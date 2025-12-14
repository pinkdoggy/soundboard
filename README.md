# 阿萬與動物朋友按鈕

此網站收錄臺灣 VTuber 厭世醫師阿萬與動物朋友們的精彩語音片段。


## 須知
這個網站係由粉絲粉肝們維護與製作，並非由官方運營。其內容皆是粉肝去脈絡化、斷章取義的剪輯，僅供娛樂。本站所有音效檔案，皆屬於原作者厭世醫師阿萬，使用時須遵守厭世醫師阿萬的二次創作條例進行。而本站的原始碼 index-raw.html 屬於粉肝創作，為 GNU GPLv3 授權的自由軟體。 

## 功能特色

- **搜尋與標籤**：快速找到想要的音效，有主播、類型等標籤
- **收藏與排序**：自訂收藏列表，拖曳編輯你的最愛音效排序
- **多軌混音編輯器**：可以把音效混音編排
- **記憶小遊戲**：不知道為什麼會有，覺得有趣就做了
- **本地化儲存**：使用 localStorage 儲存設定跟狀態

## 快速開始

### 本地運行

1. 克隆此專案：
```bash
git clone <repository-url>
cd soundboard
```

2. 使用任何 HTTP 伺服器運行（由於 CORS 限制，需要伺服器環境）：
```bash
# 使用 Python 3
python -3 -m http.server 8000

# 或使用 Node.js 的 http-server
npx http-server
```

3. 開啟瀏覽器訪問 `http://localhost:8000/`

## 專案結構

```
soundboard/
├── index.html                   # 主要網站檔案（部屬用）
├── index-raw.html               # 主要網站檔案（原始碼）
├── config/                      # 配置檔案
│   ├── sounds.json              # 音效清單與元數據
│   ├── tags.json                # 標籤定義（主播、類型）
│   └── vote-results.json        # 票選結果資料
├── sounds/                      # 音效檔案目錄（.mp3）
├── avatars/                     # 主播頭像圖片
├── assets/                      # 其他靜態資源
├── scripts/                     # 外部腳本庫
│   └── Sortable.min.js          # 拖曳排序庫
├── python-scripts/              # 音效處理與資料生成腳本
│   ├── 轉檔v3.py                # 音訊轉檔與標準化
│   ├── JSON生成v3.py            # 從檔名生成 JSON 索引
│   ├── 檔名清理.py              # 批次清理檔名
│   └── ufid64.py                # 生成唯一 ID
├── misc/                        # 雜項檔案
└── doc/                         # 技術文檔
```

## 音效資料管理

### 添加新音效

1. 將音效檔案放入 `sounds/` 目錄
2. 檔名格式：`<主播縮寫>-<標題>[<標籤>].mp3`
   - 例：`萬-最棒的音效版.mp3`
   - 例：`萬-豹-OOOO[笑,迷因].mp3`
3. 執行處理流程（見下方腳本使用）

### Python 腳本工作流程

詳見 [文檔目錄](doc/) 中的「腳本使用指南」，基本流程：

```bash
# 1. 清理檔名
python python-scripts/檔名清理.py -i sounds/

# 2. 轉檔並標準化音量
python python-scripts/轉檔v3.py -i sounds/ -o sounds/已轉換/

# 3. 生成 JSON 索引
python python-scripts/JSON生成v3.py -i sounds/ -o config/sounds.json

# 4. 生成唯一 ID
python python-scripts/ufid64.py config/sounds.json --inplace --namespace soundboard --bytes 4
```

## 架構說明

詳細程式架構說明請參閱 [doc/architecture.md](doc/architecture.md)

