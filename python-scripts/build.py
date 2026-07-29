#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
網站建置流程
=================================================
  1. gen_og.py --execute ── 產生每條音效的 Open Graph 分享頁（s/*.html）、
                            OG 縮圖，並更新 index-raw.html 的首頁 OG 區塊
  2. html-minifier-terser ── index-raw.html → index.html

任一步失敗即中止並回報，退出碼非 0，避免把半成品部署出去。

為什麼建置訊息寫在 Python 而不是 build.bat：
cmd.exe 是以「執行當下的主控台編碼」逐行解析批次檔的，該編碼會隨環境改變
（cp950／65001…），批次檔內只要有中文就可能被拆碎成語法錯誤。Python 在
Windows 主控台是走 Unicode API 輸出，任何編碼下都正確，因此 build.bat 只保留
純 ASCII 的呼叫，所有訊息由本檔負責。

用法：
  python python-scripts/build.py          # 完整建置
  python python-scripts/build.py --skip-og  # 只重新壓縮，不重跑 OG 產生
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
INDEX_RAW = ROOT / "index-raw.html"
INDEX_OUT = ROOT / "index.html"
MIN_OUTPUT_BYTES = 50_000  # 正常產出約 100KB，明顯過小視為異常

MINIFY_ARGS = [
    "index-raw.html",
    "--collapse-whitespace", "--remove-comments",
    "--minify-css", "true", "--minify-js", "true",
    "-o", "index.html",
]


def hr(title=""):
    print("=" * 46, flush=True)
    if title:
        print(f"  {title}")
        print("=" * 46, flush=True)


def fail(msg, detail=""):
    print()
    print(f"[失敗] {msg}")
    if detail:
        for line in detail.splitlines():
            print(f"        {line}")
    print()
    hr("建置失敗，請勿部署")
    sys.exit(1)


def run_step(no, total, title, cmd, cwd=ROOT):
    # 子行程直接寫主控台，父行程的輸出在重導向時會被緩衝；
    # 先 flush 才能保證訊息順序正確。
    print(f"[{no}/{total}] {title}", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=cwd)
    except FileNotFoundError as e:
        fail(f"找不到執行檔：{cmd[0]}", str(e))
    if proc.returncode != 0:
        fail(f"{title} 執行失敗（錯誤碼 {proc.returncode}）。",
             "index.html 未更新或可能不完整。")
    return proc


def find_npx():
    for name in ("npx.cmd", "npx"):
        p = shutil.which(name)
        if p:
            return p
    fail("找不到 npx。", "請確認已安裝 Node.js 並在 PATH 中。")


def main():
    ap = argparse.ArgumentParser(description="建置網站（OG 分享頁 + 壓縮 index.html）")
    ap.add_argument("--skip-og", action="store_true",
                    help="略過 OG 分享頁產生，只重新壓縮 index.html")
    ap.add_argument("--og-mode", choices=["changed", "force", "skip"], default=None,
                    help="分享頁建置模式；不指定則由 gen_og.py 互動詢問")
    args = ap.parse_args()

    hr("阿萬與動物朋友按鈕 - 建置")
    print()

    total = 1 if args.skip_og else 2
    step = 0

    if not args.skip_og:
        step += 1
        og_cmd = [sys.executable, str(SCRIPT_DIR / "gen_og.py"), "--execute"]
        if args.og_mode:
            og_cmd += ["--mode", args.og_mode]
        run_step(step, total, "產生 Open Graph 分享頁（gen_og.py）", og_cmd)
        print("[OK] 分享頁與 OG 縮圖產生完成。")
        print()
    else:
        print("（已指定 --skip-og，略過 OG 分享頁產生）")
        print()

    if not INDEX_RAW.is_file():
        fail(f"找不到 {INDEX_RAW.name}。")

    step += 1
    before = INDEX_OUT.stat().st_size if INDEX_OUT.is_file() else None
    run_step(step, total, "壓縮 index-raw.html → index.html",
             [find_npx(), "html-minifier-terser", *MINIFY_ARGS])

    # 產出檢查：存在、非空、大小合理
    if not INDEX_OUT.is_file():
        fail("壓縮指令結束但沒有產生 index.html。")
    size = INDEX_OUT.stat().st_size
    if size < MIN_OUTPUT_BYTES:
        fail(f"index.html 只有 {size:,} bytes，明顯過小，判定為異常產出。",
             "請重新檢查 index-raw.html。")

    delta = "" if before is None else f"（前次 {before:,} bytes）"
    print(f"[OK] index.html 已產生：{size:,} bytes {delta}")
    print()
    hr("建置成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
