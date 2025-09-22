#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改進點：
1) 遞迴掃描當前資料夾及其子資料夾下的 .mp3 檔。
2) 支援多人縮寫 -> tag；遇到沒有縮寫表的名稱，也會直接把該名稱加入 tags（不跳過）。
3) 解析標題結尾的「類型分類」標籤：<主播1>-<主播2>-<標題>(<tag1>,<tag2>)
   - 兼容空白與全形括弧、全形標點（（ ）、，、、 等），例如：(唱, 笑)、（唱、笑）都能正確解析。
4) 產出標準 JSON 陣列到 mp3_index.json，並保留相對路徑於 "file" 欄位。
"""
import os
import json
import re
from typing import Iterable, List

# 縮寫 -> 完整 tag 的對照（可自行擴充）
ABBR_TO_TAG = {
    "貓": "貓下去",
    "狗": "Matsuko",
    "萬": "阿萬",
    "瓦": "瓦哈",
    "豹": "豹子頭",
    "喵": "喵惠妹",
    "雞": "花雕雞",
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
    ，、、 -> ,（都視為分隔符）
    並保留原文其他字元。
    """
    return (
        s.replace("〔", "[")
         .replace("〕", "]")
         .replace("，", ",")
         .replace("、", ",")
    )

def parse_title_and_extra_tags(last_part: str):
    """
    解析最後一段：<標題>(<tag1>,<tag2>)
    - 允許空白與全形符號（會先 normalize）
    - 回傳 (title_without_suffix, extra_tags_list)
    """
    normalized = normalize_fullwidth_punct(last_part)
    # 擷取尾端括弧
    m = re.search(r"\[([^)]*)\]\s*$", normalized)
    extra_tags = []
    title = normalized
    if m:
        inside = m.group(1)
        # 去掉括弧部分，剩餘即為標題
        title = normalized[:m.start()].rstrip()
        # 用逗號切並清理空白
        for t in inside.split(","):
            t = norm_text(t)
            if t:
                extra_tags.append(t)
    return title, extra_tags

def parts_before_title(filename_wo_ext: str):
    """
    將不含副檔名的檔名依各式連字號切分。
    規則：最後一段視為「標題(+可選括弧)」，之前皆為人名/縮寫。
    """
    parts = [norm_text(p) for p in HYPHEN_SPLIT_RE.split(filename_wo_ext) if norm_text(p)]
    if not parts:
        return [], ""
    # 修正：不要用星號解包去接 parts[:-1]，避免 names 變成「巢狀 list」
    names = parts[:-1]
    last = parts[-1]
    return names, last

def _flatten_names(names: Iterable) -> List[str]:
    """防呆：若接收到巢狀 list，攤平成一維字串列表。"""
    flat = []
    for n in names:
        if isinstance(n, (list, tuple)):
            for x in n:
                if isinstance(x, str):
                    flat.append(x)
        elif isinstance(n, str):
            flat.append(n)
    return flat

def tags_from_names(names):
    """
    依序處理名稱列表：
    - 若在縮寫表中，轉換為對應 tag。
    - 否則直接把名稱加入 tags（不跳過）。
    - 移除空字串並去重（維持出現順序）。
    """
    names = _flatten_names(names)  # 防呆：就算外部傳巢狀也能處理
    tags = []
    seen = set()
    for n in names:
        if not n:
            continue
        tag = ABBR_TO_TAG.get(n, n)  # 沒縮寫就直接用名稱
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags

def collect_mp3s(root="."):
    """遞迴蒐集所有 .mp3 檔，回傳相對路徑（相對於 root）。"""
    results = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".mp3"):
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                results.append(rel)
    results.sort()
    return results

def build_index(root="."):
    """
    建立索引陣列：
    {
      "file": "<相對路徑>",
      "title": "<標題（去除括弧）>",
      "tags": ["<tag1>", "<tag2>", ...]
    }
    """
    out = []
    for relpath in collect_mp3s(root):
        base = os.path.basename(relpath)
        name_wo_ext, _ = os.path.splitext(base)
        # 切分為「人名/縮寫 …」與「最後一段(標題+可選括弧)」
        names, last = parts_before_title(name_wo_ext)

        # 標題 + 類型分類標籤
        title, extra_tags = parse_title_and_extra_tags(last)

        tags = tags_from_names(names)

        # 合併類型分類標籤，維持順序並去重
        for t in extra_tags:
            if t and t not in tags:
                tags.append(t)

        out.append({
            "file": relpath.replace("\\", "/"),  # Windows 相容處理
            "title": title,
            "tags": tags,
        })
    return out

def main():
    data = build_index(".")
    with open("mp3_index.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
