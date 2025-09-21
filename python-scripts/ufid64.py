#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UFID v1 (configurable length)
- 從 'file' 欄位產生決定性的 ID，長度可選 4/8/16 bytes（預設 4）
- 預設正規化：Unicode NFKC + casefold + strip（可調整/關閉）
- Hash：BLAKE2b(digest_size=nbytes), person='UFIDv1', salt=sha256(namespace)[:16] (若提供)
- 編碼：Base64url（無 padding）；nbytes=4/8/16 時字串長度約為 6/11/22
- 模式：
  * 嚴格（預設）：補缺 id → 檢查碰撞（任何重複即中止）→ 驗證既有 id 與本次參數一致性（預設警告，可選中止）
  * --auto-resolve：穩定順序 + k=0,1,2… 重算直到不碰撞；可加 --force 對全部重算
"""

import argparse
import base64
import hashlib
import json
import sys
import unicodedata
from typing import Optional, Dict, List, Any

# ---------- Transform (configurable) ----------

def transform_name(name: str, norm: str, do_casefold: bool, do_strip: bool) -> str:
    s = name
    if norm and norm.lower() != "none":
        s = unicodedata.normalize(norm.upper(), s)
    if do_casefold:
        s = s.casefold()
    if do_strip:
        s = s.strip()
    return s

def _salt_from_namespace(namespace: Optional[str]) -> Optional[bytes]:
    if not namespace:
        return None
    return hashlib.sha256(namespace.encode("utf-8")).digest()[:16]  # 16 bytes

def ufid(filename: str, namespace: Optional[str], k: int,
         norm: str, do_casefold: bool, do_strip: bool, nbytes: int) -> str:
    if not isinstance(filename, str) or not filename:
        raise ValueError("filename must be a non-empty string")
    transformed = transform_name(filename, norm, do_casefold, do_strip)
    payload = f"ufid:v1:{namespace or ''}:{transformed}:{k}".encode("utf-8")

    # blake2b 不接受 salt=None；僅在有 namespace 時才帶入
    kwargs = {"digest_size": nbytes, "person": b"UFIDv1"}
    salt = _salt_from_namespace(namespace)
    if salt is not None:
        kwargs["salt"] = salt

    h = hashlib.blake2b(payload, **kwargs)
    raw = h.digest()  # nbytes
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

# ---------- Collision & verification helpers ----------

def _collect_ids(records: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    idx_by_id: Dict[str, List[int]] = {}
    for i, obj in enumerate(records):
        if isinstance(obj, dict):
            v = obj.get("id")
            if v is not None:
                idx_by_id.setdefault(str(v), []).append(i)
    return idx_by_id

def _find_duplicates(records: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    dup: Dict[str, List[int]] = {}
    idx_by_id = _collect_ids(records)
    for k, lst in idx_by_id.items():
        if len(lst) > 1:
            dup[k] = lst
    return dup

def _report_duplicates(records: List[Dict[str, Any]], dup: Dict[str, List[int]]) -> str:
    lines = ["Collision(s) detected:"]
    for idv, idxs in dup.items():
        lines.append(f"  id={idv} -> {len(idxs)} records")
        for i in idxs:
            obj = records[i]
            lines.append(f"    - index {i}: file={obj.get('file')!r}, title={obj.get('title')!r}")
    return "\n".join(lines)

def _verify_existing_ids(records: List[Dict[str, Any]], namespace: Optional[str],
                         norm: str, do_casefold: bool, do_strip: bool, nbytes: int) -> List[str]:
    """
    對「已有非 null id」的記錄，計算本次參數下的期望 id（k=0），
    若不同則回傳警告訊息。
    """
    notes: List[str] = []
    for i, obj in enumerate(records):
        if not isinstance(obj, dict):
            continue
        if obj.get("id") is None:
            continue
        fname = obj.get("file")
        if not isinstance(fname, str) or not fname:
            continue
        expected = ufid(fname, namespace, 0, norm, do_casefold, do_strip, nbytes)
        if str(obj["id"]) != expected:
            notes.append(f"Index {i} has existing id={obj['id']} but expected={expected} for file={fname!r}")
    return notes

# ---------- Assignment strategies ----------

def assign_ids_strict(records: List[Dict[str, Any]], namespace: Optional[str],
                      force: bool, norm: str, do_casefold: bool, do_strip: bool,
                      verify_mode: str, nbytes: int) -> int:
    changed = 0
    # 1) 填/重算 id
    for obj in records:
        if not isinstance(obj, dict):
            continue
        if not force and ("id" in obj and obj["id"] is not None):
            continue
        fname = obj.get("file")
        if not isinstance(fname, str) or not fname:
            continue
        obj["id"] = ufid(fname, namespace, 0, norm, do_casefold, do_strip, nbytes)
        changed += 1

    # 2) 檢查碰撞（含既有與新算）
    dup = _find_duplicates(records)
    if dup:
        msg = _report_duplicates(records, dup)
        raise SystemExit(msg)

    # 3) 驗證一致性
    if verify_mode != "off":
        notes = _verify_existing_ids(records, namespace, norm, do_casefold, do_strip, nbytes)
        if notes:
            text = "Existing ID mismatches detected:\n" + "\n".join("  - " + n for n in notes)
            if verify_mode == "fail":
                raise SystemExit(text + "\nHint: use --force (or --auto-resolve --force) to recompute ids.")
            else:
                sys.stderr.write(text + "\n")
    return changed

def assign_ids_auto_resolve(records: List[Dict[str, Any]], namespace: Optional[str],
                            force: bool, norm: str, do_casefold: bool, do_strip: bool,
                            nbytes: int) -> int:
    """
    自動解碰：
      - force=False：保留既有非 null id，對缺少的以 k=0,1,2… 找唯一值
      - force=True：全部（含既有）以 k=0,1,2… 重新分配，確保全域唯一且與本次參數一致
    """
    changed = 0
    used = set()
    if not force:
        for obj in records:
            if isinstance(obj, dict) and obj.get("id") is not None:
                used.add(str(obj["id"]))

    def need_assign(o: Dict[str, Any]) -> bool:
        if not isinstance(o, dict):
            return False
        if force:
            return True
        return (("id" not in o) or (o.get("id") is None))

    pending = [o for o in records if need_assign(o) and isinstance(o.get("file"), str) and o.get("file")]
    pending.sort(key=lambda o: transform_name(o["file"], norm, do_casefold, do_strip))  # 決定性順序

    for obj in pending:
        fname = obj["file"]
        k = 0
        while True:
            cand = ufid(fname, namespace, k, norm, do_casefold, do_strip, nbytes)
            if cand not in used:
                old = obj.get("id")
                if old != cand:
                    obj["id"] = cand
                    changed += 1
                used.add(cand)
                break
            k += 1

    dup = _find_duplicates(records)
    if dup:
        msg = _report_duplicates(records, dup)
        raise SystemExit("Unexpected duplicates after auto-resolve:\n" + msg)
    return changed

# ---------- I/O & CLI ----------

HELP_EPILOG = r"""
Examples:
  # 1) 嚴格模式（預設；NFKC + casefold + strip；ID=4 bytes），輸出到 stdout
  ufid.py meta.json

  # 2) 嚴格模式 + 命名空間（建議）+ 8 bytes + 就地覆寫
  ufid.py meta.json --namespace "my_project" --bytes 8 --inplace

  # 3) 自動解碰（只補缺少 id，不動既有 id），仍用 4 bytes
  ufid.py meta.json --auto-resolve --namespace "my_project"

  # 4) 自動解碰 + 全部重算 + 16 bytes（修掉既有重複或不一致）
  ufid.py meta.json --auto-resolve --force --bytes 16 --namespace "my_project"

