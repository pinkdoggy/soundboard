#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voices 檔名／id 規範校正（通用，可重複執行）
=====================================================
注意：本腳本處理的是「檔名與 id 的命名規範」，與音訊的音量正規化
（loudnorm，見 轉檔v3.py）完全無關。

掃描 config/voices.json，讓每筆資料回到規範狀態：

  1. 檔名 = <實況主tag>_<實況主tag>_<title>[其他tag][其他tag].<副檔名>
     （實況主 = tags.json 中 role=streamer；tag 順序沿用 json 內的順序；
       title 經過「底線→空白、Windows 禁用字元→全形、trim」處理）
     檔名與此不符者 → 以 title/tags 為準重新命名實體檔案。
  2. id 必須能由檔名以 ufid64 重算（無 namespace、4 bytes、碰撞時遞增 k）。
     已經有效的 id 一律保留不動；只有失效的才重新計算。
  3. id_old 原封不動保留（第二版用戶最愛升級的依據）。
  4. 受影響的 id 同步更新到 config/vote-results.json。

設計原則：只碰真正不符規範的條目，正常條目連 id 都不會變動，
因此可以放心重複執行（冪等）。

用法：
  python fix_voices_naming.py            # dry-run，只印報告
  python fix_voices_naming.py --execute  # 實際執行（會先備份 config/）
