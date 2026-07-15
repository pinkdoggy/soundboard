#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音效板大翻新遷移腳本：sounds/ + sounds.json → voices/ + voices.json
=====================================================================

流程（--execute 前皆為 dry-run，不動任何檔案）：
  0. 備份    ── 將 sounds/ 整包壓縮、config 與 index html 複本存到備份資料夾
  1. 建立計畫 ── 依 config/sounds.json 的 file/title/tags 計算每筆的新檔名與新 id
  2. 檢查    ── 缺檔、孤兒、檔名衝突（Windows 大小寫不敏感 + NFC）、id 碰撞、
               保留字、空標題等邊角情況；任何致命問題直接中止
  3. 執行    ── 登記檔「複製」到 voices/（原檔保留於 sounds/ 不動）、
               孤兒檔「移動」到 voices_orphan/、寫出 config/voices.json、
               同步 config/sounds.json 的 title、重對應 config/vote-results.json 的 id
  4. 驗證    ── 檔案數量、逐檔大小比對、id 唯一性與可重算性

新檔名格式（依使用者規範）：
  <實況主tag>_<實況主tag>_<title>[其他tag][其他tag].<副檔名>
  - 實況主tag = tags.json 中 role == "streamer" 的標籤（維持 sounds.json 內順序）
  - 其他 tag  = 其餘標籤（維持順序），每個獨立一組方括弧
  - title 處理：底線→空白、Windows 禁用字元→對應全形、前後空白 trim
  - 處理後 title 同步寫回 json 的 title 欄位

id 規則：依 ufid64.py（BLAKE2b、namespace=無、NFKC+casefold+strip、4 bytes、
auto-resolve k=0,1,2…），舊 id 改存於 id_old。

用法：
  python migrate_voices.py            # dry-run（只產生報告）
  python migrate_voices.py --execute  # 實際執行（先自動備份）
