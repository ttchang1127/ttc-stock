# ttc-stock Dashboard 維運 SOP（機械化執行版）

> **這份文件寫給誰**：維護本知識庫的 AI 助理（目前為 Gemini 3.6 Flash）。
> **怎麼用**：找到對應的「任務」章節，**照抄指令、照順序執行、比對預期輸出**。
> **不要自己想辦法。** 遇到本文件沒寫到的狀況，一律停止並回報使用者。

最後更新：2026-08-01

---

## 0. 紅線：以下事項絕對禁止

違反任何一條都會讓網站顯示假資料給使用者看。**沒有例外，沒有「這次應該沒關係」。**

| # | 禁止事項 | 原因 |
|---|---|---|
| 1 | 手動輸入、估算、或「合理推測」任何股價或 MACD 數字 | 網站曾因此顯示假資料長達數個版本 |
| 2 | 直接用文字編輯器修改 `prices.json` | 這個檔案**只能**由 `scripts/fetch_price_history.py` 產生 |
| 3 | 在程式碼中加入任何 `Math.random()`、`Math.sin()`、`Math.cos()` 來產生價格 | 舊版曾用 sin/cos 假造走勢，已移除，不准復活 |
| 4 | 把 MACD 柱體公式改成 `(dif - signal) * 2` | 現行版本是 `dif - signal`，乘 2 會讓柱體蓋住線 |
| 5 | 在資料來源不明或失敗時，把橫幅文字寫成「已驗證」「真實資料」 | 失敗時必須顯示紅色錯誤橫幅 |
| 6 | `git commit` 包含 `.obsidian/` 目錄 | 那是 Obsidian 視窗狀態，與網站無關 |
| 7 | 修改 `dashboard_mag7.html` | 那是另一個獨立頁面，不在本 SOP 範圍 |
| 8 | 使用 `git push --force` 或 `git reset --hard` | 會毀掉遠端歷史 |

---

## 1. 檔案地圖

工作目錄（以下所有指令都在這裡執行）：

```
/Volumes/Crucial X8/Jarvis Obsidian/Sec_kb
```

| 檔案 | 用途 | 你可以改嗎 |
|---|---|---|
| `dashboard.html` | 網站主頁（含全部 JS 計算邏輯） | ⚠️ 只在使用者明確要求時 |
| `prices.json` | 真實日線收盤價資料庫 | ❌ 只能由腳本產生 |
| `scripts/fetch_price_history.py` | 抓價腳本 | ⚠️ 只改 `DEFAULT_TICKERS` 那一行 |
| `.github/workflows/update-prices.yml` | 每日自動更新排程 | ❌ 不要改 |
| `dashboard_mag7.html` | 另一個獨立頁面 | ❌ 不在範圍內 |

遠端與網址：

- Git remote：`git@github.com:ttchang1127/ttc-stock.git`
- 分支：`main`
- 線上網址：https://ttchang1127.github.io/ttc-stock/dashboard.html

---

## 2. 資料怎麼流動（讀懂這段就好，不用改任何東西）

```
yfinance (Yahoo Finance)
        ↓  scripts/fetch_price_history.py
   prices.json          ← 真實收盤價，跟著 git commit 一起進 repo
        ↓  dashboard.html 用 fetch('prices.json') 讀取
   瀏覽器端計算 MACD 並畫圖
```

**為什麼不讓瀏覽器直接抓 Yahoo？**
因為 GitHub Pages 是純靜態網站，而 Yahoo 的 API 不回傳 CORS 標頭，瀏覽器一定會被擋。**不要嘗試改回直連 Yahoo，一定會失敗。**

---

## 3. 任務 A：更新股價資料

### 什麼時候做
使用者說「更新股價」「資料太舊」的時候。
（平日有 GitHub Actions 自動做，通常不需要手動執行。）

### 步驟

**A-1. 進入目錄**

```bash
cd "/Volumes/Crucial X8/Jarvis Obsidian/Sec_kb"
```

**A-2. 執行抓價腳本**

```bash
python3 scripts/fetch_price_history.py
```

**A-3. 看輸出，對照下表決定下一步**

| 你看到的輸出 | 代表 | 下一步 |
|---|---|---|
| `Wrote prices.json (13 tickers, ...)` | 有新資料 | 前往 A-4 |
| `No new quotes; leaving prices.json unchanged` | 資料沒變（假日或已是最新） | **停止，不要 commit**，回報「資料已是最新」 |
| `No tickers fetched; refusing to overwrite` | 全部抓取失敗 | **停止**，回報使用者「Yahoo 連線失敗」 |
| 出現 `FAILED` 但仍有 `Wrote prices.json` | 部分股票抓失敗 | 前往 A-4，並在回報中列出失敗的代號 |

**A-4. 確認只有 prices.json 被改動**

```bash
git status --short
```

預期輸出**只能**有這一行（`.obsidian/workspace.json` 若出現請忽略、不要加入）：

```
 M prices.json
```

若出現其他檔案被修改 → **停止**，回報使用者。

**A-5. Commit 並推送**

```bash
git add prices.json && git commit -m "chore: refresh prices.json" && git push origin main
```

**A-6. 等待 1～3 分鐘後驗證網站**

```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://ttchang1127.github.io/ttc-stock/prices.json"
```

預期輸出：`200`
若是 `404` → 再等 2 分鐘重跑一次。連續三次都 404 → 停止並回報。

---

## 4. 任務 B：新增追蹤標的

### 步驟

**B-1. 開啟 `scripts/fetch_price_history.py`，找到這一段**

