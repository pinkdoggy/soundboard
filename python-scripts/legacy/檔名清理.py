#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
批次整理腳本所在目錄的檔名（直接更名，無需確認）：

1) 將 "_" 改為 "-"
2) "-" 左右不保留空白（"a - b.txt" → "a-b.txt"）
3) 若 "-" 與副檔名相鄰（如 a-.mp3），移除該 "-"
4) 將連續方括弧片段 [A][B][C] → [A,B,C]，也解析全形［］
5) 清理方括弧內外空白（例如 " [ A ] " → "[A]"、"foo [A]" → "foo[A]"、"[A] bar" → "[A]bar"）

可選：
  --include-hidden  # 若也想處理以 . 開頭的隱藏檔
"""

import re
import argparse
from pathlib import Path

def normalize_brackets_whitespace(text: str) -> str:
    """
    1) 全形［］→ 半形[]
    2) 去除方括弧內部的前後空白：[  A  ] → [A]
    3) 去除方括弧外部緊貼的空白：' foo [A] bar ' → ' foo[A]bar '
    """
    # 全形 → 半形
    text = text.replace("［", "[").replace("］", "]")
    # 內部空白
    text = re.sub(r"\[\s*([^][]*?)\s*\]", lambda m: f"[{m.group(1).strip()}]", text)
    # 外部緊貼空白（左側 / 右側）
    text = re.sub(r"\s+\[", "[", text)
    text = re.sub(r"\]\s+", "]", text)
    return text

def combine_bracket_runs(text: str) -> str:
    """
    將兩個以上連續的 [片段] 合併成一個：[A][B][C] → [A,B,C]
    允許中間有空白。
    """
    pattern = re.compile(r'(?:\[\s*[^][]*?\s*\]\s*){2,}')

    def repl(m: re.Match) -> str:
        tokens = re.findall(r'\[\s*([^][]*?)\s*\]', m.group(0))
        tokens = [t.strip() for t in tokens if t.strip() != ""]
        return "[" + ",".join(tokens) + "]"

    return pattern.sub(repl, text)

def transform_filename(original_name: str) -> str:
    """
    依規則回傳新檔名（不觸碰實體檔案）
    只視最後一個 '.' 之後為副檔名。
    """
    dot_idx = original_name.rfind(".")
    if dot_idx > 0:
        base, ext = original_name[:dot_idx], original_name[dot_idx:]
    else:
        base, ext = original_name, ""

    # 先處理方括弧與其空白
    base = normalize_brackets_whitespace(base)

    # "_" → "-"
    base = base.replace("_", "-")

    # "-" 左右不保留空白
    base = re.sub(r"\s*-\s*", "-", base)

    # 合併連續方括弧片段
    base = combine_bracket_runs(base)

    # 若 base 尾巴為 "-"（例如 a-.ext）→ 去掉
    base = base.rstrip("-")

    # 重組
    new_name = base + ext

    # 防呆：將 "-."（緊貼副檔名點）變成 "."
    new_name = re.sub(r'-\.(?=[^.]+$)', '.', new_name)

    # 去除整體前後空白
    new_name = new_name.strip()

    return new_name

def main() -> None:
    parser = argparse.ArgumentParser(description="整理腳本目錄中的檔名（直接更名）。")
    parser.add_argument(
        "--include-hidden", action="store_true",
        help="包含隱藏檔（以 . 開頭）"
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    items = sorted(root.iterdir())

    changed = False
    for p in items:
        if not p.is_file():
            continue
        if not args.include_hidden and p.name.startswith("."):
            continue

        new_name = transform_filename(p.name)
        if new_name != p.name:
            dst = p.with_name(new_name)
            if dst.exists() and dst.resolve() != p.resolve():
                print(f"[跳過] 目標已存在：{dst.name}")
                continue
            try:
                p.rename(dst)
                print(f"[完成] {p.name} -> {dst.name}")
                changed = True
            except Exception as e:
                print(f"[失敗] {p.name} -> {dst.name}：{e}")

    if not changed:
        print("沒有需要更名的檔案。")

if __name__ == "__main__":
    main()
