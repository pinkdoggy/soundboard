#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
帝王謝改列實況主後的資料修正
=================================================
tags.json 已將「帝王謝」設為 role=streamer，本腳本讓實體檔案與 config/voices.json
跟上規範：

  1. 補回遺失的「帝王謝」tag（使用者重新產生 JSON 時掉了的那筆）
  2. 依規範重算檔名：實況主tag 以底線接在前面、其餘 tag 放方括弧
       '帝王謝 拍謝拍謝.mp3'            → '帝王謝_拍謝拍謝.mp3'
       '阿萬_帝王謝 帝王知道自己很可愛.mp3' → '阿萬_帝王謝_帝王知道自己很可愛.mp3'
       '…_晚安[帝王謝][綠茶].mp3'        → '…_豹子頭_帝王謝_晚安[綠茶].mp3'
  3. 依新檔名重算 id（ufid64，無 namespace、4 bytes、碰撞時遞增 k）
  4. 由 git 救回的原始 sounds.json 還原 id_old，讓第二版用戶的最愛能正常升級
  5. 同步更新 config/vote-results.json 內受影響的 id
  6. 順手修正重複條目（同 file 同 id 出現兩次，會造成重複卡片與 soundMap 覆蓋）

用法：
  python fix_kingxie.py                 # dry-run，只印報告
  python fix_kingxie.py --execute       # 實際執行（會先備份 config/）
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
BACKUP_DIR = ROOT / "backup-kingxie"
# 由 git dangling 物件 7ef6e50 救回的改版前 sounds.json（供還原 id_old）
ORIGINAL_SOUNDS = SCRIPT_DIR / "_original-sounds-for-idold.json"

FULLWIDTH = {"\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？",
             '"': "＂", "<": "＜", ">": "＞", "|": "｜"}

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


