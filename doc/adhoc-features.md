# ADHOC 特殊功能文檔

本文件記錄專案中的臨時性特殊功能。這些功能通常是為特定事件或需求而設計，未來可能會重構為更通用的系統。

---

## 三周年特殊機制：音效時間軸觸發頭像動畫

### 概述

這是一個為三周年慶祝活動設計的特殊功能。當播放特定音效（`OVA1gg`）時，在音效播放到第 9 秒時會觸發一個頭像動畫效果。

### 功能行為

**觸發條件**：
- 音效 ID：`OVA1gg`
- 觸發時間點：音效播放後第 9 秒

**動畫效果**：
1. 頭像從螢幕右側飛入（ease-out 緩動，耗時 0.6 秒）
2. 停留在螢幕正中央（垂直置中，水平置中），持續 1 秒
3. 頭像從中央飛出到左側（ease-out 緩動，耗時 0.6 秒）
4. 動畫結束後自動清理 DOM 元素

**頭像資源**：
- 檔案路徑：`avatars/catdown-問號.png`
- 尺寸：120px × 120px（圓形顯示）

### 技術實作

#### 1. CSS 樣式定義

位置：[index-raw.html](../index-raw.html) 約 1181-1244 行

```css
/* =========================================================================
   [ADHOC] 三周年特殊機制：特定音效觸發頭像飛入動畫

   此為臨時性功能，未來可能重構為通用的音效事件系統。
   目前實作：OVA1gg 音效在第 9 秒時觸發貓下去頭像從右側飛入

   TODO (未來重構):
   - 將配置移至 sounds.json 中 (如 avatarAnimations 欄位)
   - 支援多個時間點、多個頭像、自訂動畫參數
   ========================================================================= */

/* 特殊頭像容器：固定在螢幕中央高度，用於飛入動畫 */
.special-avatar-container {
  position: fixed;
  top: 50%;
  right: 0;
  transform: translateY(-50%);
  z-index: 999;
  pointer-events: none;
}

/* 特殊頭像樣式 */
.special-avatar {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  border: 3px solid rgba(255, 255, 255, 0.8);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
  object-fit: cover;
}

/* 飛入動畫：從右側進入螢幕中央 (ease-out) */
@keyframes flyInFromRight {
  0% {
    transform: translateX(150px);
    opacity: 0;
  }
  100% {
    transform: translateX(calc(-50vw + 60px));
    opacity: 1;
  }
}

/* 飛出動畫：從中央離開到左側 (ease-out) */
@keyframes flyOutToLeft {
  0% {
    transform: translateX(calc(-50vw + 60px));
    opacity: 1;
  }
  100% {
    transform: translateX(calc(-100vw - 150px));
    opacity: 0;
  }
}

/* 飛入動畫類別 */
.fly-in {
  animation: flyInFromRight 0.6s ease-out forwards;
}

/* 飛出動畫類別 */
.fly-out {
  animation: flyOutToLeft 0.6s ease-out forwards;
}
```

#### 2. JavaScript 事件邏輯

位置：[index-raw.html](../index-raw.html) 約 3190-3228 行，在 `onPlayStart` 函數內

```javascript
/* =====================================================================
   [ADHOC] 三周年特殊機制：OVA1gg 音效的頭像飛入動畫

   在第 9 秒時觸發貓下去頭像從右側飛入，停留 1 秒後飛出

   TODO (未來重構):
   - 將此邏輯抽離為通用函數
   - 支援從 sounds.json 讀取配置 (觸發時間、頭像、動畫參數)
   ===================================================================== */
if (snd.id === 'OVA1gg') {
  // 在第 9 秒觸發頭像飛入
  const triggerTime = 9000; // 9 秒 = 9000 毫秒
  const displayDuration = 1000; // 停留 1 秒

  setTimeout(() => {
    // 建立特殊頭像容器
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
/* ===================================================================== */
```

### 時間軸說明

```
音效播放開始
    |
    |-- 0.0s  音效開始播放
    |
    |-- 9.0s  頭像開始從右側飛入
    |-- 9.6s  頭像到達螢幕中央（飛入動畫結束）
    |
    |-- 10.6s 頭像開始飛出到左側
    |-- 11.2s 頭像完全離開螢幕（飛出動畫結束）
    |         DOM 元素自動清理
```

