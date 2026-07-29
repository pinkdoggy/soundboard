#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Open Graph 分享預覽產生器
=========================================================
爬蟲（Facebook / Discord / LINE / X）不執行 JavaScript，靜態主機也無法依
查詢字串回傳不同 HTML，因此「每條音效有自己的分享預覽」必須在建置時
預先產生實體檔案。本腳本產生：

  1. assets/og/<頭貼檔名>.png ── 每位實況主一張 512×512 OG 縮圖
     （頭貼等比放大置中、去除透明度並填上網站背景色，
       避免部分平台把透明區域算成黑底）
  2. s/<id>.html ── 每條音效一個極小的預覽頁
       og:title       {音效標題}－阿萬與動物朋友按鈕
       og:description by {實況主標籤、…}\n標籤：{其他標籤、…}
       og:image       第一個實況主標籤對應的頭貼
     真人開啟時由 JS 立即轉址回 ../?sound=<id>；爬蟲不跑 JS，只會讀到 meta。
  3. 首頁 OG 區塊 ── 就地更新 index-raw.html 中 OG:BEGIN/OG:END 之間的內容
     （音效總數自動代入）

執行後若有變更 index-raw.html，記得重新執行 build.bat 產生 index.html。

用法：
  python gen_og.py            # dry-run，只報告會產生什麼
  python gen_og.py --execute  # 實際寫入
"""

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
VOICES_JSON = ROOT / "config" / "voices.json"
TAGS_JSON = ROOT / "config" / "tags.json"
INDEX_RAW = ROOT / "index-raw.html"
OUT_DIR = ROOT / "s"
OG_IMG_DIR = ROOT / "assets" / "og"
FAVICON = ROOT / "assets" / "favicon.png"

# OG 的 og:url / og:image 必須是絕對網址，換網域時只需改這一行
BASE_URL = "https://pinkdoggy.github.io/soundboard/"

SITE_NAME = "阿萬與動物朋友按鈕"
HOME_DESC = "由粉肝製作的非官方音效板網站，目前收藏了{n}條網路足跡，西西"
OG_SIZE = 512
AVATAR_RATIO = 0.75          # 頭貼在畫布中佔的比例
OG_BG = (0x14, 0x18, 0x21)   # 與網站 --card 一致
SEP = "、"

MARK_BEGIN = "<!-- OG:BEGIN 由 python-scripts/gen_og.py 產生，請勿手動編輯 -->"
MARK_END = "<!-- OG:END -->"


def esc(s: str) -> str:
    """HTML 屬性跳脫；換行以實體表示，避免屬性值被折行破壞。"""
    return html.escape(str(s), quote=True).replace("\n", "&#10;")


def load():
    voices = json.loads(VOICES_JSON.read_text(encoding="utf-8"))
    tags_def = json.loads(TAGS_JSON.read_text(encoding="utf-8"))
    streamers = {t["key"]: t for t in tags_def if t.get("role") == "streamer"}
    return voices, streamers


# --------------------------------------------------------------------------- #
#  1. OG 縮圖
# --------------------------------------------------------------------------- #
def build_images(streamers, execute, log):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("需要 Pillow：pip install Pillow")

    jobs = []
    for key, t in streamers.items():
        src = ROOT / t["avatar"]
        if not src.is_file():
            raise SystemExit(f"找不到頭貼：{src}（tags.json 的 {key}）")
        jobs.append((key, src, OG_IMG_DIR / (Path(t["avatar"]).stem + ".png")))
    jobs.append(("(首頁)", FAVICON, OG_IMG_DIR / "home.png"))

    if execute:
        OG_IMG_DIR.mkdir(parents=True, exist_ok=True)
    for key, src, dst in jobs:
        if not execute:
            log(f"  [圖] {key}: {src.relative_to(ROOT)} → {dst.relative_to(ROOT)} ({OG_SIZE}×{OG_SIZE})")
            continue
        im = Image.open(src).convert("RGBA")
        side = int(OG_SIZE * AVATAR_RATIO)
        # 等比縮放到目標框內
        scale = min(side / im.width, side / im.height)
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                       Image.LANCZOS)
        canvas = Image.new("RGB", (OG_SIZE, OG_SIZE), OG_BG)
        canvas.paste(im, ((OG_SIZE - im.width) // 2, (OG_SIZE - im.height) // 2), im)
        canvas.save(dst, "PNG", optimize=True)
    return jobs


# --------------------------------------------------------------------------- #
#  2. 每條音效的預覽頁
# --------------------------------------------------------------------------- #
PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_esc}</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{site}">
<meta property="og:locale" content="zh_TW">
<meta property="og:title" content="{title_esc}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="{size}">
<meta property="og:image:height" content="{size}">
<meta property="og:url" content="{page_url}">
<meta property="og:audio" content="{audio}">
<meta property="og:audio:type" content="{audio_type}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title_esc}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{img}">
<link rel="canonical" href="{app_url}">
<link rel="icon" href="../assets/favicon.png" type="image/png">
<script>location.replace("../?sound={id_js}");</script>
</head>
<body><noscript><a href="../?sound={id_attr}">前往「{plain_title}」</a></noscript></body>
</html>
"""