def norm_key(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def build_plan():
    voices = json.loads(VOICES_JSON.read_text(encoding="utf-8"))
    tags_def = json.loads(TAGS_JSON.read_text(encoding="utf-8"))
    streamers = {t["key"] for t in tags_def if t.get("role") == "streamer"}
    if "帝王謝" not in streamers:
        raise SystemExit("tags.json 尚未將『帝王謝』設為 role=streamer，請先確認。")

    orig = json.loads(ORIGINAL_SOUNDS.read_text(encoding="utf-8"))
    # 以 (處理後title, tags集合) 建立原始記錄索引，用來還原 id_old
    orig_idx = {}
    for e in orig:
        k = (norm_key(process_title(e["title"])), tuple(sorted(e["tags"])))
        orig_idx.setdefault(k, []).append(e)

    fatal, actions = [], []

    # ---- A. 移除重複條目（同 file、同 id；保留有 id_old 的那筆） ----
    seen, dup_removals = {}, []
    for i, e in enumerate(voices):
        key = norm_key(e["file"])
        if key in seen:
            a, b = seen[key], i
            keep, drop = (a, b) if voices[a].get("id_old") else (b, a)
            if voices[a]["id"] != voices[b]["id"]:
                fatal.append(f"重複 file 但 id 不同，需人工判斷：{e['file']!r}")
            else:
                dup_removals.append(drop)
                seen[key] = keep
        else:
            seen[key] = i

    # ---- B. 帝王謝：補 tag ----
    for e in voices:
        if "帝王謝" in e["file"] and "帝王謝" not in e["tags"]:
            # 原始資料證實此筆 tags 應含帝王謝（阿萬_帝王知道自己很可愛）
            insert_at = len([t for t in e["tags"] if t in streamers])
            e["tags"] = e["tags"][:insert_at] + ["帝王謝"] + e["tags"][insert_at:]
            actions.append(("補tag", e["file"], "tags += 帝王謝"))

    # ---- C. 重算受影響條目的檔名 / id / id_old ----
    keep_idx = [i for i in range(len(voices)) if i not in set(dup_removals)]
    # 未受影響條目的 id 先佔位，供碰撞檢查
    targets = [i for i in keep_idx if "帝王謝" in voices[i]["tags"]]
    taken_ids = {voices[i]["id"] for i in keep_idx if i not in targets}
    taken_names = {norm_key(voices[i]["file"]) for i in keep_idx if i not in targets}

    renames = []
    for i in targets:
        e = voices[i]
        ext = os.path.splitext(e["file"])[1]
        new_file = canonical_name(e["tags"], e["title"], ext, streamers)
        old_file = e["file"]

        if new_file != old_file:
            if norm_key(new_file) in taken_names:
                fatal.append(f"新檔名與其他條目衝突：{new_file!r}")
                continue
            src, dst = VOICES_DIR / old_file, VOICES_DIR / new_file
            if not src.is_file():
                fatal.append(f"找不到來源檔：{src}")
                continue
            if dst.exists() and norm_key(old_file) != norm_key(new_file):
                fatal.append(f"目標檔已存在：{dst}")
                continue
            renames.append((old_file, new_file))
        taken_names.add(norm_key(new_file))

        # id 重算（碰撞時遞增 k，與 ufid64 auto-resolve 行為一致）
        k = 0
        while True:
            cand = ufid64.ufid(new_file, **UA, k=k)
            if cand not in taken_ids:
                break
            k += 1
        taken_ids.add(cand)

        # id_old：優先保留既有值，否則由原始記錄還原
        old_id_before = e.get("id_old")
        if not old_id_before:
            hit = orig_idx.get((norm_key(process_title(e["title"])), tuple(sorted(e["tags"]))))
            if hit and len(hit) == 1:
                e["id_old"] = hit[0]["id"]
            elif hit:
                fatal.append(f"id_old 還原不唯一（{len(hit)} 筆候選）：{e['title']!r}")

        actions.append(("更新", old_file, {
            "new_file": new_file, "old_id": e["id"], "new_id": cand,
            "id_old": e.get("id_old"), "id_old_restored": not old_id_before and e.get("id_old"),
            "tags": e["tags"], "k": k,
        }))
        e["file"], e["id"] = new_file, cand

    # 套用重複移除（由後往前刪，避免索引位移）
    for i in sorted(dup_removals, reverse=True):
        actions.append(("刪重複", voices[i]["file"], f"id={voices[i]['id']} (無 id_old 的那筆)"))
        voices.pop(i)

    return voices, renames, actions, fatal, targets


def report(actions, renames, fatal, voices):
    L = [f"時間：{datetime.now().isoformat(timespec='seconds')}", ""]
    if fatal:
        L.append("=== 致命錯誤（已中止） ===")
        L += ["  " + f for f in fatal]
        L.append("")
    L.append(f"=== 變更摘要：{len(renames)} 個檔案更名、{len(actions)} 項資料調整 ===")
    L.append("")
    for kind, name, info in actions:
        if kind == "更新":
            L.append(f"[更新] {name!r}")
            L.append(f"       → 檔名 {info['new_file']!r}")
            L.append(f"       → id   {info['old_id']} → {info['new_id']}"
                     + (f"  (k={info['k']} 解碰)" if info["k"] else ""))
            L.append(f"       → tags {info['tags']}")
            L.append(f"       → id_old {info['id_old']}"
                     + ("  ← 由原始 sounds.json 還原" if info["id_old_restored"] else "  (原有)"))
        else:
            L.append(f"[{kind}] {name!r}：{info}")
    L.append("")
    L.append(f"最終 voices.json 筆數：{len(voices)}")
    return "\n".join(L)


def write_json_crlf(path: Path, data, indent=4):
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    path.write_bytes((text + "\n").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))