總動畫時長：約 2.2 秒（從第 9 秒開始到第 11.2 秒結束）

### 測試方法

1. 開啟網站
2. 搜尋並播放音效 `OVA1gg`（可透過搜尋欄輸入 ID 或相關標籤）
3. 等待約 9 秒
4. 觀察螢幕右側是否有頭像飛入到中央
5. 確認頭像停留約 1 秒後飛出

### 已知限制

1. **硬編碼邏輯**：目前觸發邏輯直接寫在 `onPlayStart` 函數中，擴展性有限
2. **單一音效專屬**：僅支援 `OVA1gg` 這一個音效
3. **固定時間點**：無法靈活調整觸發時間
4. **單一頭像**：無法支援多個頭像同時或依序出現
5. **手動維護**：所有參數（時間、頭像路徑、動畫參數）都需手動在程式碼中修改

### 未來重構規劃

#### 階段 1：抽象化邏輯

將硬編碼邏輯抽離為可重用函數：

```javascript
/**
 * 在音效播放特定時間點觸發頭像飛入動畫
 * @param {Audio} audio - Audio 元素
 * @param {Object} config - 配置物件
 * @param {number} config.triggerTime - 觸發時間（毫秒）
 * @param {string} config.avatarSrc - 頭像圖片路徑
 * @param {number} config.displayDuration - 停留時間（毫秒）
 */
function scheduleAvatarAnimation(audio, config) {
  // 實作...
}
```

#### 階段 2：配置檔案化

在 `sounds.json` 中新增欄位：

```json
{
  "id": "OVA1gg",
  "file": "sounds/貓下去-3周年貓下去.m4a",
  "tags": ["貓下去", "三周年"],
  "avatarAnimations": [
    {
      "triggerTime": 9000,
      "avatarSrc": "avatars/catdown-問號.png",
      "displayDuration": 1000,
      "animationType": "flyInFromRight"
    }
  ]
}
```

#### 階段 3：通用事件系統

設計完整的音效事件系統，支援：
- 多個時間點觸發
- 多種動畫類型（飛入、彈出、淡入淡出等）
- 自訂動畫參數（速度、緩動函數、起始/結束位置）
- 複合效果（同時觸發多個動畫）
- 事件類型擴展（不僅限於頭像，還可以是文字、特效等）

### 維護注意事項

1. **標註清楚**：所有相關程式碼都已使用 `[ADHOC]` 標記，方便搜尋定位
2. **註解完整**：每段程式碼都有詳細註解說明用途和未來重構方向
3. **文檔更新**：本文檔、[architecture.md](architecture.md) 都已記錄此功能
4. **版本控制**：修改此功能時請在 commit message 中說明
5. **重構時機**：當需要為其他音效添加類似功能時，應考慮進行重構

### 相關檔案

- 主要程式碼：[index-raw.html](../index-raw.html)
  - CSS：約 1181-1244 行
  - JavaScript：約 3190-3228 行
- 頭像資源：[avatars/catdown-問號.png](../avatars/catdown-問號.png)
- 架構文檔：[architecture.md](architecture.md#adhoc-三周年特殊機制音效時間軸觸發動畫)

### 變更歷史

- **2025-12-16**：初始實作，為三周年活動新增 OVA1gg 音效的頭像飛入動畫

---

## 新增 ADHOC 功能的指引

如果未來需要新增類似的臨時性特殊功能，請遵循以下步驟：

1. **明確標註**：在所有相關程式碼（CSS/JS/HTML）前加上 `[ADHOC]` 註解
2. **完整註解**：說明功能用途、觸發條件、未來重構方向
3. **更新文檔**：
   - 在本文件中新增章節
   - 在 [architecture.md](architecture.md) 中記錄技術細節
   - 必要時更新 README
4. **命名規範**：使用描述性的 class 名稱，避免與現有樣式衝突
5. **獨立性**：盡量保持功能獨立，降低對現有系統的影響
6. **可測試性**：提供明確的測試步驟
7. **記錄限制**：明確列出功能的限制和已知問題
8. **規劃重構**：描述未來如何將此功能整合為通用系統

這樣可以確保即使是臨時性功能，也能保持程式碼的可維護性和可讀性。