def describe(entry, streamers):
    """組出 og:description：by 實況主，必要時再加一行標籤。"""
    st = [t for t in entry["tags"] if t in streamers]
    other = [t for t in entry["tags"] if t not in streamers]
    lines = ["by " + SEP.join(st)] if st else []
    # 逾七成音效沒有非實況主標籤，空的「標籤：」會讓預覽看起來像壞掉，故省略
    if other:
        lines.append("標籤：" + SEP.join(other))
    return "\n".join(lines)


def render(entry, streamers):
    st = [t for t in entry["tags"] if t in streamers]
    avatar_stem = Path(streamers[st[0]]["avatar"]).stem if st else "home"
    full_title = f"{entry['title']}－{SITE_NAME}"
    sid = entry["id"]
    ext = Path(entry["file"]).suffix.lower()
    return PAGE.format(
        audio=esc(BASE_URL + "voices/" + quote(entry["file"])),
        audio_type="audio/mp4" if ext == ".m4a" else "audio/mpeg",
        title_esc=esc(full_title),
        plain_title=esc(entry["title"]),
        desc=esc(describe(entry, streamers)),
        site=esc(SITE_NAME),
        img=esc(f"{BASE_URL}assets/og/{avatar_stem}.png"),
        size=OG_SIZE,
        page_url=esc(f"{BASE_URL}s/{sid}.html"),
        app_url=esc(f"{BASE_URL}?sound={sid}"),
        id_attr=esc(sid),
        id_js=json.dumps(sid)[1:-1],  # 供 JS 字串安全使用
    )


def build_pages(voices, streamers, execute, log):
    if execute:
        # 整個重建，避免留下已刪除音效的舊頁面
        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
        OUT_DIR.mkdir(parents=True)
    total = 0
    for e in voices:
        content = render(e, streamers)
        if execute:
            (OUT_DIR / f"{e['id']}.html").write_text(content, encoding="utf-8")
        total += len(content.encode("utf-8"))
    return total


# --------------------------------------------------------------------------- #
#  3. 首頁 OG 區塊
# --------------------------------------------------------------------------- #
def home_block(n):
    desc = esc(HOME_DESC.format(n=n))
    return "\n".join([
        MARK_BEGIN,
        f'  <meta name="description" content="{desc}">',
        '  <meta property="og:type" content="website">',
        f'  <meta property="og:site_name" content="{esc(SITE_NAME)}">',
        '  <meta property="og:locale" content="zh_TW">',
        f'  <meta property="og:title" content="{esc(SITE_NAME)}">',
        f'  <meta property="og:description" content="{desc}">',
        f'  <meta property="og:image" content="{esc(BASE_URL)}assets/og/home.png">',
        f'  <meta property="og:image:width" content="{OG_SIZE}">',
        f'  <meta property="og:image:height" content="{OG_SIZE}">',
        f'  <meta property="og:url" content="{esc(BASE_URL)}">',
        '  <meta name="twitter:card" content="summary">',
        f'  <meta name="twitter:title" content="{esc(SITE_NAME)}">',
        f'  <meta name="twitter:description" content="{desc}">',
        f'  <meta name="twitter:image" content="{esc(BASE_URL)}assets/og/home.png">',
        "  " + MARK_END,
    ])


