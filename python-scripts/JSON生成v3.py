#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改進點（v3）：
1) 遞迴掃描輸入根目錄及其子資料夾下的 .mp3 檔（預設為當前資料夾 .）。
2) 支援多人縮寫 -> tag；遇到沒有縮寫表的名稱，也會直接把該名稱加入 tags（不跳過）。
3) 解析標題結尾的「類型分類」標籤：<主播1>-<主播2>-<標題>[<tag1>,<tag2>] 或 (<tag1>,<tag2>)
   - 兼容空白與全形括弧、全形標點（（ ）、〔 〕、，、 等），例如：[唱, 笑]、[唱、笑]、(唱, 笑) 都能正確解析。
4) 產出標準 JSON 陣列，保留相對於「輸入根目錄」的路徑於 "file" 欄位。
5) 新增 CLI 參數：-i/--input 指定輸入根目錄；-o/--output 指定輸出路徑（預設 mp3_index.json；設為 "-" 或 "stdout" 會輸出到標準輸出）。
"""
import os
import json
import re
import argparse
from typing import Iterable, List, Tuple

# 縮寫 -> 完整 tag 的對照（可自行擴充）
ABBR_TO_TAG = {
    "貓": "貓下去",
    "狗": "Matsuko",
    "萬": "阿萬",
    "瓦": "瓦哈",
    "豹": "豹子頭",
    "喵": "喵惠妹",
    "雞": "花雕雞",
    "鼠": "鼠ki雅",
    "鈴鼠": "馬鈴鼠"
}

# 允許的分隔符：半形 - 及常見全形／變體
HYPHEN_SPLIT_RE = re.compile(r"[-‐-‒–—―－]")

def norm_text(s: str) -> str:
    """一般化字串：去除前後空白。"""
    return s.strip()

def normalize_fullwidth_punct(s: str) -> str:
    """
    將全形括弧與標點一般化：
    〔、〕 -> [、]
    （、） -> (、)
    ，、（頓號） -> ,（都視為分隔符）
    並保留原文其他字元。
    """
    return (
        s.replace("〔", "[")
         .replace("〕", "]")
         #.replace("（", "(")
         #.replace("）", ")")
         .replace("，", ",")
         .replace("、", ",")
    )

def parse_title_and_extra_tags(last_part: str) -> Tuple[str, List[str]]:
    """
    解析最後一段：<標題>[<tag1>,<tag2>] 或 (<tag1>,<tag2>)
    - 允許空白與全形符號（會先 normalize）
    - 回傳 (title_without_suffix, extra_tags_list)
    """
    normalized = normalize_fullwidth_punct(last_part)
    m = re.search(r"\[([^\]]*)\]\s*$", normalized)
    #if not m:
    #    m = re.search(r"\(([^\)]*)\)\s*$", normalized)

    extra_tags: List[str] = []
    title = normalized
    if m:
        inside = m.group(1)
        # 去掉尾端括弧，剩餘即為標題
        title = normalized[:m.start()].rstrip()
        # 用逗號切並清理空白
        for t in inside.split(","):
            t = norm_text(t)
            if t:
                extra_tags.append(t)
    return title, extra_tags

def parts_before_title(filename_wo_ext: str) -> Tuple[List[str], str]:
    """
    將不含副檔名的檔名依各式連字號切分。
    規則：最後一段視為「標題(+可選括弧)」，之前皆為人名/縮寫。
    """
    parts = [norm_text(p) for p in HYPHEN_SPLIT_RE.split(filename_wo_ext) if norm_text(p)]
    if not parts:
        return [], ""
    names = parts[:-1]
    last = parts[-1]
    return names, last

def _flatten_names(names: Iterable) -> List[str]:
    """防呆：若接收到巢狀 list，攤平成一維字串列表。"""
    flat: List[str] = []
    for n in names:
        if isinstance(n, (list, tuple)):
            for x in n:
                if isinstance(x, str):
                    flat.append(x)
        elif isinstance(n, str):
            flat.append(n)
    return flat

def tags_from_names(names: Iterable[str]) -> List[str]:
    """
    依序處理名稱列表：
    - 若在縮寫表中，轉換為對應 tag。
    - 否則直接把名稱加入 tags（不跳過）。
    - 移除空字串並去重（維持出現順序）。
    """
    names = _flatten_names(names)  # 防呆：就算外部傳巢狀也能處理
    tags: List[str] = []
    seen = set()
    for n in names:
        if not n:
            continue
        tag = ABBR_TO_TAG.get(n, n)  # 沒縮寫就直接用名稱
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags

def collect_mp3s(root: str = ".") -> List[str]:
    """遞迴蒐集所有 .mp3 檔，回傳相對路徑（相對於 root）。"""
    results: List[str] = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".mp3"):
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                results.append(rel)
    results.sort()
    return results

def build_index(root: str = ".") -> List[dict]:
    """
    建立索引陣列：
    {
      "file": "<相對路徑>",
      "title": "<標題（去除尾端括弧）>",
      "tags": ["<tag1>", "<tag2>", ...]
    }
    """
    out: List[dict] = []
    for relpath in collect_mp3s(root):
        base = os.path.basename(relpath)
        name_wo_ext, _ = os.path.splitext(base)
        # 切分為「人名/縮寫 …」與「最後一段(標題+可選括弧)」
        names, last = parts_before_title(name_wo_ext)

        # 標題 + 類型分類標籤
        title, extra_tags = parse_title_and_extra_tags(last)

        tags = tags_from_names(names)

        # 合併類型分類標籤，維持出現順序並去重
        for t in extra_tags:
            if t and t not in tags:
                tags.append(t)

        out.append({
            "file": relpath.replace("\\", "/"),  # Windows 相容處理
            "title": title,
            "tags": tags,
        })
    return out

def write_output(data, output_path: str) -> None:
    """將結果寫入檔案或輸出到 stdout。"""
    if output_path in ("-", "stdout"):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    parent = os.path.dirname(os.path.abspath(output_path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="生成json_v3.py",
        description="掃描輸入根目錄中的 .mp3，解析檔名成標題與標籤，輸出標準 JSON 陣列。"
    )
    parser.add_argument(
        "-i", "--input", dest="input_root", default=".",
        help='輸入根目錄（預設 "."）'
    )
    parser.add_argument(
        "-o", "--output", dest="output_path", default="mp3_index.json",
        help='輸出檔路徑（預設 "mp3_index.json"；設為 "-" 或 "stdout" 會輸出到標準輸出）'
    )
    args = parser.parse_args(argv)

    data = build_index(args.input_root)
    write_output(data, args.output_path)

if __name__ == "__main__":
    main()