"""

import argparse
import csv
import importlib.util
import json
import os
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
VOICES_DIR = ROOT / "voices"
VOICES_JSON = ROOT / "config" / "voices.json"
TAGS_JSON = ROOT / "config" / "tags.json"
VOTES_JSON = ROOT / "config" / "vote-results.json"
BACKUP_DIR = ROOT / "backup-voices-naming"

FULLWIDTH = {"\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？",
             '"': "＂", "<": "＜", ">": "＞", "|": "｜"}
MAX_K = 8  # id 解碰上限

_spec = importlib.util.spec_from_file_location("ufid64", SCRIPT_DIR / "ufid64.py")
ufid64 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ufid64)
UA = dict(namespace=None, norm="nfkc", do_casefold=True, do_strip=True, nbytes=4)


def process_title(t: str) -> str:
    s = t.replace("_", " ")
    s = "".join(FULLWIDTH.get(c, c) for c in s)
    return s.strip()


def canonical_name(tags, title, ext, streamers) -> str:
    st = [t for t in tags if t in streamers]
    ot = [t for t in tags if t not in streamers]
    pre = "_".join(st)
    return (pre + "_" if pre else "") + process_title(title) + "".join(f"[{t}]" for t in ot) + ext


def nkey(s: str) -> str:
    """Windows 檔名比對鍵：NFC + casefold。"""
    return unicodedata.normalize("NFC", s).casefold()


def valid_ids_for(filename: str):
    return [ufid64.ufid(filename, **UA, k=k) for k in range(MAX_K)]


def build_plan():
    voices = json.loads(VOICES_JSON.read_text(encoding="utf-8"))
    tags_def = json.loads(TAGS_JSON.read_text(encoding="utf-8"))
    streamers = {t["key"] for t in tags_def if t.get("role") == "streamer"}
    fatal, changes = [], []

    # ---- 1. 算出每筆的目標檔名 ----
    plan = []
    for i, e in enumerate(voices):
        ext = os.path.splitext(e["file"])[1]
        want = canonical_name(e["tags"], e["title"], ext, streamers)
        plan.append({"i": i, "old_file": e["file"], "new_file": want,
                     "old_id": e["id"], "new_id": e["id"], "renamed": want != e["file"]})

    # 目標檔名不可互相衝突
    seen = {}
    for p in plan:
        k = nkey(p["new_file"])
        if k in seen:
            fatal.append(f"目標檔名衝突：{p['old_file']!r} 與 {plan[seen[k]]['old_file']!r} "
                         f"都要變成 {p['new_file']!r}")
        seen[k] = p["i"]

    # ---- 2. id：有效者保留，失效者重算 ----
    # 先收集「不需變動」的 id 佔位
    need_fix = []
    taken = set()
    for p in plan:
        e = voices[p["i"]]
        if e["id"] in valid_ids_for(p["new_file"]):
            taken.add(e["id"])          # 對新檔名仍然有效 → 保留
        else:
            need_fix.append(p)
    for p in need_fix:
        for k in range(MAX_K):
            cand = ufid64.ufid(p["new_file"], **UA, k=k)
            if cand not in taken:
                p["new_id"], p["k"] = cand, k
                taken.add(cand)
                break
        else:
            fatal.append(f"id 解碰超過 {MAX_K} 次：{p['new_file']!r}")

    # ---- 3. 檔案更名的可行性檢查 ----
    renames = [(p["old_file"], p["new_file"]) for p in plan if p["renamed"]]
    disk = {nkey(x.name): x.name for x in VOICES_DIR.iterdir() if x.is_file()}
    for old, new in renames:
        if nkey(old) not in disk:
            fatal.append(f"找不到來源檔：{old!r}")
        if nkey(new) in disk and nkey(new) != nkey(old):
            fatal.append(f"目標檔已存在：{new!r}")

    for p in plan:
        if p["renamed"] or p["new_id"] != p["old_id"]:
            changes.append(p)
    return voices, plan, changes, renames, fatal


def report(changes, renames, fatal, total):
    L = [f"時間：{datetime.now().isoformat(timespec='seconds')}",
         f"voices.json 共 {total} 筆；需調整 {len(changes)} 筆（其中 {len(renames)} 筆需更名實體檔案）", ""]
    if fatal:
        L.append("=== 致命錯誤（已中止） ===")
        L += ["  " + f for f in fatal] + [""]
    for p in changes:
        L.append(f"[{p['i']}] {p['old_file']!r}")
        if p["renamed"]:
            L.append(f"      檔名 → {p['new_file']!r}")
        else:
            L.append(f"      檔名不變（{p['new_file']!r}）")
        if p["new_id"] != p["old_id"]:
            L.append(f"      id   {p['old_id']} → {p['new_id']}"
                     + (f"  (k={p.get('k')} 解碰)" if p.get("k") else ""))
        else:
            L.append(f"      id   {p['old_id']}（不變）")
    if not changes:
        L.append("已完全符合規範，無須調整。")
    return "\n".join(L)


def write_json_crlf(path: Path, data, indent=4):
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    path.write_bytes((text + "\n").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))


def execute(voices, plan, changes, renames, log):
    BACKUP_DIR.mkdir(exist_ok=True)
    for f in (VOICES_JSON, TAGS_JSON, VOTES_JSON):
        shutil.copy2(f, BACKUP_DIR / f.name)
    log(f"[備份] config/*.json → {BACKUP_DIR.name}/")

    for old, new in renames:
        (VOICES_DIR / old).rename(VOICES_DIR / new)
    log(f"[更名] voices/ 內 {len(renames)} 個檔案")

    idmap = {}
    for p in plan:
        e = voices[p["i"]]
        e["file"] = p["new_file"]
        if p["new_id"] != p["old_id"]:
            idmap[p["old_id"]] = p["new_id"]
            e["id"] = p["new_id"]
    write_json_crlf(VOICES_JSON, voices)
    log(f"[寫出] voices.json（{len(voices)} 筆，{len(idmap)} 筆 id 變更）")

    votes = json.loads(VOTES_JSON.read_text(encoding="utf-8"))
    n = 0
    for v in votes:
        if v.get("id") in idmap:
            v["id"] = idmap[v["id"]]
            n += 1
    if n:
        VOTES_JSON.write_text(json.dumps(votes, ensure_ascii=False, indent=2),
                              encoding="utf-8", newline="\n")
    log(f"[更新] vote-results.json（{n} 筆 id 重對應）")

    with open(BACKUP_DIR / "naming-fix-map.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["old_file", "new_file", "old_id", "new_id"])
        for p in changes:
            w.writerow([p["old_file"], p["new_file"], p["old_id"], p["new_id"]])
    log("[稽核] naming-fix-map.csv 已寫入")


def verify(log):
    """重讀磁碟與 JSON 做獨立驗證。"""
    voices = json.loads(VOICES_JSON.read_text(encoding="utf-8"))
    tags_def = json.loads(TAGS_JSON.read_text(encoding="utf-8"))
    streamers = {t["key"] for t in tags_def if t.get("role") == "streamer"}
    disk = {p.name for p in VOICES_DIR.iterdir() if p.is_file()}
    errors = []

    files = [e["file"] for e in voices]
    ids = [e["id"] for e in voices]
    if len(set(files)) != len(files):
        errors.append("voices.json 有重複 file")
    if len(set(ids)) != len(ids):
        errors.append("voices.json 有重複 id")
    if set(files) != disk:
        errors.append(f"JSON 與 voices/ 不一致：僅JSON {len(set(files)-disk)}、僅磁碟 {len(disk-set(files))}")
    for e in voices:
        want = canonical_name(e["tags"], e["title"], os.path.splitext(e["file"])[1], streamers)
        if want != e["file"]:
            errors.append(f"檔名仍不符規範：{e['file']!r} 應為 {want!r}")
        if e["id"] not in valid_ids_for(e["file"]):
            errors.append(f"id 仍無法由檔名重算：{e['file']!r}")

    if errors:
        for e in errors[:20]:
            log("[驗證失敗] " + e)
        raise SystemExit("驗證未通過。備份在 " + str(BACKUP_DIR))
    log(f"[驗證] 通過：{len(voices)} 筆全部符合檔名規範、id 皆可由檔名重算、"
        f"與 voices/ {len(disk)} 檔完全對帳。")


def main():
    ap = argparse.ArgumentParser(description="voices 檔名／id 規範校正（預設 dry-run）")
    ap.add_argument("--execute", action="store_true", help="實際執行")
    args = ap.parse_args()
    log = print

    voices, plan, changes, renames, fatal = build_plan()
    text = report(changes, renames, fatal, len(voices))
    BACKUP_DIR.mkdir(exist_ok=True)
    out = BACKUP_DIR / f"naming-fix-report-{'execute' if args.execute else 'dryrun'}.txt"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[報告] {out}")

    if fatal:
        sys.exit(1)
    if not changes:
        return
    if not args.execute:
        print("\ndry-run 完成，未變更任何檔案。加 --execute 正式執行。")
        return
    execute(voices, plan, changes, renames, log)
    verify(log)
    print("完成。")


if __name__ == "__main__":
    main()