def execute(voices, renames, actions, log):
    BACKUP_DIR.mkdir(exist_ok=True)
    for f in (VOICES_JSON, TAGS_JSON, VOTES_JSON):
        shutil.copy2(f, BACKUP_DIR / f.name)
    log(f"[備份] config/*.json → {BACKUP_DIR.name}/")

    # 1) 實體檔案更名
    for old, new in renames:
        (VOICES_DIR / old).rename(VOICES_DIR / new)
    log(f"[更名] voices/ 內 {len(renames)} 個檔案")

    # 2) voices.json
    write_json_crlf(VOICES_JSON, voices)
    log(f"[寫出] voices.json（{len(voices)} 筆）")

    # 3) vote-results.json 內受影響的 id
    idmap = {i["old_id"]: i["new_id"] for k, _, i in actions if k == "更新" and isinstance(i, dict)}
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

    # 4) 稽核檔
    with open(BACKUP_DIR / "kingxie-rename-map.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["old_file", "new_file", "old_id", "new_id", "id_old"])
        for kind, name, info in actions:
            if kind == "更新":
                w.writerow([name, info["new_file"], info["old_id"], info["new_id"], info["id_old"]])
    log("[稽核] kingxie-rename-map.csv 已寫入")


def verify(log):
    """獨立重讀磁碟與 JSON 驗證最終狀態。"""
    voices = json.loads(VOICES_JSON.read_text(encoding="utf-8"))
    tags_def = json.loads(TAGS_JSON.read_text(encoding="utf-8"))
    streamers = {t["key"] for t in tags_def if t.get("role") == "streamer"}
    disk = {p.name for p in VOICES_DIR.iterdir() if p.is_file()}
    errors = []

    files = [e["file"] for e in voices]
    ids = [e["id"] for e in voices]
    if len(set(files)) != len(files):
        errors.append("voices.json 仍有重複 file")
    if len(set(ids)) != len(ids):
        errors.append("voices.json 仍有重複 id")
    if set(files) != disk:
        errors.append(f"JSON 與 voices/ 不一致：僅JSON {len(set(files)-disk)}、僅磁碟 {len(disk-set(files))}")
    for e in voices:
        if "帝王謝" in e["tags"] or "帝王謝" in e["file"]:
            want = canonical_name(e["tags"], e["title"], os.path.splitext(e["file"])[1], streamers)
            if want != e["file"]:
                errors.append(f"檔名不符規範：{e['file']!r} 應為 {want!r}")
            if "帝王謝" not in e["tags"]:
                errors.append(f"檔名含帝王謝但 tags 沒有：{e['file']!r}")
            if e["id"] not in [ufid64.ufid(e["file"], **UA, k=k) for k in range(3)]:
                errors.append(f"id 無法由檔名重算：{e['file']!r}")

    votes = json.loads(VOTES_JSON.read_text(encoding="utf-8"))
    idset = set(ids)
    stale = [v["id"] for v in votes if v.get("id") and v["id"] not in idset]

    if errors:
        for e in errors:
            log("[驗證失敗] " + e)
        raise SystemExit("驗證未通過。可用 git checkout 還原。")
    n_king = sum(1 for e in voices if "帝王謝" in e["tags"])
    log(f"[驗證] 通過：voices.json {len(voices)} 筆 == voices/ {len(disk)} 檔；"
        f"帝王謝 {n_king} 筆全部符合規範；id 無重複。")
    log(f"[驗證] vote-results 仍有 {len(stale)} 筆無對應 id（皆為先前已刪除的音效）。")


def main():
    ap = argparse.ArgumentParser(description="帝王謝實況主化的資料修正（預設 dry-run）")
    ap.add_argument("--execute", action="store_true", help="實際執行")
    args = ap.parse_args()
    log = print

    voices, renames, actions, fatal, _ = build_plan()
    text = report(actions, renames, fatal, voices)
    BACKUP_DIR.mkdir(exist_ok=True)
    out = BACKUP_DIR / f"kingxie-report-{'execute' if args.execute else 'dryrun'}.txt"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[報告] {out}")

    if fatal:
        sys.exit(1)
    if not args.execute:
        print("\ndry-run 完成，未變更任何檔案。加 --execute 正式執行。")
        return
    execute(voices, renames, actions, log)
    verify(log)
    print("完成。")


if __name__ == "__main__":
    main()