"""

import argparse
import csv
import importlib.util
import json
import shutil
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
SOUNDS_DIR = ROOT / "sounds"
VOICES_DIR = ROOT / "voices"
ORPHAN_DIR = ROOT / "voices_orphan"
SOUNDS_JSON = ROOT / "config" / "sounds.json"
TAGS_JSON = ROOT / "config" / "tags.json"
VOTES_JSON = ROOT / "config" / "vote-results.json"
VOICES_JSON = ROOT / "config" / "voices.json"
BACKUP_DIR = ROOT / "backup-pre-voices-20260715"

# tags.json 之外額外認定為實況主的標籤（tags.json 補上 role=streamer 後可移除）
EXTRA_STREAMERS = {"帝王謝"}

# Windows 禁用字元 → 全形對應
FULLWIDTH = {
    "\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？",
    '"': "＂", "<": "＜", ">": "＞", "|": "｜",
}
RESERVED = {"CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

# ufid64.py 動態載入（沿用專案的 id 計算方法）
_spec = importlib.util.spec_from_file_location("ufid64", SCRIPT_DIR / "ufid64.py")
ufid64 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ufid64)

UFID_ARGS = dict(namespace=None, norm="nfkc", do_casefold=True, do_strip=True, nbytes=4)


def process_title(title: str) -> str:
    """依規範處理 title：底線→空白、禁用字元→全形、trim。"""
    s = title.replace("_", " ")
    s = "".join(FULLWIDTH.get(c, c) for c in s)
    return s.strip()


def collision_key(name: str) -> str:
    """Windows 檔名衝突判定鍵：NFC 正規化 + 大小寫折疊。"""
    return unicodedata.normalize("NFC", name).casefold()


def build_new_filename(streamers, others, title, ext) -> str:
    prefix = "_".join(streamers)
    return (prefix + "_" if prefix else "") + title + "".join(f"[{t}]" for t in others) + ext


def load_inputs():
    sounds = json.loads(SOUNDS_JSON.read_text(encoding="utf-8"))
    tags_def = json.loads(TAGS_JSON.read_text(encoding="utf-8"))
    votes = json.loads(VOTES_JSON.read_text(encoding="utf-8"))
    streamer_set = {t["key"] for t in tags_def if t.get("role") == "streamer"} | EXTRA_STREAMERS
    return sounds, streamer_set, votes


def build_plan(sounds, streamer_set, log):
    """為每筆 sounds.json 記錄計算新檔名/新 title/新 id 與來源檔案。

    回傳 (plan, orphans, fatal)：
      plan   : list of dict(entry 原順序)，含 excluded 記錄（missing file）
      orphans: sounds/ 內未登記的檔名 list
      fatal  : list of 致命錯誤字串（非空即應中止）
    """
    fatal = []

    # ---- 磁碟盤點 ----
    if not SOUNDS_DIR.is_dir():
        return [], [], [f"找不到音效資料夾：{SOUNDS_DIR}"]
    sub = [p for p in SOUNDS_DIR.iterdir() if p.is_dir()]
    if sub:
        fatal.append(f"sounds/ 內含子資料夾（腳本僅支援單層）：{[p.name for p in sub]}")
    disk = {p.name for p in SOUNDS_DIR.iterdir() if p.is_file()}
    by_nfc = {}
    by_ci = {}
    for n in disk:
        by_nfc.setdefault(unicodedata.normalize("NFC", n), []).append(n)
        by_ci.setdefault(collision_key(n), []).append(n)

    def locate(fname):
        """registered file 欄位 → 實際磁碟檔名（None = 缺檔）。"""
        if fname in disk:
            return fname, "exact"
        c = by_nfc.get(unicodedata.normalize("NFC", fname))
        if c and len(c) == 1:
            return c[0], "nfc"
        c = by_ci.get(collision_key(fname))
        if c and len(c) == 1:
            return c[0], "casefold"
        return None, None

    # ---- 逐筆建立計畫 ----
    plan = []
    dup_file_check = {}
    for idx, e in enumerate(sounds):
        fname, title, tags, old_id = e["file"], e["title"], e["tags"], e.get("id")
        src, how = locate(fname)
        ext = "." + fname.rsplit(".", 1)[1] if "." in fname else ""
        if not ext:
            fatal.append(f"[{idx}] {fname!r}：無副檔名")
        streamers = [t for t in tags if t in streamer_set]
        others = [t for t in tags if t not in streamer_set]
        for t in tags:
            if any(c in FULLWIDTH or c in "[]_" for c in t):
                fatal.append(f"[{idx}] {fname!r}：tag {t!r} 含檔名不允許/會破壞格式的字元，請先修正資料")
        new_title = process_title(title)
        if not new_title:
            fatal.append(f"[{idx}] {fname!r}：title {title!r} 處理後為空")
        plan.append({
            "index": idx, "old_file": fname, "src_name": src, "src_how": how,
            "old_title": title, "new_title": new_title,
            "tags": list(tags), "streamers": streamers, "others": others,
            "ext": ext, "old_id": old_id, "new_file": None, "new_id": None,
            "excluded": src is None, "disamb": 0,
        })
        if fname in dup_file_check:
            fatal.append(f"[{idx}] file 欄位重複：{fname!r}")
        dup_file_check[fname] = idx

    # ---- 檔名產生 + 衝突消歧（JSON 順序在前者保留原名，其後加 (2)(3)…） ----
    taken = {}
    for p in plan:
        if p["excluded"]:
            continue
        cand_title = p["new_title"]
        n = 1
        while True:
            new_file = build_new_filename(p["streamers"], p["others"], cand_title, p["ext"])
            key = collision_key(new_file)
            if key not in taken:
                break
            n += 1
            if n > 99:
                fatal.append(f"[{p['index']}] {p['old_file']!r}：檔名消歧超過 99 次，中止")
                break
            cand_title = p["new_title"] + f"({n})"
        if n > 99:
            continue
        if n > 1:
            p["disamb"] = n
            p["new_title"] = cand_title
        p["new_file"] = new_file
        taken[key] = p["index"]
        stem = new_file.split(".", 1)[0]
        if stem.upper() in RESERVED:
            fatal.append(f"[{p['index']}] 新檔名為 Windows 保留字：{new_file!r}")

    # ---- 孤兒 ----
    claimed = {p["src_name"] for p in plan if p["src_name"]}
    orphans = sorted(disk - claimed)

    # ---- 新 id（沿用 ufid64 auto-resolve：k=0,1,2…，穩定順序） ----
    active = [p for p in plan if not p["excluded"]]
    records = [{"file": p["new_file"]} for p in active]
    try:
        ufid64.assign_ids_auto_resolve(
            records, None, True, "nfkc", True, True, 4)
    except SystemExit as se:
        fatal.append(f"id 產生失敗：{se}")
        return plan, orphans, fatal
    for p, r in zip(active, records):
        p["new_id"] = r["id"]
        k0 = ufid64.ufid(p["new_file"], **UFID_ARGS, k=0)
        p["id_k"] = 0 if r["id"] == k0 else ">0"

    ids = [p["new_id"] for p in active]
    if len(ids) != len(set(ids)):
        fatal.append("新 id 有重複（不應發生）")
    return plan, orphans, fatal


def make_report(plan, orphans, fatal, sounds, votes):
    L = []
    p = L.append
    active = [x for x in plan if not x["excluded"]]
    excluded = [x for x in plan if x["excluded"]]
    p(f"時間：{datetime.now().isoformat(timespec='seconds')}")
    p(f"sounds.json 記錄：{len(sounds)}；可遷移：{len(active)}；缺檔排除：{len(excluded)}")
    p(f"sounds/ 孤兒檔（將移至 voices_orphan/）：{len(orphans)}")
    p("")
    if fatal:
        p("=== 致命錯誤（已中止，未動任何檔案） ===")
        for f in fatal:
            p("  " + f)
        p("")
    if excluded:
        p("=== 登記於 json 但磁碟缺檔（不納入 voices.json，請人工確認） ===")
        for x in excluded:
            p(f"  {x['old_file']!r} (id={x['old_id']})")
        p("")
    fuzzy = [x for x in active if x["src_how"] != "exact"]
    if fuzzy:
        p("=== 以 NFC/大小寫寬鬆比對找到來源檔 ===")
        for x in fuzzy:
            p(f"  {x['old_file']!r} -> 磁碟 {x['src_name']!r} ({x['src_how']})")
        p("")
    dis = [x for x in active if x["disamb"]]
    if dis:
        p("=== 檔名/標題消歧（同名衝突，title 加 (n) 後同步回 json） ===")
        for x in dis:
            p(f"  {x['old_file']!r}: title {x['old_title']!r} -> {x['new_title']!r} -> {x['new_file']!r}")
        p("")
    zero = [x for x in active if not x["streamers"]]
    if zero:
        p("=== 無實況主標籤的記錄（檔名無前綴，請確認是否需補 tags.json 角色定義） ===")
        for x in zero:
            p(f"  {x['old_file']!r} tags={x['tags']} -> {x['new_file']!r}")
        p("")
    kk = [x for x in active if x.get("id_k") == ">0"]
    if kk:
        p("=== id 以 k>0 解碰（NFKC+casefold 後同值的檔名對） ===")
        for x in kk:
            p(f"  {x['new_file']!r} -> id={x['new_id']}")
        p("")
    # 舊 id 重複
    seen = {}
    for x in plan:
        seen.setdefault(x["old_id"], []).append(x["old_file"])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        p("=== 舊 id 重複（遷移對照採「後者優先」，與舊網頁 Map 行為一致） ===")
        for k, v in dups.items():
            p(f"  {k}: {v}")
        p("")
    # 舊 id 與舊檔名不符（歷史遺留，僅供參考）
    stale = [x for x in plan
             if x["old_id"] and ufid64.ufid(x["old_file"], **UFID_ARGS, k=0) != x["old_id"]]
    if stale:
        p(f"=== 舊 id 與 ufid(舊檔名) 不符（{len(stale)} 筆，歷史遺留僅記錄） ===")
        for x in stale[:20]:
            p(f"  {x['old_file']!r} id={x['old_id']}")
        p("")
    # vote-results 對照狀況
    idmap = {x["old_id"]: x["new_id"] for x in active}
    unmapped = [v.get("id") for v in votes if v.get("id") and v["id"] not in idmap]
    p(f"vote-results.json：{len(votes)} 筆，可重對應 {sum(1 for v in votes if v.get('id') in idmap)} 筆，"
      f"無對應保留原值 {len(unmapped)} 筆：{unmapped}")
    p("")
    p("=== 孤兒檔清單 ===")
    for n in orphans:
        p(f"  {n!r}")
    return "\n".join(L)


def write_json_crlf(path: Path, data, indent=4):
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    path.write_bytes((text + "\n").replace("\n", "\r\n").encode("utf-8"))


def do_backup(log):
    BACKUP_DIR.mkdir(exist_ok=True)
    for f in (SOUNDS_JSON, TAGS_JSON, VOTES_JSON, ROOT / "index-raw.html", ROOT / "index.html"):
        if f.exists():
            shutil.copy2(f, BACKUP_DIR / f.name)
            log(f"[備份] {f.name}")
    zip_path = BACKUP_DIR / "sounds-full-backup.zip"
    if not zip_path.exists():
        files = sorted(p for p in SOUNDS_DIR.iterdir() if p.is_file())
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
            for f in files:
                z.write(f, f"sounds/{f.name}")
        log(f"[備份] sounds/ 共 {len(files)} 檔 → {zip_path.name}"
            f"（{zip_path.stat().st_size/1e6:.1f} MB）")
    else:
        log(f"[備份] {zip_path.name} 已存在，略過重壓縮")


def do_execute(plan, orphans, sounds, votes, log):
    active = [x for x in plan if not x["excluded"]]

    if VOICES_DIR.exists() and any(VOICES_DIR.iterdir()):
        raise SystemExit(f"{VOICES_DIR} 已存在且非空，為避免混入舊資料請先處理。")
    # 允許 voices_orphan/ 已存在（重跑情境），但不得與本次要移動的孤兒同名
    clash = [n for n in orphans if (ORPHAN_DIR / n).exists()]
    if clash:
        raise SystemExit(f"voices_orphan/ 已有同名檔案，請先處理：{clash[:5]}")
    VOICES_DIR.mkdir(exist_ok=True)
    ORPHAN_DIR.mkdir(exist_ok=True)

    # 1) 複製登記檔 → voices/（sounds/ 內原檔不動）
    for x in active:
        src = SOUNDS_DIR / x["src_name"]
        dst = VOICES_DIR / x["new_file"]
        if dst.exists():
            raise SystemExit(f"目標已存在（不應發生）：{dst}")
        shutil.copy2(src, dst)
    log(f"[複製] {len(active)} 檔 → voices/")

    # 2) 移動孤兒 → voices_orphan/
    for n in orphans:
        shutil.move(str(SOUNDS_DIR / n), str(ORPHAN_DIR / n))
    log(f"[移動] {len(orphans)} 孤兒檔 → voices_orphan/")

    # 3) config/voices.json（維持 sounds.json 原順序；id_old 保留舊 id）
    out = [{"file": x["new_file"], "title": x["new_title"], "tags": x["tags"],
            "id": x["new_id"], "id_old": x["old_id"]} for x in active]
    write_json_crlf(VOICES_JSON, out)
    log(f"[寫出] {VOICES_JSON.name}（{len(out)} 筆）")

    # 4) 同步 sounds.json 的 title（其餘欄位不動；缺檔記錄也同步）
    for x, e in zip(plan, sounds):
        assert e["file"] == x["old_file"]
        e["title"] = x["new_title"] if not x["excluded"] else process_title(e["title"])
    write_json_crlf(SOUNDS_JSON, sounds)
    log(f"[更新] {SOUNDS_JSON.name}（title 同步）")

    # 5) vote-results.json：id 重對應（無對應者保留原值）
    idmap = {x["old_id"]: x["new_id"] for x in active}
    changed = 0
    for v in votes:
        if v.get("id") in idmap:
            v["id"] = idmap[v["id"]]
            changed += 1
    VOTES_JSON.write_text(json.dumps(votes, ensure_ascii=False, indent=2),
                          encoding="utf-8", newline="\n")
    log(f"[更新] {VOTES_JSON.name}（重對應 {changed}/{len(votes)} 筆）")

    # 6) 稽核檔
    with open(BACKUP_DIR / "rename-map.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["old_file", "new_file", "id_old", "id_new", "note"])
        for x in plan:
            w.writerow([x["old_file"], x["new_file"] or "", x["old_id"] or "",
                        x["new_id"] or "", "MISSING-FILE" if x["excluded"] else ""])
        for n in orphans:
            w.writerow([n, "(voices_orphan)", "", "", "ORPHAN"])
    (BACKUP_DIR / "id-map.json").write_text(
        json.dumps(idmap, ensure_ascii=False, indent=2), encoding="utf-8")
    log("[稽核] rename-map.csv / id-map.json 已寫入備份資料夾")


def do_verify(plan, orphans, log):
    """遷移後驗證：檔案數、逐檔大小、id 唯一且可重算。"""
    active = [x for x in plan if not x["excluded"]]
    errors = []

    voices_files = {p.name for p in VOICES_DIR.iterdir() if p.is_file()}
    if len(voices_files) != len(active):
        errors.append(f"voices/ 檔案數 {len(voices_files)} != 計畫 {len(active)}")
    for x in active:
        dst = VOICES_DIR / x["new_file"]
        src = SOUNDS_DIR / x["src_name"]
        if not dst.is_file():
            errors.append(f"缺少輸出：{dst.name!r}")
        elif dst.stat().st_size != src.stat().st_size:
            errors.append(f"大小不符：{dst.name!r}")

    orphan_files = {p.name for p in ORPHAN_DIR.iterdir() if p.is_file()}
    if not set(orphans) <= orphan_files:
        errors.append(f"voices_orphan/ 缺少本次應移入的孤兒檔（{len(orphan_files)} vs {len(orphans)}）")

    data = json.loads(VOICES_JSON.read_text(encoding="utf-8"))
    ids = [e["id"] for e in data]
    files = [e["file"] for e in data]
    if len(set(ids)) != len(ids):
        errors.append("voices.json id 重複")
    if len(set(files)) != len(files):
        errors.append("voices.json file 重複")
    if {e["file"] for e in data} != voices_files:
        errors.append("voices.json 與 voices/ 檔案清單不一致")
    for e in data:
        k0 = ufid64.ufid(e["file"], **UFID_ARGS, k=0)
        if e["id"] != k0 and e["id"] != ufid64.ufid(e["file"], **UFID_ARGS, k=1):
            errors.append(f"id 無法由檔名重算：{e['file']!r}")

    if errors:
        for e in errors:
            log("[驗證失敗] " + e)
        raise SystemExit("驗證未通過，請檢查上列錯誤。備份在 " + str(BACKUP_DIR))
    log(f"[驗證] 通過：voices/ {len(voices_files)} 檔、孤兒 {len(orphan_files)} 檔、"
        f"voices.json {len(data)} 筆，id/檔名皆唯一且可重算。")


def main():
    ap = argparse.ArgumentParser(description="sounds → voices 遷移（預設 dry-run）")
    ap.add_argument("--execute", action="store_true", help="實際執行（會先備份）")
    args = ap.parse_args()
    log = print

    sounds, streamer_set, votes = load_inputs()
    plan, orphans, fatal = build_plan(sounds, streamer_set, log)
    report = make_report(plan, orphans, fatal, sounds, votes)

    BACKUP_DIR.mkdir(exist_ok=True)
    mode = "execute" if args.execute else "dryrun"
    report_path = BACKUP_DIR / f"migration-report-{mode}.txt"
    report_path.write_text(report, encoding="utf-8")
    log(f"[報告] {report_path}")

    if fatal:
        log("發現致命錯誤，中止。詳見報告。")
        sys.exit(1)

    if not args.execute:
        log("dry-run 完成，未動任何檔案。加上 --execute 正式執行。")
        return

    do_backup(log)
    do_execute(plan, orphans, sounds, votes, log)
    do_verify(plan, orphans, log)
    log("全部完成。")


if __name__ == "__main__":
    main()