```python
DEFAULT_TICKERS = [
    "NVDA", "GOOG", "ARM", "MRVL", "COHR", "TSLA", "INTC",
    "NOK", "ONDS", "TSM", "AAPL", "MSFT", "META",
]
```

**B-2. 把新代號加進去**（例如要加 `AMZN`）

```python
DEFAULT_TICKERS = [
    "NVDA", "GOOG", "ARM", "MRVL", "COHR", "TSLA", "INTC",
    "NOK", "ONDS", "TSM", "AAPL", "MSFT", "META", "AMZN",
]
```

⚠️ 只改這個清單。**不要動檔案中其他任何一行。**

**B-3. 執行腳本**

```bash
python3 scripts/fetch_price_history.py
```

在輸出中找新代號那一行。若顯示 `FAILED` → 代表代號打錯或 Yahoo 沒有這檔，**把它從清單移除**並回報使用者。

**B-4. Commit 並推送**

```bash
git add prices.json scripts/fetch_price_history.py && git commit -m "feat: track AMZN" && git push origin main
```

### ⚠️ 重要限制

只做 B-1～B-4，新代號**只會**進入「回溯分析器」的可查詢範圍。

它**不會**自動出現在下方持股表格與總覽圖 —— 那需要另外在 `dashboard.html` 的 `titansData` 陣列補上該公司的基本面資料（毛利率、F-Score、DCF 估值等）。
**這些數字你沒有來源，不准編造。** 若使用者要求把新標的加進表格，回覆：「需要先提供該公司的基本面數據」。

---

## 5. 任務 C：驗證網站是否正常

任何改動推送後，執行這三個檢查。

**C-1. 資料檔存在**

```bash
curl -s -o /dev/null -w "prices.json: %{http_code}\n" "https://ttchang1127.github.io/ttc-stock/prices.json"
```
預期：`prices.json: 200`

**C-2. 網頁存在**

```bash
curl -s -o /dev/null -w "dashboard.html: %{http_code}\n" "https://ttchang1127.github.io/ttc-stock/dashboard.html"
```
預期：`dashboard.html: 200`

**C-3. 假資料產生器沒有復活**（最重要）

```bash
cd "/Volumes/Crucial X8/Jarvis Obsidian/Sec_kb" && grep -c "Math.sin\|Math.random\|seedMap" dashboard.html
```

預期輸出：`0`

**若不是 0 → 代表假資料程式碼被加回來了。立刻停止，回報使用者。**

---

## 6. 不可更動的計算規則

若使用者要求修改圖表，先確認不會破壞以下規則。**有疑慮就先問，不要自己決定。**

| 項目 | 現行規則 |
|---|---|
| EMA 參數 | 快線 12、慢線 26、Signal 9 |
| DIF | `EMA(12) - EMA(26)` |
| Signal | `EMA(DIF, 9)` |
| 柱體 Histogram | `DIF - Signal`（**不乘 2**） |
| EMA 預熱 | 用 `prices.json` 全部歷史（約 751 筆）計算後才裁切顯示區間 |
| 日線圖單位 | 絕對美元 |
| 總覽圖單位 | **柱體 ÷ 股價 × 100，即百分比**（跨股票才可比較） |

### 四色定義

| 顏色碼 | 名稱 | 條件 |
|---|---|---|
| `#10b981` | 亮綠 | `hist >= 0` 且 `hist >= 前一根` |
| `#059669` | 暗綠 | `hist >= 0` 且 `hist < 前一根` |
| `#ef4444` | 亮紅 | `hist < 0` 且 `hist <= 前一根` |
| `#f43f5e` | 暗粉 | `hist < 0` 且 `hist > 前一根` |

⚠️ 「前一根」在**日線圖**是指前一個交易日；在**總覽圖**是指**該檔股票自己的**前一交易日，**不是隔壁那檔股票**。

---

## 7. 故障排除對照表

| 症狀 | 原因 | 處理 |
|---|---|---|
| 網頁顯示紅色橫幅「無法載入 prices.json」 | 檔案沒推上去或路徑錯 | 執行 C-1，若 404 則重跑任務 A |
| 網頁顯示「資料庫中沒有代號 XXX」 | 該股票不在追蹤清單 | 這是**正常行為**，不是錯誤。要加請走任務 B |
| GitHub Actions 顯示紅色失敗 | 多半是 Yahoo 暫時故障 | 隔天會自動再跑一次。連續失敗三天才需回報 |
| Actions 的 push 步驟 403 | repo 權限設定問題 | 回報使用者：需到 Settings → Actions → General 開啟寫入權限 |
| 排程突然完全不跑 | GitHub 對 60 天無活動的 repo 自動停用排程 | 回報使用者到 Actions 分頁手動重新啟用 |
| 圖表柱體大小很奇怪 | 可能有人改動了計算公式 | 執行 C-3，並比對第 6 章規則 |

---

## 8. 什麼時候必須停下來問人

遇到以下任一情況，**不要嘗試自己解決**，直接回報使用者：

1. 本文件沒有描述的錯誤訊息
2. `git status` 出現預期外的檔案改動
3. 需要修改 `dashboard.html` 的計算邏輯
4. 需要填寫任何你沒有可靠來源的數字
5. 任何操作連續失敗三次
6. 需要執行本文件沒有列出的指令

---

## 附錄：目前追蹤的 13 檔標的

`NVDA` `GOOG` `ARM` `MRVL` `COHR` `TSLA` `INTC` `NOK` `ONDS` `TSM` `AAPL` `MSFT` `META`

自動更新排程：每週一至週五 UTC 23:00（美股收盤後約 3 小時）。