def update_index(n, execute, log):
    text = INDEX_RAW.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    block = home_block(n).replace("\n", nl)

    if MARK_BEGIN in text and MARK_END in text:
        a = text.index(MARK_BEGIN)
        b = text.index(MARK_END) + len(MARK_END)
        new = text[:a] + block.lstrip() + text[b:]
        action = "更新"
    else:
        anchor = f"<title>{SITE_NAME}</title>"
        if anchor not in text:
            raise SystemExit(f"index-raw.html 找不到錨點 {anchor!r}，無法插入 OG 區塊。")
        i = text.index(anchor) + len(anchor)
        new = text[:i] + nl + block + text[i:]
        action = "插入"

    changed = new != text
    if changed and execute:
        INDEX_RAW.write_text(new, encoding="utf-8", newline="")
    log(f"  [首頁] {action} OG 區塊（音效總數 {n}）" + ("" if changed else "：內容相同，無變更"))
    return changed


# --------------------------------------------------------------------------- #
def verify(voices, streamers, log):
    """重讀產出做獨立驗證。"""
    errors = []
    files = {p.stem for p in OUT_DIR.iterdir() if p.suffix == ".html"}
    ids = {e["id"] for e in voices}
    if files != ids:
        errors.append(f"s/ 與 voices.json 不符：僅檔案 {len(files-ids)}、僅JSON {len(ids-files)}")
    for t in streamers.values():
        p = OG_IMG_DIR / (Path(t["avatar"]).stem + ".png")
        if not p.is_file():
            errors.append(f"缺 OG 圖：{p.name}")
    if not (OG_IMG_DIR / "home.png").is_file():
        errors.append("缺 OG 圖：home.png")

    # 抽驗內容正確性
    import random
    random.seed(0)
    for e in random.sample(voices, min(60, len(voices))):
        txt = (OUT_DIR / f"{e['id']}.html").read_text(encoding="utf-8")
        if esc(f"{e['title']}－{SITE_NAME}") not in txt:
            errors.append(f"標題未出現：{e['id']}")
        if f'"../?sound={e["id"]}"' not in txt:
            errors.append(f"轉址目標錯誤：{e['id']}")
        st = [t for t in e["tags"] if t in streamers]
        stem = Path(streamers[st[0]]["avatar"]).stem
        if f"assets/og/{stem}.png" not in txt:
            errors.append(f"縮圖對應錯誤：{e['id']}")

    raw = INDEX_RAW.read_text(encoding="utf-8")
    if MARK_BEGIN not in raw or f"收藏了{len(voices)}條" not in raw:
        errors.append("index-raw.html 的首頁 OG 區塊不正確")

    if errors:
        for e in errors[:20]:
            log("[驗證失敗] " + e)
        raise SystemExit("驗證未通過。")
    log(f"[驗證] 通過：s/ {len(files)} 頁與 voices.json 完全對應；"
        f"OG 圖 {len(streamers)+1} 張齊全；抽驗 60 頁標題/轉址/縮圖皆正確。")


def main():
    ap = argparse.ArgumentParser(description="產生每條音效的 OG 分享預覽頁（預設 dry-run）")
    ap.add_argument("--execute", action="store_true", help="實際寫入檔案")
    args = ap.parse_args()
    log = print
    ex = args.execute

    voices, streamers = load()
    log(f"音效 {len(voices)} 條；實況主 {len(streamers)} 位；base = {BASE_URL}")
    log("=== 1. OG 縮圖 ===")
    build_images(streamers, ex, log)
    if ex:
        log(f"  已產生 {len(streamers)+1} 張 {OG_SIZE}×{OG_SIZE} PNG → assets/og/")
    log("=== 2. 音效預覽頁 ===")
    total = build_pages(voices, streamers, ex, log)
    log(f"  {'已產生' if ex else '將產生'} {len(voices)} 個檔案 → s/（合計約 {total/1e6:.1f} MB）")
    log("=== 3. 首頁 OG ===")
    changed = update_index(len(voices), ex, log)

    if not ex:
        log("\ndry-run 完成，未寫入任何檔案。加 --execute 正式執行。")
        return
    verify(voices, streamers, log)
    if changed:
        log("\n※ index-raw.html 已變更，請重新執行 build.bat 產生 index.html。")


if __name__ == "__main__":
    main()
