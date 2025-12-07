# Python 腳本與資料管理指南

本文件詳細說明 `/python-scripts`、`/config` 和 `/misc` 目錄的內容，以及音效處理腳本的使用方式。

## 目錄

- [目錄結構](#目錄結構)
- [Python 腳本詳解](#python-腳本詳解)
- [完整工作流程](#完整工作流程)
- [配置檔案說明](#配置檔案說明)
- [雜項檔案](#雜項檔案)

---

## 目錄結構

```
soundboard/
├── python-scripts/           # Python 處理腳本
│   ├── 轉檔v3.py             # 音訊轉檔與音量標準化
│   ├── JSON生成v3.py         # 從檔名生成 JSON 索引
│   ├── 檔名清理.py           # 批次清理與規範化檔名
│   ├── ufid64.py             # 生成唯一識別碼
│   ├── 流程_清理_轉檔_JSON.bat  # Windows 批次腳本（整合流程）
│   └── JSON編碼UUID.bat      # Windows 批次腳本（JSON + ID）
├── config/                   # 配置與資料檔案
│   ├── sounds.json           # 音效清單（主要資料）
│   ├── sounds-old.json       # 舊版備份
│   ├── tags.json             # 標籤定義
│   ├── vote-results.json     # 票選結果
│   └── 新增資料夾/           # 備份與測試檔案
└── misc/                     # 雜項檔案
    └── 第一屆音效板票選結果.csv  # 原始票選資料
```

---

## Python 腳本詳解

### 1. 檔名清理.py

**目的**：批次規範化音效檔案的檔名，確保符合命名規則。

#### 功能

1. 將底線 `_` 改為連字號 `-`
2. 移除連字號左右的空白（`a - b.mp3` → `a-b.mp3`）
3. 移除副檔名前的多餘連字號（`foo-.mp3` → `foo.mp3`）
4. 合併連續方括弧標籤（`[A][B][C]` → `[A,B,C]`）
5. 清理方括弧內外的空白（`[ A ]` → `[A]`）
6. 統一全形/半形標點符號

#### 使用方式

```bash
# 基本用法：清理腳本所在目錄
python 檔名清理.py

# 指定輸入目錄
python 檔名清理.py -i /path/to/sounds/

# 包含隱藏檔案
python 檔名清理.py -i sounds/ --include-hidden
```

#### 參數說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `-i, --input` | 輸入資料夾路徑 | 腳本所在目錄 |
| `--include-hidden` | 處理隱藏檔案（`.` 開頭） | 否 |

#### 範例

**執行前：**
```
萬_最棒的音效版.mp3
貓_豹_合作 [ 笑 ] [ 迷因 ].mp3
瓦 - 開燈啊-.mp3
```

**執行後：**
```
萬-最棒的音效版.mp3
貓-豹-合作[笑,迷因].mp3
瓦-開燈啊.mp3
```

#### 注意事項

- **就地更名**：直接修改檔名，無法復原
- **目標衝突檢查**：若目標檔名已存在，會跳過該檔案
- **建議先備份**：處理前建議備份重要檔案

---

### 2. 轉檔v3.py

**目的**：批次轉換音訊檔案為標準化 MP3，並進行音量標準化（EBU R128 loudnorm）。

#### 功能

1. **格式轉換**：支援 `.mp4`, `.mp3`, `.m4a`, `.wav`, `.flac` 轉為 MP3
2. **音量標準化**：使用 FFmpeg loudnorm 濾鏡（EBU R128 標準）
   - 目標響度：-14 LUFS
   - 真峰值：-1.5 dBTP
   - 動態範圍：11 LRA
3. **兩段式 + 後備方案**：
   - 預設：分析 → 套用（精確）
   - 失敗時：單段式 loudnorm（後備）
4. **智慧編碼策略**：
   - MP3 檔案若取樣率已符合目標，保持原位元率
   - 其他情況使用 VBR V4 編碼
5. **並行處理**：多核心加速（可設定工作數）

#### 使用方式

```bash
# 基本用法：轉換當前目錄所有音訊檔案
python 轉檔v3.py -o 已轉換/

# 指定輸入與輸出目錄
python 轉檔v3.py -i raw-audio/ -o converted/

# 遞迴處理子目錄
python 轉檔v3.py -i sounds/ -o output/ --recursive

# 保留立體聲（預設為單聲道）
python 轉檔v3.py -i sounds/ -o output/ --stereo

# 強制覆寫已存在檔案
python 轉檔v3.py -i sounds/ -o output/ --force

# 乾跑模式（僅顯示指令，不執行）
python 轉檔v3.py -i sounds/ -o output/ --dry-run

# 自訂音量標準化參數
python 轉檔v3.py -i sounds/ -o output/ --I -16 --TP -2.0 --LRA 7.0

# 指定並行工作數
python 轉檔v3.py -i sounds/ -o output/ --workers 4
```

#### 參數說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `-i, --input` | 輸入資料夾 | 當前目錄 |
| `-o, --output` | 輸出資料夾（必填） | - |
| `--recursive` | 遞迴處理子目錄 | 否 |
| `--stereo` | 保留原聲道數 | 否（單聲道） |
| `--force` | 強制覆寫已存在檔案 | 否 |
| `--dry-run` | 僅顯示指令，不執行 | 否 |
| `--sample-rate` | 目標取樣率（Hz） | 32000 |
| `--workers` | 並行工作數（0=自動） | 0 |
| `--I` | loudnorm 目標響度（LUFS） | -14.0 |
| `--TP` | loudnorm 真峰值（dBTP） | -1.5 |
| `--LRA` | loudnorm 動態範圍 | 11.0 |

#### 技術細節

**兩段式 loudnorm 流程：**

```bash
# Pass 1: 分析
ffmpeg -i input.mp3 -af "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json" -f null -

# Pass 2: 套用（帶入分析結果）
ffmpeg -i input.mp3 \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=-16.2:measured_TP=-2.1:..." \
  -c:a libmp3lame -q:a 4 -ar 32000 -ac 1 output.mp3
```

**後備方案（單段式）：**

當兩段式失敗時（如檔案損壞、音訊異常），自動改用單段式：

```bash
ffmpeg -i input.mp3 \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11" \
  -c:a libmp3lame -q:a 4 -ar 32000 -ac 1 output.mp3
```

#### 依賴需求

- **FFmpeg**：必須安裝並在 PATH 中
- **FFprobe**：通常隨 FFmpeg 一起安裝
- **Python 套件**：`tqdm`（進度條）

安裝依賴：

```bash
pip install tqdm
```

#### 效能建議

- **並行工作數**：建議設為 CPU 核心數的 50-75%（`--workers 4` / `--workers 6`）
- **記憶體消耗**：每個工作約需 100-200 MB
- **處理速度**：單檔約 1-3 秒（取決於長度與 CPU）

---

### 3. JSON生成v3.py

**目的**：掃描音效檔案，從檔名解析標題與標籤，生成標準 JSON 索引。

#### 功能

1. **遞迴掃描**：遞迴搜尋目錄下所有 `.mp3` 檔案
2. **檔名解析**：
   - 格式：`<主播1>-<主播2>-<標題>[<標籤1>,<標籤2>]`
   - 支援主播縮寫自動轉換（萬 → 阿萬、狗 → Matsuko 等）
   - 支援類型分類標籤（方括弧內）
3. **路徑保留**：輸出相對路徑（相對於輸入根目錄）
4. **標準 JSON 格式**：產出符合網站需求的 JSON 陣列

#### 使用方式

```bash
# 基本用法：掃描當前目錄，輸出到 mp3_index.json
python JSON生成v3.py

# 指定輸入與輸出
python JSON生成v3.py -i sounds/ -o config/sounds.json

# 輸出到標準輸出（stdout）
python JSON生成v3.py -i sounds/ -o stdout

# 或使用 "-"
python JSON生成v3.py -i sounds/ -o -
```

#### 參數說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `-i, --input` | 輸入根目錄 | `.`（當前目錄） |
| `-o, --output` | 輸出檔案路徑 | `mp3_index.json` |

#### 檔名解析規則

**主播縮寫對照：**

| 縮寫 | 完整名稱 |
|------|----------|
| 萬 | 阿萬 |
| 狗 | Matsuko |
| 貓 | 貓下去 |
| 豹 | 豹子頭 |
| 瓦 | 瓦哈 |
| 雞 | 花雕雞 |
| 鼠 | 鼠ki雅 |
| 鈴鼠 | 馬鈴鼠 |

**解析範例：**

| 檔名 | 解析結果 |
|------|----------|
| `萬-最棒的音效版.mp3` | title: "最棒的音效版"<br>tags: ["阿萬"] |
| `萬-豹-合作片段[笑,迷因].mp3` | title: "合作片段"<br>tags: ["阿萬", "豹子頭", "笑", "迷因"] |
| `貓-狗-對話[SUS].mp3` | title: "對話"<br>tags: ["貓下去", "Matsuko", "SUS"] |

**支援的分隔符：**

- 連字號：`-`, `－`, `‐`, `–`, `—`, `―`（全形/半形/各種變體）
- 標籤分隔：`,`, `，`, `、`（逗號、頓號）
- 標籤括弧：`[]`, `〔〕`（半形/全形）

#### 輸出格式

```json
[
  {
    "file": "萬-最棒的音效版.mp3",
    "title": "最棒的音效版",
    "tags": ["阿萬"]
  }
]
```

#### 注意事項

- **不含 `id` 欄位**：需要執行 `ufid64.py` 生成唯一 ID
- **標籤去重**：同一標籤只會出現一次
- **順序保持**：主播標籤在前，類型標籤在後

---

### 4. ufid64.py

**目的**：為 JSON 記錄生成唯一、決定性的識別碼（Unique File ID）。

#### 功能

1. **決定性 ID**：相同 `file` 欄位永遠產生相同 ID
2. **可配置長度**：支援 4/8/16 bytes（對應約 6/11/22 字元）
3. **碰撞處理**：
   - 嚴格模式：檢測碰撞並中止
   - 自動解碰模式：自動調整參數直到唯一
4. **版本驗證**：檢查既有 ID 是否與本次參數一致
5. **命名空間支援**：隔離不同專案的 ID 空間

#### 使用方式

```bash
# 基本用法：為 sounds.json 生成 ID（輸出到 stdout）
python ufid64.py config/sounds.json

# 就地覆寫原檔案
python ufid64.py config/sounds.json --inplace

# 指定命名空間與 ID 長度（推薦）
python ufid64.py config/sounds.json \
  --namespace "soundboard" \
  --bytes 4 \
  --inplace

# 自動解碰模式（處理碰撞）
python ufid64.py config/sounds.json \
  --auto-resolve \
  --namespace "soundboard" \
  --bytes 8 \
  --inplace

# 全部重新生成（修正既有 ID）
python ufid64.py config/sounds.json \
  --auto-resolve \
  --force \
  --namespace "soundboard" \
  --bytes 4 \
  --inplace

# 輸出到指定檔案
python ufid64.py config/sounds.json \
  -o config/sounds-with-id.json \
  --namespace "soundboard"
```

#### 參數說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `input` | 輸入 JSON 檔案（位置參數） | - |
| `-o, --output` | 輸出檔案路徑 | stdout |
| `--inplace` | 就地覆寫輸入檔案 | 否 |
| `--namespace` | 命名空間（推薦使用） | 無 |
| `--bytes` | ID 長度（4/8/16） | 4 |
| `--force` | 強制重新生成所有 ID | 否 |
| `--auto-resolve` | 自動解碰模式 | 否（嚴格模式） |
| `--normalize` | Unicode 正規化方式 | `nfkc` |
| `--no-casefold` | 停用大小寫折疊 | 啟用 |
| `--no-strip` | 停用前後空白去除 | 啟用 |
| `--fail-on-mismatch` | 既有 ID 不符時中止 | 警告 |
| `--no-verify-existing` | 不驗證既有 ID | 驗證 |

#### 技術細節

**ID 生成演算法：**

```
transform(filename) = normalize(filename) with NFKC + casefold + strip
payload = "ufid:v1:{namespace}:{transformed}:{k}"
salt = SHA256(namespace)[:16]  # if namespace provided
hash = BLAKE2b(payload, digest_size=nbytes, person='UFIDv1', salt=salt)
id = Base64url(hash) without padding
```

**碰撞機率（Birthday Paradox）：**

| ID 長度 | 熵（bits） | 50% 碰撞機率於 | 適用範圍 |
|---------|-----------|--------------|----------|
| 4 bytes | 32 | ~77k 項目 | 小型專案（< 5k） |
| 8 bytes | 64 | ~5 billion | 中型專案（< 1M） |
| 16 bytes | 128 | ~1.8×10^19 | 任意規模 |

**建議：**
- **< 5000 音效**：4 bytes 可接受
- **5k - 50k**：使用 8 bytes
- **> 50k 或嚴格需求**：使用 16 bytes

#### 模式說明

**嚴格模式（預設）：**

1. 補齊缺少的 ID（`id` 為 null 或不存在）
2. 檢查碰撞（任何重複立即中止）
3. 驗證既有 ID 與本次參數一致性（警告）

**自動解碰模式（`--auto-resolve`）：**

1. 保留既有 ID（除非 `--force`）
2. 對缺少 ID 的記錄，嘗試 k=0,1,2,... 直到唯一
3. 若 `--force`：全部重新生成，確保一致性

#### 範例場景

**場景 1：首次生成 ID**

```bash
python ufid64.py config/sounds.json \
  --namespace "soundboard" \
  --bytes 4 \
  --inplace
```

結果：所有記錄新增 `id` 欄位。

**場景 2：新增音效後補充 ID**

```bash
# 只為缺少 ID 的記錄生成（不動既有）
python ufid64.py config/sounds.json --inplace --namespace "soundboard"
```

**場景 3：發現碰撞，自動修復**

```bash
python ufid64.py config/sounds.json \
  --auto-resolve \
  --namespace "soundboard" \
  --inplace
```

**場景 4：升級 ID 長度（4 → 8 bytes）**

```bash
python ufid64.py config/sounds.json \
  --auto-resolve \
  --force \
  --bytes 8 \
  --namespace "soundboard" \
  --inplace
```

---

### 5. 批次腳本（Windows）

#### 流程_清理_轉檔_JSON.bat

整合完整流程的 Windows 批次腳本。

**執行步驟：**

1. 檔名清理
2. 音訊轉檔
3. 生成 JSON 索引

#### JSON編碼UUID.bat

僅執行 JSON 生成與 ID 生成。

---

## 完整工作流程

### 標準流程（從原始音訊到部署）

```bash
# 前置：確保已安裝 Python 與 FFmpeg
pip install tqdm

# === Step 1: 檔名規範化 ===
cd python-scripts
python 檔名清理.py -i ../sounds/

# === Step 2: 音訊轉檔與標準化 ===
python 轉檔v3.py \
  -i ../sounds/ \
  -o ../sounds/已轉換/ \
  --recursive \
  --workers 4

# === Step 3: 替換原檔案（可選） ===
# 將已轉換目錄的檔案移回 sounds/
# 或直接在 sounds/ 目錄執行轉檔（需要額外磁碟空間）

# === Step 4: 生成 JSON 索引 ===
python JSON生成v3.py \
  -i ../sounds/ \
  -o ../config/sounds.json

# === Step 5: 生成唯一 ID ===
python ufid64.py ../config/sounds.json \
  --namespace "soundboard" \
  --bytes 4 \
  --inplace

# === Step 6: 驗證 JSON 格式 ===
# 使用線上 JSON 驗證工具或：
python -m json.tool ../config/sounds.json > /dev/null && echo "JSON 格式正確"

# === Step 7: 部署 ===
# 上傳 sounds/ 和 config/sounds.json 到伺服器
```

### 增量更新流程（新增音效）

```bash
# 1. 將新音效放入 sounds/new/ 目錄

# 2. 清理檔名
python 檔名清理.py -i ../sounds/new/

# 3. 轉檔
python 轉檔v3.py -i ../sounds/new/ -o ../sounds/

# 4. 重新生成 JSON（掃描整個 sounds/ 目錄）
python JSON生成v3.py -i ../sounds/ -o ../config/sounds.json

# 5. 補充新音效的 ID（不動既有 ID）
python ufid64.py ../config/sounds.json \
  --namespace "soundboard" \
  --inplace
```

### 修復既有問題流程

**問題：發現 ID 碰撞**

```bash
python ufid64.py config/sounds.json \
  --auto-resolve \
  --namespace "soundboard" \
  --inplace
```

**問題：音量不一致**

```bash
# 重新轉檔所有音效（慎用）
python 轉檔v3.py -i sounds/ -o sounds-remastered/ --force
```

**問題：標籤錯誤**

1. 修正檔名（重新命名或使用檔名清理腳本）
2. 重新生成 JSON
3. 若 `file` 欄位改變，需重新生成 ID（`--force`）

---

## 配置檔案說明

### config/sounds.json

**結構：** JSON 陣列，每個元素為一個音效記錄。

**必要欄位：**

```json
{
  "file": "萬-最棒的音效版.mp3",
  "title": "最棒的音效版",
  "tags": ["阿萬"],
  "id": "Fz95EA"
}
```

| 欄位 | 類型 | 說明 | 生成方式 |
|------|------|------|----------|
| `file` | string | 音效檔案路徑（相對於 sounds/） | JSON生成v3.py |
| `title` | string | 顯示標題 | JSON生成v3.py |
| `tags` | string[] | 標籤陣列 | JSON生成v3.py |
| `id` | string | 唯一識別碼 | ufid64.py |

**維護注意事項：**

- **不可手動編輯 `id`**：ID 由 `file` 欄位決定性生成，手動修改會導致不一致
- **可手動編輯 `title` 和 `tags`**：調整顯示標題或標籤分類
- **若修改 `file`**：需重新執行 `ufid64.py --force` 更新 ID

### config/tags.json

**結構：** JSON 陣列，定義所有標籤的顯示樣式。

**範例：**

```json
[
  {
    "key": "阿萬",
    "name": "阿萬",
    "color": "#f59e0b",
    "role": "streamer",
    "avatar": "avatars/drr1.png"
  },
  {
    "key": "笑",
    "name": "笑",
    "color": "#edb34e",
    "role": "category"
  }
]
```

| 欄位 | 類型 | 說明 | 必填 |
|------|------|------|------|
| `key` | string | 標籤鍵值（與 sounds.json 的 tags 對應） | 是 |
| `name` | string | 顯示名稱 | 是 |
| `color` | string | 標籤顏色（hex） | 是 |
| `role` | string | 角色類型（"streamer" / "category"） | 是 |
| `avatar` | string | 頭像路徑 | streamer 必填 |

**維護：** 手動編輯，新增主播或類型標籤時更新。

### config/vote-results.json

**結構：** 票選結果資料（可選）。

**範例：**

```json
[
  {
    "file": "萬-最棒的音效版.mp3",
    "votes": 150,
    "rank": 1
  }
]
```

---

## 雜項檔案

### misc/第一屆音效板票選結果.csv

**內容：** 社群票選活動的原始結果資料。

**格式：** CSV 檔案，包含音效檔名、票數等資訊。

**用途：**
- 生成 `config/vote-results.json`
- 歷史記錄保存

**處理方式：**

```python
# 範例：CSV 轉 JSON 腳本（未提供，需自行編寫）
import csv
import json

with open('misc/第一屆音效板票選結果.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    data = list(reader)

with open('config/vote-results.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
```

---

## 常見問題與除錯

### Q1: FFmpeg 找不到

**錯誤訊息：**
```
錯誤：找不到 ffmpeg，請先安裝並確認在 PATH 中。
```

**解決方法：**

1. 安裝 FFmpeg：
   - Windows: 下載 [FFmpeg](https://ffmpeg.org/download.html) 並加入 PATH
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt install ffmpeg`

2. 驗證安裝：
   ```bash
   ffmpeg -version
   ```

### Q2: 轉檔失敗（loudnorm 錯誤）

**錯誤訊息：**
```
[FAIL] output.mp3
兩段式 loudnorm 套用/轉檔失敗
```

**可能原因：**
- 音訊檔案損壞
- 音訊串流異常（無聲音、極低音量等）
- FFmpeg 版本過舊

**解決方法：**
- 腳本會自動嘗試後備方案（單段式 loudnorm）
- 若仍失敗，手動檢查該檔案：
  ```bash
  ffprobe -v error -show_entries stream=codec_name,channels,sample_rate input.mp3
  ```

### Q3: JSON 生成後無 ID

**原因：** 未執行 `ufid64.py`。

**解決：**
```bash
python ufid64.py config/sounds.json --inplace --namespace "soundboard"
```

### Q4: ID 碰撞錯誤

**錯誤訊息：**
```
Collision(s) detected:
  id=abc123 -> 2 records
```

**解決方法：**

使用自動解碰模式：

```bash
python ufid64.py config/sounds.json \
  --auto-resolve \
  --namespace "soundboard" \
  --inplace
```

或增加 ID 長度：

```bash
python ufid64.py config/sounds.json \
  --auto-resolve \
  --force \
  --bytes 8 \
  --namespace "soundboard" \
  --inplace
```

### Q5: 檔名包含特殊字元導致解析錯誤

**解決方法：**

1. 先執行檔名清理腳本
2. 手動檢查並修正不符合規範的檔名
3. 避免使用特殊符號（如 `|`, `?`, `*`, `<`, `>` 等）

---

## 最佳實踐

### 1. 命名規範

**檔名格式：**
```
<主播縮寫>-<標題>[<標籤1>,<標籤2>].mp3
```

**範例：**
- ✅ `萬-最棒的音效版.mp3`
- ✅ `狗-萬-GAYBAR[唱,迷因].mp3`
- ❌ `萬_最棒的音效版.mp3`（使用底線）
- ❌ `萬 - 最棒的音效版.mp3`（多餘空白）
- ❌ `最棒的音效版.mp3`（缺少主播）
- ❌ `萬-最棒的音效版-.mp3`（多餘的-dash）

### 2. 批次處理建議

**大量新增音效時：**

1. 分批處理（避免一次轉檔過多導致系統負載過高）
2. 驗證每批結果
3. 增量更新 JSON（而非全部重新生成）

**範例：**

```bash
# 處理第一批
python 轉檔v3.py -i batch1/ -o sounds/ --workers 4

# 驗證
ls sounds/ | wc -l

# 處理第二批
python 轉檔v3.py -i batch2/ -o sounds/ --workers 4

# 最後統一生成 JSON 與 ID
python JSON生成v3.py -i sounds/ -o config/sounds.json
python ufid64.py config/sounds.json --inplace --namespace "soundboard"
```

---

## 進階主題

### 自訂 loudnorm 參數

針對特定類型音效調整標準化參數：

```bash
# 較低響度（適合環境音、ASMR）
python 轉檔v3.py -i asmr/ -o output/ --I -18 --LRA 15

# 較高響度（適合音樂、唱歌）
python 轉檔v3.py -i music/ -o output/ --I -11 --TP -1.0 --LRA 7
```

---

更多技術細節請參閱 [architecture.md](architecture.md)。
