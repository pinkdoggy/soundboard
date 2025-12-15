# 網站架構與技術文檔

本文件描述「阿萬與動物朋友按鈕」網站的技術架構、原碼結構與實作細節。

## 目錄

- [技術概覽](#技術概覽)
- [原碼結構](#原碼結構)
- [資料結構](#資料結構)
- [Local Storage 使用](#local-storage-使用)
- [核心模組](#核心模組)
  - [音頻播放核心](#5-音頻播放核心)
  - [[ADHOC] 三周年特殊機制：音效時間軸觸發動畫](#adhoc-三周年特殊機制音效時間軸觸發動畫)
- [樣式系統](#樣式系統)

---

## 技術概覽

### 使用技術

原生JS/HTML/CSS實作，使用 HTML5 Audio API 實現音軌混音器。
使用 Sortable.JS 提供拖曳排序功能（唯一外部依賴）。

### 架構特點

單檔應用、IIFE 模式、localStorage 儲存使用者設定、滾動載入、URL驅動。

### 授權

- **程式碼（index-raw.html）**：GNU GPLv3
- **音效內容**：版權歸原創作者所有

---

## 原碼結構

### 檔案組織

主要檔案：[index-raw.html](../index-raw.html)（約 4813 行）

```
index-raw.html
├── GPL 授權聲明
├── <head>
│   ├── Meta 標籤與設定
│   └── <style>：完整 CSS 樣式系統（~2000 行）
│       ├── CSS 變數定義（亮色/暗色主題）
│       ├── CSS Reset 與基礎樣式
│       ├── 版面配置（Header、搜尋列、卡片網格）
│       ├── 元件樣式（按鈕、標籤、Toast 通知）
│       ├── 最愛面板樣式
│       ├── 記憶遊戲樣式
│       └── demaPanel 混音編輯器樣式
├── <body>
│   ├── 背景圖層系統
│   ├── 頁首區域（標題與主播頭像動畫）
│   ├── 導覽列（首頁、遊戲、關於、票選）
│   ├── 搜尋列與標籤篩選
│   ├── 分頁容器
│   │   ├── 首頁：音效卡片網格 + 最愛列表
│   │   ├── 遊戲：記憶遊戲面板
│   │   ├── 關於：專案資訊
│   │   └── 票選：票選結果展示
│   ├── 設定面板（音量控制）
│   ├── demaPanel 混音編輯器
│   ├── 右鍵選單
│   └── Toast 通知容器
└── <script>
    ├── SortableJS 載入
    └── 主應用程式（IIFE，~2800 行）
        ├── 1. 常數與設定 (CONFIG, MESSAGES)
        ├── 2. 工具函式
        ├── 3. DOM 元素引用 (els)
        ├── 4. 應用程式狀態 (state)
        ├── 5. 音頻播放核心
        ├── 6. DOM 建構工具 (dom)
        ├── 7. 通用工具函式 (utils)
        ├── 8. 路由與 URL 管理
        ├── 9. UI 互動與事件處理
        ├── 10. UI 渲染函式
        ├── 11. 初始化流程
        ├── 12. 記憶小遊戲
        └── 13. demaPanel 多軌混音編輯器
```

### 模組說明

#### 1. 常數與設定

**CONFIG 物件**：集中管理所有可調整參數

```javascript
const CONFIG = {
  // 資料來源路徑
  paths: {
    tags: 'config/tags.json',
    sounds: 'config/sounds.json',
    voteResults: 'config/vote-results.json'
  },

  // localStorage 鍵名
  storage: {
    favorites: 'favorites',
    favoritesVersion: 'favorites_version',
    favoritesBackup: 'favorites_legacy_backup',
    theme: 'theme',
    globalVolume: 'globalVolume'
  },

  // UI 時間設定（毫秒）
  timing: {
    toastDuration: 2500,        // Toast 顯示時長
    longPressDelay: 650,        // 長按觸發選單延遲
    searchDebounce: 180,        // 搜尋防抖延遲
    animationDelay: 60,         // 頭像動畫延遲間隔
    hopOutDelay: 90             // 頭像離場動畫延遲
  },

  // UI 渲染設定
  ui: {
    batchSize: 72               // 每次渲染的卡片數量 (6欄 x 12列)
  },

  // 票選相關
  awards: {
    topRankCount: 30,           // 讀取前 N 名
    top10Count: 10,             // 顯示為前 10 名
    next20Count: 20             // 顯示為入圍獎
  },

  // 記憶遊戲相關
  game: {
    pairCount: 8,               // 配對數量
    cardFlipDelay: 500,         // 翻牌檢查延遲
    rewardAccuracy: 90,         // 觸發獎勵的準確率門檻
    rewardSoundIds: [...]       // 獎勵音效 ID 列表
  },

  // 預設顏色
  colors: {
    defaultTag: '#94a3b8'       // 預設標籤色
  }
}
```

**MESSAGES 物件**：集中管理 UI 訊息文字

```javascript
const MESSAGES = {
  toast: {
    linkCopied: '已複製分享連結',
    listLinkCopied: '已複製分享最愛列表連結',
    noFavorites: '沒有最愛可分享',
    sortingSaved: '已儲存最愛排序',
    sortingBlocked: '正在編輯最愛排序，無法變更最愛',
    favMigrated: (count, missing) => `已升級最愛格式，共 ${count} 筆...`,
    gameReward: '你是記憶猛肝'
  },
  errors: {
    configLoadFailed: '載入設定檔失敗...',
    gameNoSounds: '目前沒有足夠的音效可供配對...'
  },
  empty: {
    noFavorites: '還沒有最愛。點音效右上的 ❤️ 加入最愛。',
    noResults: '沒有符合搜尋的音效。'
  }
}
```

#### 2. 工具函式

```javascript
// 版本字串附加（用於緩存清除）
const withV = url => url + (url.includes('?') ? '&' : '?') + 'v=' + VERSION

// Fisher-Yates 洗牌演算法
function shuffleInPlace(arr, rng = Math.random) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
```

#### 3. DOM 元素引用 (els)

統一管理所有 DOM 元素引用：

```javascript
const els = {
  // 搜尋與篩選
  q: document.getElementById('q'),
  activeChips: document.getElementById('activeChips'),
  clearBtn: document.getElementById('clearBtn'),
  tagList: document.getElementById('tagList'),

  // 主要容器
  grid: document.getElementById('grid'),
  favGrid: document.getElementById('favGrid'),
  empty: document.getElementById('empty'),
  favEmpty: document.getElementById('favEmpty'),

  // 控制按鈕
  settingsBtn: document.getElementById('settingsBtn'),
  themeBtn: document.getElementById('themeBtn'),
  stage: document.getElementById('stage'),
  navToggle: document.getElementById('navToggle'),

  // 分頁元素
  pageHome: document.getElementById('page-home'),
  pageGame: document.getElementById('page-game'),
  pageAbout: document.getElementById('page-about'),
  pageawards: document.getElementById('page-awards'),

  // 設定面板
  settingsModal: document.getElementById('settingsModal'),
  settingsVolume: document.getElementById('settingsVolume'),
  settingsVolumeValue: document.getElementById('settingsVolumeValue'),

  // 票選頁面
  awardsTop10: document.getElementById('awards-top10'),
  awardsNext20: document.getElementById('awards-next20'),

  // 最愛管理
  sortFavBtn: document.getElementById('sortFavBtn'),
  doneSortBtn: document.getElementById('doneSortBtn'),
  shareFavBtn: document.getElementById('shareFavBtn'),
  shuffleBtn: document.getElementById('shuffleBtn'),
  resetOrderBtn: document.getElementById('resetOrderBtn'),

  // demaPanel 相關（混音編輯器）
  openDemaBtn: document.getElementById('openDemaBtn'),
  demaPanel: document.getElementById('demaPanel'),
  demaUndo: document.getElementById('demaUndo'),
  demaRedo: document.getElementById('demaRedo'),
  // ... 更多 demaPanel 元素

  // 動態查詢元素（使用 getter）
  get menu() { return document.getElementById('menu'); },
  get toast() { return document.getElementById('toast'); },
  get navTabs() { return document.querySelectorAll('.tab[data-page]'); }
}
```

#### 4. 應用程式狀態 (state)

集中式狀態管理：

```javascript
const state = {
  // 資料
  tags: {},                      // 標籤定義物件 { key: tagObj }
  tagList: [],                   // 所有標籤陣列
  usedTagList: [],               // 實際使用的標籤陣列
  sounds: [],                    // 所有音效陣列
  soundMap: new Map(),           // ID -> 音效物件映射
  defaultSoundsSnapshot: [],     // 預設排序快照

  // 最愛
  favorites: JSON.parse(localStorage.getItem(CONFIG.storage.favorites) || '[]'),
  favSet: new Set(),             // 最愛集合（快速查詢）
  isSorting: false,              // 是否正在排序最愛
  sortable: null,                // SortableJS 實例

  // 搜尋與篩選
  queryText: '',                 // 搜尋文字
  queryTags: new Set(),          // 選取的標籤集合

  // UI 狀態
  page: 'home',                  // 目前分頁
  contextTimer: null,            // 長按計時器
  toastTimer: null,              // Toast 計時器
  highlightedCardId: '',         // 高亮卡片 ID

  // 分享列表
  receivedList: [],              // 接收的分享列表

  // 記憶遊戲
  cgRunning: false,              // 遊戲是否進行中

  // 分批渲染
  displayList: [],               // 目前顯示的音效列表
  renderedCount: 0,              // 已渲染數量
  observer: null,                // IntersectionObserver 實例

  // 全域音量
  globalVolume: 1.0              // 0.0 - 1.0
}
```

初始化邏輯：

```javascript
// 初始化最愛集合
state.favSet = new Set(state.favorites)

// 從 localStorage 恢復全域音量
state.globalVolume = (() => {
  const v = localStorage.getItem(CONFIG.storage.globalVolume)
  const n = Number(v)
  return (v !== null && !isNaN(n) && n >= 0 && n <= 1) ? n : 1.0
})()
```

#### 5. 音頻播放核心

使用 HTML5 Audio API：

```javascript
// 套用全域音量到 Audio 元素
const applyVolumeToAudio = a => {
  try {
    a && (a.volume = state.globalVolume)
  } catch (e) {
    console.warn('[applyVolumeToAudio] 設定音量失敗', e)
  }
}

// 建立 Audio 播放器
function createPlayer(src, opts = {}) {
  const { snd, onPlay, onEnded, preload = 'auto', loop = false, autoplay = true } = opts
  try {
    const audio = new Audio(src)
    Object.assign(audio, { preload, loop })
    onPlay && audio.addEventListener('play', () => onPlay(snd, audio))
    onEnded && audio.addEventListener('ended', () => onEnded(snd, audio))
    applyVolumeToAudio(audio)
    autoplay && audio.play().catch(() => {})
    return audio
  } catch (e) {
    console.warn('[createPlayer] failed', e)
    return null
  }
}

// 播放音效並觸發動畫
const playSoundObject = snd =>
  snd?.src ? createPlayer(snd.src, { snd, onPlay: onPlayStart, onEnded: onPlayEnd }) : null
```

特性：
- 支援多音軌同時播放
- 全域音量控制
- 自動處理瀏覽器自動播放政策
- 播放時觸發頭像動畫（onPlayStart）
- 播放結束清理（onPlayEnd）

##### [ADHOC] 三周年特殊機制：音效時間軸觸發動畫

> **注意**：這是一個臨時性的特殊功能，未來可能重構為通用的音效事件系統。

**當前實作**：音效 `OVA1gg` 在播放到第 9 秒時，會觸發「貓下去問號頭像」從螢幕右側飛入到中央的動畫。

**技術實作**：

1. **CSS 樣式** (約 1181-1244 行)：
   - `.special-avatar-container`：固定在螢幕垂直中央高度 (`position: fixed; top: 50%`)
   - `.special-avatar`：圓形頭像樣式 (120px × 120px)
   - `@keyframes flyInFromRight`：從右側飛入動畫 (ease-out, 0.6s)
   - `@keyframes flyOutToLeft`：飛出到左側動畫 (ease-out, 0.6s)

2. **JavaScript 邏輯** (約 3190-3228 行，位於 `onPlayStart` 函數內)：
   ```javascript
   if (snd.id === 'OVA1gg') {
     const triggerTime = 9000; // 9 秒
     const displayDuration = 1000; // 停留 1 秒

     setTimeout(() => {
       // 建立頭像容器並加入 fly-in 動畫
       const container = dom.el('div', { class: 'special-avatar-container' });
       const avatarImg = dom.el('img', {
         src: 'avatars/catdown-問號.png',
         alt: '貓下去問號頭像',
         class: 'special-avatar fly-in'
       });
       container.appendChild(avatarImg);
       document.body.appendChild(container);

       // 1 秒後觸發飛出動畫
       setTimeout(() => {
         avatarImg.classList.remove('fly-in');
         avatarImg.classList.add('fly-out');
         // 動畫結束後移除元素
         avatarImg.addEventListener('animationend', () => {
           container.remove();
         }, { once: true });
       }, displayDuration);
     }, triggerTime);
   }
   ```

3. **動畫流程**：
   - 音效開始播放 → 倒數 9 秒
   - 第 9 秒：頭像從右側飛入 (0.6 秒，ease-out)
   - 停留在螢幕中央 1 秒
   - 飛出到左側 (0.6 秒，ease-out)
   - 動畫結束後自動清理 DOM 元素

**未來重構方向**：
- 將配置移至 `sounds.json` 中，新增 `avatarAnimations` 欄位
- 支援多個時間點觸發
- 支援同時顯示多個頭像
- 支援自訂動畫參數（持續時間、方向、緩動函數等）
- 抽象為通用的時間軸事件系統

#### 6. DOM 建構工具 (dom)

提供函式式 DOM 建構：

```javascript
const dom = {
  // 建立元素
  el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag)
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v
      else if (k === 'style') Object.assign(e.style, v)
      else if (k.startsWith('on') && typeof v === 'function')
        e.addEventListener(k.slice(2), v)
      else if (v != null) e.setAttribute(k, v)
    }
    for (const c of [].concat(children).filter(Boolean)) {
      e.append(c)
    }
    return e
  },

  // 建立愛心 SVG
  svgHeart() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('viewBox', '0 0 24 24')
    svg.innerHTML = '<path d="..." fill="none" stroke="currentColor" stroke-width="1.5"/>'
    return svg
  }
}
```

使用範例：

```javascript
const button = dom.el('button',
  { class: 'btn', onclick: () => alert('clicked') },
  ['點我']
)
```

#### 7. 通用工具函式 (utils)

```javascript
const utils = {
  // 正規化字串
  slug: s => s.normalize('NFKC').trim(),

  // 根據 ID 取得元素
  byId: id => document.getElementById(id),

  // 儲存最愛
  saveFav: () => localStorage.setItem(CONFIG.storage.favorites, JSON.stringify(state.favorites)),

  // 檢查最愛
  inFav: id => state.favSet.has(id),

  // 觸發下載
  download(url, filename) {
    const a = Object.assign(document.createElement('a'), { href: url, download: filename || '' })
    document.body.appendChild(a)
    a.click()
    a.remove()
  },

  // 解析搜尋查詢
  parseQuery() {
    const parts = state.queryText.trim().split(/\s+/).filter(Boolean)
    const tags = new Set([...state.queryTags])
    const terms = []
    for (const p of parts) {
      if (p.startsWith('#')) {
        tags.add(utils.slug(p.slice(1)))
      } else {
        terms.push(utils.slug(p))
      }
    }
    return { terms, tags }
  },

  // 判斷音效是否符合搜尋條件
  match(sound, terms, tags) {
    const lowerTitle = sound.title.toLowerCase()
    const sluggedTags = sound.tags.map(t => utils.slug(t))
    // 標籤過濾：音效必須包含所有已選標籤
    for (const t of tags) if (!sluggedTags.includes(t)) return false
    // 文字過濾：標題或標籤必須包含所有搜尋詞
    for (const term of terms) {
      const lower = term.toLowerCase()
      if (!lowerTitle.includes(lower) &&
          !sound.tags.some(t => t.toLowerCase().includes(lower))) return false
    }
    return true
  },

  // 防抖
  debounce(fn, wait = 200) {
    let t
    return (...args) => {
      clearTimeout(t)
      t = setTimeout(() => fn(...args), wait)
    }
  }
}
```

#### 8. 路由與 URL 管理

實現 URL 驅動狀態：

```javascript
// 建立 URLSearchParams
function buildSearchParams() {
  const params = new URLSearchParams(location.search)
  if (state.page && state.page !== 'home') {
    params.set('page', state.page)
  } else {
    params.delete('page')
  }
  return params
}

// 將狀態同步到 URL
function updateURLFromState(push = false) {
  const { terms, tags } = utils.parseQuery()
  const params = buildSearchParams()
  const allTags = [...tags].map(tk => '#' + tk)
  const q = [...terms, ...allTags].filter(Boolean).join(' ')
  q ? params.set('q', q) : params.delete('q')
  const qs = params.toString()
  const newURL = `${location.pathname}${qs ? '?' + qs : ''}`
  push ? history.pushState(null, '', newURL) : history.replaceState(null, '', newURL)
}

// 從 URL 讀取狀態
function applyURLToState() {
  const params = new URLSearchParams(location.search)
  const q = params.get('q') || ''
  const { terms, tags } = utils.parseQuery()
  state.queryText = terms.join(' ')
  state.queryTags = tags
  els.q.value = [state.queryText, ...[...tags].map(t => '#' + t)].join(' ')
  // 讀取分頁參數
  const pageParam = params.get('page')
  state.page = ['game', 'about', 'awards'].includes(pageParam) ? pageParam : 'home'
  // 讀取分享列表
  state.receivedList = params.get('list')?.split(',').filter(Boolean) ?? []
}

// 監聽瀏覽器前進/後退
window.addEventListener('popstate', () => {
  applyURLToState()
  render()
  focusSoundFromURL()
})
```

支援功能：
- 搜尋條件持久化（`?q=關鍵字 #標籤`）
- 分頁狀態（`?page=game`）
- 單一音效分享（`?sound=id`）
- 列表分享（`?list=id1,id2,id3`）
- 瀏覽器前進/後退

#### 9. UI 互動與事件處理

**分頁切換**：

```javascript
function showPage(pg) {
  const prevPage = state.page
  dispatchPageEvent(pg, prevPage, 'before')
  state.page = pg
  // 顯示/隱藏分頁
  for (const [key, elKey] of Object.entries(pageMap)) {
    els[elKey]?.classList.toggle('hidden', key !== pg)
  }
  // 更新導覽樣式
  els.navTabs.forEach(tab => {
    const isActive = tab.getAttribute('data-page') === pg
    tab.classList.toggle('active', isActive)
    tab.setAttribute('aria-selected', String(isActive))
  })
  document.body.classList.toggle('bg-full', pg === 'about')
  document.body.classList.remove('nav-open')
  updateURLFromState(true)
  dispatchPageEvent(pg, prevPage, 'after')
}
```

**主題切換**：

```javascript
// 初始化主題
const savedTheme = localStorage.getItem(CONFIG.storage.theme) ||
  (matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark')
applyTheme(savedTheme)

// 切換主題
els.themeBtn.addEventListener('click', () => {
  const next = document.documentElement.classList.contains('light') ? 'dark' : 'light'
  if (next === 'dark') playSoundById('oNTWqg') // 特殊音效：開燈啊
  localStorage.setItem(CONFIG.storage.theme, next)
  applyTheme(next)
})

function applyTheme(theme) {
  document.body.classList.add('no-transition')
  document.documentElement.classList.toggle('light', theme === 'light')
  document.body.offsetHeight // 強制 reflow
  document.body.classList.remove('no-transition')
}
```

**右鍵選單**：

```javascript
function openMenuForSound(snd, x, y) {
  const menu = els.menu
  if (!menu) return

  menu.innerHTML = ''

  // 播放
  menu.appendChild(dom.el('button',
    { class: 'menu-item', onclick: () => { playSoundObject(snd); menu.remove() } },
    ['▶ 播放']
  ))

  // 切換最愛
  const inFav = utils.inFav(snd.id)
  menu.appendChild(dom.el('button',
    { class: 'menu-item', onclick: () => { toggleFavorite(snd.id); menu.remove() } },
    [inFav ? '💔 移除最愛' : '❤️ 加入最愛']
  ))

  // 下載
  menu.appendChild(dom.el('button',
    { class: 'menu-item', onclick: () => { utils.download(snd.src, snd.file); menu.remove() } },
    ['⬇ 下載音效']
  ))

  // 分享
  menu.appendChild(dom.el('button',
    { class: 'menu-item', onclick: async () => {
        await navigator.clipboard.writeText(buildSoundURL(snd.id))
        toast(MESSAGES.toast.linkCopied)
        menu.remove()
      }
    },
    ['🔗 複製連結']
  ))

  // 加到混音軌道
  menu.appendChild(dom.el('button',
    { class: 'menu-item', onclick: () => { demaPanel.addSoundToTrack(snd, 0); menu.remove() } },
    ['🎵 加到軌道']
  ))

  positionMenu(x, y)
}
```

#### 10. UI 渲染函式

**主渲染函式**：

```javascript
function render() {
  const { terms, tags } = utils.parseQuery()

  // 篩選音效
  let filtered = state.sounds.filter(s => utils.match(s, terms, tags))

  // 若有接收的分享列表，優先顯示
  if (state.receivedList.length > 0) {
    const receivedSounds = state.receivedList
      .map(id => state.soundMap.get(id))
      .filter(Boolean)
    if (receivedSounds.length > 0) {
      renderReceivedList(receivedSounds)
    }
  }

  // 儲存顯示列表
  state.displayList = filtered
  state.renderedCount = 0

  // 清空容器
  els.grid.innerHTML = ''
  els.empty.classList.toggle('hidden', filtered.length > 0)

  // 渲染第一批
  renderNextBatch()

  // 渲染最愛面板
  renderFavPanel()

  // 渲染標籤列表
  renderTagList()

  // 渲染已選標籤
  renderActiveChips()
}
```

**分批渲染**：

使用 IntersectionObserver 實現虛擬滾動：

```javascript
function renderNextBatch() {
  const { displayList, renderedCount } = state
  const batchSize = CONFIG.ui.batchSize
  const nextBatch = displayList.slice(renderedCount, renderedCount + batchSize)

  if (nextBatch.length === 0) return

  // 渲染卡片
  const fragment = document.createDocumentFragment()
  nextBatch.forEach(snd => {
    fragment.appendChild(renderSoundCard(snd))
  })
  els.grid.appendChild(fragment)

  state.renderedCount += nextBatch.length

  // 若還有更多，設置觀察器
  if (state.renderedCount < displayList.length) {
    const lastCard = els.grid.lastElementChild
    if (lastCard) {
      state.observer?.disconnect()
      state.observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) {
          state.observer.disconnect()
          renderNextBatch()
        }
      }, { rootMargin: '500px' })
      state.observer.observe(lastCard)
    }
  }
}
```

**音效卡片渲染**：

```javascript
function renderSoundCard(snd, opts = { inFav: false }) {
  const card = dom.el('div', {
    class: 'card',
    id: 'snd-' + snd.id,
    'data-id': snd.id
  })

  // 播放按鈕
  const playBtn = dom.el('button', {
    class: 'card-play',
    'aria-label': '播放音效：' + snd.title,
    onclick: () => playSoundObject(snd)
  }, ['▶'])

  // 愛心按鈕
  const favBtn = dom.el('button', {
    class: 'card-fav' + (utils.inFav(snd.id) ? ' active' : ''),
    'aria-label': '加入最愛',
    onclick: (e) => {
      e.stopPropagation()
      toggleFavorite(snd.id, e.target)
    }
  }, [dom.svgHeart()])

  // 標題
  const title = dom.el('div', { class: 'card-title' }, [snd.title])

  // 標籤
  const tagsDiv = dom.el('div', { class: 'card-tags' })
  snd.tags.forEach(tagKey => {
    const tagDef = state.tags[tagKey]
    if (tagDef) {
      tagsDiv.appendChild(dom.el('span', {
        class: 'tag tag-sm',
        style: { background: tagDef.color || CONFIG.colors.defaultTag }
      }, [tagDef.name]))
    }
  })

  card.append(playBtn, favBtn, title, tagsDiv)

  // 右鍵選單（桌面）
  card.addEventListener('contextmenu', (e) => {
    e.preventDefault()
    openMenuForSound(snd, e.clientX, e.clientY)
  })

  // 長按選單（行動裝置）
  let timer = null
  card.addEventListener('touchstart', (e) => {
    timer = setTimeout(() => {
      const touch = e.touches[0]
      openMenuForSound(snd, touch.clientX, touch.clientY)
    }, CONFIG.timing.longPressDelay)
  })
  card.addEventListener('touchend', () => clearTimeout(timer))
  card.addEventListener('touchmove', () => clearTimeout(timer))

  return card
}
```

**最愛面板渲染**：

```javascript
function renderFavPanel() {
  const container = els.favGrid
  if (!container) return

  container.innerHTML = ''
  els.favEmpty.classList.toggle('hidden', state.favorites.length > 0)

  state.favorites.forEach(id => {
    const snd = state.soundMap.get(id)
    if (snd) {
      container.appendChild(renderSoundCard(snd, { inFav: true }))
    }
  })

  // 初始化拖曳排序
  if (!state.sortable && container) {
    state.sortable = Sortable.create(container, {
      animation: 150,
      disabled: !state.isSorting,
      onEnd: (evt) => {
        const [moved] = state.favorites.splice(evt.oldIndex, 1)
        state.favorites.splice(evt.newIndex, 0, moved)
        utils.saveFav()
      }
    })
  } else {
    state.sortable?.option('disabled', !state.isSorting)
  }
}
```

#### 11. 初始化流程

```javascript
async function loadConfig() {
  try {
    // 載入標籤定義
    const tagsRes = await fetch(withV(CONFIG.paths.tags))
    const tagsJson = await tagsRes.json()
    state.tags = Object.fromEntries(tagsJson.map(t => [t.key, t]))
    state.tagList = tagsJson

    // 載入音效清單
    const soundsRes = await fetch(withV(CONFIG.paths.sounds))
    const soundsJson = await soundsRes.json()

    // 轉換為音效物件並建立映射
    state.sounds = soundsJson.map(s => ({
      ...s,
      src: `sounds/${s.file}?v=${VERSION}`
    }))
    state.soundMap = new Map(state.sounds.map(s => [s.id, s]))
    state.defaultSoundsSnapshot = [...state.sounds]

    // 統計使用的標籤
    const usedTags = new Set()
    state.sounds.forEach(s => s.tags.forEach(t => usedTags.add(t)))
    state.usedTagList = state.tagList.filter(t => usedTags.has(t.key))

    // 執行最愛遷移
    migrateFavoritesFromFilesToIds(soundsJson)

    // 載入票選結果（可選）
    try {
      const voteRes = await fetch(withV(CONFIG.paths.voteResults))
      const voteJson = await voteRes.json()
      await applyVoteResultsOrdering(voteJson)
    } catch (e) {
      console.warn('[loadConfig] 票選結果載入失敗', e)
    }

  } catch (err) {
    console.error('[loadConfig] 載入失敗', err)
    document.body.innerHTML = `<div class="error">${MESSAGES.errors.configLoadFailed}</div>`
    throw err
  }
}

// 應用程式入口
async function init() {
  await loadConfig()
  applyURLToState()
  render()
  initEvents()
  setupConcentrationGame()
  focusSoundFromURL()
}

// 啟動
init().catch(err => console.error('[init] 初始化失敗', err))
```

#### 12. 記憶小遊戲

實作配對翻牌遊戲：

```javascript
function setupConcentrationGame() {
  let gameState = {
    pairs: [],          // 配對陣列 [{id, title, src}, ...]
    board: [],          // 遊戲板 [{pairIdx, flipped, matched}, ...]
    flipped: [],        // 已翻開的卡片索引
    moves: 0,           // 步數
    matches: 0,         // 配對成功數
    timer: null,        // 計時器
    startTime: 0        // 開始時間
  }

  function pickPairs() {
    const validSounds = state.sounds.filter(s => s.src)
    if (validSounds.length === 0) return false

    const selected = shuffleInPlace([...validSounds])
      .slice(0, CONFIG.game.pairCount)

    gameState.pairs = selected.map(s => ({
      id: s.id,
      title: s.title,
      src: s.src
    }))

    return true
  }

  function startGame() {
    if (!pickPairs()) {
      toast(MESSAGES.errors.gameNoSounds)
      return
    }

    // 建立遊戲板（每對兩張）
    gameState.board = []
    gameState.pairs.forEach((pair, idx) => {
      gameState.board.push({ pairIdx: idx, flipped: false, matched: false })
      gameState.board.push({ pairIdx: idx, flipped: false, matched: false })
    })
    shuffleInPlace(gameState.board)

    gameState.flipped = []
    gameState.moves = 0
    gameState.matches = 0
    gameState.startTime = Date.now()

    startTimer()
    updateBoard()
    updateStats()
  }

  function onCardClick(idx) {
    const card = gameState.board[idx]
    if (card.flipped || card.matched || gameState.flipped.length >= 2) return

    card.flipped = true
    gameState.flipped.push(idx)
    updateBoard()

    // 播放音效
    const pair = gameState.pairs[card.pairIdx]
    playSoundObject(pair)

    if (gameState.flipped.length === 2) {
      gameState.moves++
      updateStats()

      setTimeout(() => {
        checkMatchPair(gameState.flipped[0], gameState.flipped[1])
      }, CONFIG.game.cardFlipDelay)
    }
  }

  function checkMatchPair(idx1, idx2) {
    const card1 = gameState.board[idx1]
    const card2 = gameState.board[idx2]

    if (card1.pairIdx === card2.pairIdx) {
      // 配對成功
      card1.matched = true
      card2.matched = true
      gameState.matches++

      if (gameState.matches === gameState.pairs.length) {
        endGame()
      }
    } else {
      // 配對失敗，翻回
      card1.flipped = false
      card2.flipped = false
    }

    gameState.flipped = []
    updateBoard()
  }

  function endGame() {
    clearInterval(gameState.timer)

    // 計算準確率
    const maxMoves = gameState.pairs.length
    const accuracy = (maxMoves / gameState.moves) * 100

    if (accuracy >= CONFIG.game.rewardAccuracy) {
      // 觸發獎勵音效
      setTimeout(() => {
        const rewardId = CONFIG.game.rewardSoundIds[
          Math.floor(Math.random() * CONFIG.game.rewardSoundIds.length)
        ]
        playSoundById(rewardId)
        toast(MESSAGES.toast.gameReward)
      }, 500)
    }
  }

  // 綁定開始按鈕
  document.getElementById('gameStartBtn')?.addEventListener('click', startGame)
}
```

#### 13. demaPanel 多軌混音編輯器

完整的音訊編輯器，詳細實作請見原始碼第 3600+ 行。

主要功能：
- 3 軌道系統
- 時間軸與 Playhead
- 音效片段拖曳、調整長度、裁剪
- 播放/暫停/停止控制
- Undo/Redo 歷史記錄
- 片段音量控制
- localStorage 持久化
- 縮放控制

---

## 資料結構

### sounds.json

```json
[
  {
    "file": "萬-最棒的音效版.mp3",
    "title": "最棒的音效版",
    "tags": ["阿萬"],
    "id": "Fz95EA"
  }
]
```

### tags.json

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

### vote-results.json

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

## Local Storage 使用

### 儲存鍵值

| 鍵名 | 類型 | 說明 |
|------|------|------|
| `favorites` | JSON Array | 收藏的音效 ID 列表 |
| `favorites_version` | String | 收藏列表版本號（"2"） |
| `favorites_legacy_backup` | JSON Array | 舊版收藏備份 |
| `theme` | String | 主題（"light" / "dark"） |
| `globalVolume` | String | 全域音量（"0.0" - "1.0"） |
| `demaPanel_state` | JSON Object | demaPanel 狀態 |

### 最愛列表遷移

舊版使用檔名，新版使用 ID：

```javascript
function migrateFavoritesFromFilesToIds(soundsJson) {
  try {
    const raw = localStorage.getItem(CONFIG.storage.favorites)
    if (!favoritesNeedMigration(raw)) {
      localStorage.setItem(CONFIG.storage.favoritesVersion, '2')
      return
    }

    const legacy = parseLegacyFavorites(raw)
    const fileToIdMap = new Map()
    buildFileMapsFromConfig(soundsJson).forEach((id, file) => {
      fileToIdMap.set(file, id)
    })

    const out = []
    let missing = 0
    legacy.forEach(item => {
      const id = fileToIdMap.get(item)
      if (id) out.push(id)
      else missing++
    })

    localStorage.setItem(CONFIG.storage.favoritesBackup, raw)
    localStorage.setItem(CONFIG.storage.favorites, JSON.stringify(out))
    localStorage.setItem(CONFIG.storage.favoritesVersion, '2')

    state.favorites = out
    state.favSet = new Set(out)

    toast(MESSAGES.toast.favMigrated(out.length, missing))
  } catch (e) {
    console.warn('[migrateFavorites] 遷移失敗', e)
  }
}
```

---

## 樣式系統

### CSS 變數架構

```css
:root {
  /* 暗色主題（預設） */
  --bg: #0b0d10;
  --fg: #e9eef5;
  --card: #141821;
  --accent: #6aa9ff;
  --heart: #ff5a7a;

  /* 間距（4px 基礎） */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;

  /* 圓角 */
  --radius-sm: 8px;
  --radius-md: 10px;
  --radius-lg: 12px;

  /* 陰影 */
  --shadow-sm: 0 2px 6px rgba(0, 0, 0, 0.18);
  --shadow-md: 0 6px 24px rgba(0, 0, 0, 0.25);

  /* 動畫時間 */
  --duration-fast: 0.06s;
  --duration-normal: 0.15s;
  --duration-slow: 0.3s;
}

:root.light {
  /* 亮色主題覆寫 */
  --bg: #f8fafc;
  --fg: #0d1320;
  --card: #ffffff;
  --accent: #2563eb;
}
```

### 響應式設計

```css
/* 卡片網格 */
.sounds-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-lg);
}

@media (max-width: 1024px) {
  .sounds-grid {
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  }
}

@media (max-width: 640px) {
  .sounds-grid {
    grid-template-columns: 1fr;
  }
}
```

---

## 效能最佳化

### 分批渲染

使用 IntersectionObserver 實現虛擬滾動，每次渲染 72 張卡片（6 欄 x 12 列），當使用者滾動到底部時載入下一批。

### 事件委派

避免為每張卡片綁定事件，使用事件委派：

```javascript
els.grid.addEventListener('click', (e) => {
  const card = e.target.closest('.card')
  if (!card) return
  const id = card.dataset.id
  // 處理點擊...
})
```

### 防抖搜尋

搜尋輸入使用 180ms 防抖，避免頻繁重新渲染。

---

## 相關文檔

- [scripts-guide.md](scripts-guide.md) - 腳本與資料管理相關文檔
- [adhoc-features.md](adhoc-features.md) - ADHOC 特殊功能文檔（臨時性功能說明）