Notes:
  - 產生的 ID 為 nbytes（4/8/16） bytes 的 BLAKE2b 輸出，Base64url（無 '='）。
    對應字串長度約：4B→6、8B→11、16B→22。
  - 32-bit（4 bytes）碰撞風險高：~1 萬筆約 1% 機率；5 萬筆已相當高。
    在意碰撞請改用 --bytes 8 或 --bytes 16。
  - 嚴格模式：任何碰撞都會中止（不寫出）。
  - 預設會驗證既有 id 與本次參數是否一致；可用 --fail-on-mismatch 中止，或 --no-verify-existing 關閉。
"""

def main():
    ap = argparse.ArgumentParser(
        description="Add deterministic UFID from 'file' into each JSON record as 'id' (4/8/16 bytes).",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=HELP_EPILOG
    )
    ap.add_argument("input", help="Input JSON path (array of records)")
    ap.add_argument("-o", "--output", help="Output path (default: stdout)")
    ap.add_argument("--namespace", help="Optional namespace for domain separation (recommended)")
    ap.add_argument("--inplace", action="store_true", help="Write back to input file in place")
    ap.add_argument("--force", action="store_true", help="Overwrite existing non-null 'id' values")
    ap.add_argument("--auto-resolve", action="store_true",
                    help="Enable collision auto-resolution (Plan B). Default is strict mode (Plan A).")

    # ID 長度（bytes）
    ap.add_argument("--bytes", dest="nbytes", type=int, choices=[4,8,16], default=4,
                    help="ID length in bytes (default: 4). Use 8 or 16 to reduce collisions.")

    # 正規化相關（預設 NFKC + casefold + strip）
    ap.add_argument("--normalize", choices=["nfc","nfd","nfkc","nfkd","none"], default="nfkc",
                    help="Unicode normalization (default: nfkc)")
    ap.add_argument("--casefold", dest="casefold", action="store_true", default=True,
                    help="Enable case folding (default: on)")
    ap.add_argument("--no-casefold", dest="casefold", action="store_false",
                    help="Disable case folding")
    ap.add_argument("--strip", dest="strip", action="store_true", default=True,
                    help="Strip leading/trailing whitespace (default: on)")
    ap.add_argument("--no-strip", dest="strip", action="store_false",
                    help="Disable strip")

    # 既有 id 一致性驗證
    ap.add_argument("--verify-existing", dest="verify_mode", action="store_const", const="warn",
                    help="Verify existing non-null ids match current parameters (warn on mismatch)")
    ap.add_argument("--fail-on-mismatch", dest="verify_mode", action="store_const", const="fail",
                    help="Same as --verify-existing but fail on mismatch")
    ap.add_argument("--no-verify-existing", dest="verify_mode", action="store_const", const="off",
                    help="Do not verify existing ids against current parameters")
    ap.set_defaults(verify_mode="warn")  # 預設：警告但不中止

    ap.add_argument("--version", "-V", action="version", version="UFID v1")

    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("Top-level JSON must be an array of objects.")

    if args.auto_resolve:
        changed = assign_ids_auto_resolve(
            data, args.namespace, args.force, args.normalize, args.casefold, args.strip, args.nbytes
        )
    else:
        changed = assign_ids_strict(
            data, args.namespace, args.force, args.normalize, args.casefold, args.strip, args.verify_mode, args.nbytes
        )

    out_path = args.input if (args.inplace and not args.output) else args.output
    out_json = json.dumps(data, ensure_ascii=False, indent=2)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out_json + "\n")
    else:
        sys.stdout.write(out_json + "\n")

    sys.stderr.write(
        f"IDs added/updated: {changed}\n"
        f"Mode: {'AUTO-RESOLVE' if args.auto_resolve else 'STRICT'}; "
        f"{'FORCE' if args.force else 'NO-FORCE'}; "
        f"Namespace: {args.namespace or '(none)'}; "
        f"Bytes: {args.nbytes}; "
        f"Normalize: {args.normalize}; "
        f"Casefold: {args.casefold}; Strip: {args.strip}; "
        f"Verify: {args.verify_mode}\n"
    )

if __name__ == "__main__":
    main()
