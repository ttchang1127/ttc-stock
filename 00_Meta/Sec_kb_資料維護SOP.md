# Sec_kb 資料維護 SOP（機械化執行版）

> **這份文件寫給誰**：維護本知識庫的 AI 助理（目前為 Gemini 3.6 Flash）。
> **怎麼用**：找到對應的「任務」章節，**照抄指令、照順序執行、比對預期輸出**。
> **不要自己想辦法。** 遇到本文件沒寫到的狀況，一律停止並回報使用者。
>
> 儀表板網頁的維護請看 [[ttc-stock_Dashboard_維運SOP]]，那是另一條線。

最後更新：2026-08-01

---

## 0. 紅線：以下事項絕對禁止

這些不是建議。**每一條都對應本庫真實發生過的錯誤。**

| # | 禁止事項 | 這條規則為什麼存在 |
|---|---|---|
| 1 | **手動輸入、估算、或「合理推測」任何財務數字** | 舊版腳本寫死 `total_assets_2026 = 115000 # approximate`，真實值是 206,803，少報 44% |
| 2 | **直接把分數或結論賦值** | 舊版 `f1 = 1 ... f9 = 1` 九項全部手動設 1，宣稱「F-Score 9/9 滿分」，真實值是 **4/9** |
| 3 | **在筆記寫「SEC 官方財報」除非數字真的來自 XBRL API** | 舊版 thesis 宣稱資料來自 SEC，實際是手打的 |
| 4 | 直接用文字編輯器修改 `financials.json` / `fundamentals.json` / `prices.json` | 這三個檔案**只能**由腳本產生 |
| 5 | 資料缺漏時用前一版的數字頂替 | 缺就是缺，必須顯示「資料不足」 |
| 6 | 把 `dashboard.html` 複製到其他目錄 | `30_Analysis/` 曾有一份舊版，內含假資料產生器，誤導了很久 |
| 7 | `git push --force` 或 `git reset --hard` | 會毀掉遠端歷史 |
| 8 | commit `.obsidian/`、`*/raw/*.html` | 前者是視窗狀態，後者是 394MB 原始財報，已在 `.gitignore` |
| 9 | **重建任何 `scripts/run_*.py`** | 那 11 支寫死數字的舊腳本已於 2026-08-01 刪除。不要從 git 歷史還原它們 |

**判斷原則**：如果一個數字你說不出它來自哪一份 filing 的哪一個 XBRL 標籤，**就不准寫進筆記**。

---

## 1. 資料怎麼流動

```
SEC XBRL Company Facts API          Yahoo Finance (yfinance)
        ↓ fetch_xbrl_financials.py          ↓ fetch_price_history.py
   financials.json                      prices.json
        ↓ compute_fundamentals.py  ←──────────┘（市值需要股價）
   fundamentals.json
        ↓ update_thesis_financials.py
   30_Analysis/*_Master_Investment_Thesis_2026.md 的第二、三章
```

這四支腳本必須**照這個順序**執行，後面的依賴前面的產出。

| 檔案 | 由誰產生 | 你可以改嗎 |
|---|---|---|
| `financials.json` | `fetch_xbrl_financials.py` | ❌ |
| `fundamentals.json` | `compute_fundamentals.py` | ❌ |
| `prices.json` | `fetch_price_history.py`（預設 6 年，5 年 Sortino 需要） | ❌ |
| `20_Filings/**` | `fetch_sec.py` | ❌ |
| thesis 第二、三章 | `update_thesis_financials.py` | ❌ |
| thesis 第一、四、五章 | 人類撰寫的敘述 | ⚠️ 只在使用者明確要求時 |

---

## 2. 任務 A：更新全部財務數據（最常用）

### 步驟

**A-1.**
```bash
cd "/Volumes/Crucial X8/Jarvis Obsidian/Sec_kb"
```

**A-2. 抓 SEC 財報**
```bash
python3 scripts/fetch_xbrl_financials.py
```
預期：14 家公司各印一行，最後 `Wrote financials.json (14 companies, ...)`

**A-3. 計算指標**
```bash
python3 scripts/compute_fundamentals.py
```
預期：一張表格，最後 `Wrote fundamentals.json (14 companies)`

**A-4. 更新 thesis 第二、三章**
```bash
python3 scripts/update_thesis_financials.py
```
預期：`已更新 14 份 thesis`

**A-5. 確認只有該動的檔案被動到**
```bash
git status --short
```

允許出現的檔案**只有**：`financials.json`、`fundamentals.json`、`30_Analysis/*_Master_Investment_Thesis_2026.md`

出現任何其他檔案 → **停止並回報**。

**A-6. 送出**
```bash
git add financials.json fundamentals.json 30_Analysis/ && git commit -m "chore: refresh SEC financials" && git push origin main
```

### 輸出對照表

| 你看到的 | 意思 | 下一步 |
|---|---|---|
| `FAILED - not in SEC ticker index` | 代號打錯 | 停止，回報使用者 |
| `FAILED - HTTPError` | SEC 暫時故障或被限流 | 等 10 分鐘重試一次；再失敗就停止回報 |
| 某公司科目數是 `11/14` 之類 | 該公司沒有 tag 那些科目 | **正常**，不是錯誤，繼續 |
| `資料不足` 出現在 thesis | 該科目 SEC 沒有 | **正常**，不准去別處找數字補 |
| `No companies fetched; refusing to overwrite` | 全部失敗 | 停止，回報使用者 |

---

## 3. 任務 B：新增一家公司

**B-1. 抓 SEC 申報文件與筆記**
```bash
python3 scripts/fetch_sec.py AMD --years 5 --download-raw
```

**B-2. 把代號加入三個清單**

| 檔案 | 變數 |
|---|---|
| `scripts/fetch_xbrl_financials.py` | `DEFAULT_TICKERS` |
| `scripts/fetch_price_history.py` | `DEFAULT_TICKERS` |

⚠️ 只改清單那幾行，不要動其他程式碼。

**B-3. 重跑任務 A 的 A-2 ~ A-6**

**B-4.** 若使用者要求也加進儀表板表格，回覆：
> 儀表板的 `titansData` 需要基本面敘述（護城河、championTag 等），這些不在 SEC 結構化資料裡。請提供內容，或確認要留空。

**不准自己編造這些欄位。**

---

## 4. 任務 C：驗證資料誠信（每次改動後必跑）

**C-1. 假資料產生器沒有復活**
```bash
grep -rc "Math.sin\|Math.random\|seedMap" dashboard.html
```
預期 `0`。不是 0 → 停止回報。

**C-2. 現役管線腳本沒有被寫死數字**
```bash
grep -nE "^\s*(f[1-9]|total_assets|net_income|revenue)_?[a-z0-9]* *= *[0-9]" \
  scripts/fetch_xbrl_financials.py scripts/compute_fundamentals.py \
  scripts/update_thesis_financials.py scripts/fetch_price_history.py
```
預期：**無輸出**。有輸出代表有人又把數字寫死了 → 停止回報。

> ⚠️ 寫死數字的 11 支 `run_*.py` 舊腳本已刪除，現在全庫都該通過這項檢查。

**C-3. 每份 thesis 都有可追溯來源**
```bash
grep -L "financials_accession:" 30_Analysis/*_Master_Investment_Thesis_2026.md
```
預期：**無輸出**（每份都有 accession number）。

**C-4. 抽驗一個數字對得上**
```bash
python3 -c "
import json
f=json.load(open('fundamentals.json'))['companies']['NVDA']
print('F-Score', f['piotroski']['score'], '/', f['piotroski']['max_evaluated'])
print('ROE     ', round(f['dupont']['roe']*100,2), '%')
print('來源    ', f['source_form'], f['source_accession'])
"
```
把輸出跟 `30_Analysis/NVDA_Master_Investment_Thesis_2026.md` 第二章比對，**必須一致**。

**C-5. Sortino 有實際計算窗口**
```bash
grep -h "Sortino Ratio（週資料）" 30_Analysis/*_Master_Investment_Thesis_2026.md | head -4
```
預期：每行不是帶「週報酬」窗口的數值，就是「資料不足」。出現沒有窗口說明的裸數字 → 停止回報。

---

## 5. 已知限制（不是 bug，不要「修」）

| 現象 | 原因 |
|---|---|
| TSM 停在 FY2024 | SEC companyfacts 尚未收錄其 FY2025 20-F。等 SEC 更新，不要手動填 |
| NOK 幣別是 EUR | Nokia 只用歐元 tag，未提供美元。**不准自己換匯** |
| AMZN / GOOGL / META / COHR 毛利率是「資料不足」 | 這些公司不 tag `GrossProfit` |
| Altman Z 高達 60~90 且標「市值主導」 | Altman Z 是為高負債製造業設計的，對輕資產科技股不適用。**這個警語必須保留** |
| 各公司科目數 11~14 不等 | 每家 tag 的科目本來就不同 |

---

## 6. 尚未驗證的區塊（重要）

thesis 的**第四、五章**（估值倍數、DCF 蒙地卡羅）目前**仍是舊版數字，未經來源驗證**。每份 thesis 第二章結尾都有警語標示這件事。

（第三章 Sortino 已於 2026-08-01 改為由 `prices.json` 實際股價計算，屬已驗證。）

- **不准**把這些數字當成已驗證資料引用
- **不准**自行「修正」它們
- 使用者若問起，據實回答：尚未驗證

---

## 7. 什麼時候必須停下來問人

1. 本文件沒有描述的錯誤訊息
2. `git status` 出現預期外的檔案
3. 需要修改任何 `scripts/*.py` 的計算邏輯
4. 需要填寫任何你沒有可靠來源的數字
5. 任何操作連續失敗三次
6. 使用者要求你「估一下」「大概抓一個數字」→ 回覆：本庫規則不允許估算，請提供來源

---

## 附錄：目前追蹤的 14 家公司

`AAPL` `AMZN` `ARM` `COHR` `GOOGL` `INTC` `META` `MRVL` `MSFT` `NOK` `NVDA` `ONDS` `TSLA` `TSM`

腳本清單：

| 腳本 | 用途 |
|---|---|
| `fetch_sec.py` | 下載 10-K / 20-F 原文並產生筆記 |
| `fetch_xbrl_financials.py` | 抓 SEC XBRL 結構化財報 → `financials.json` |
| `compute_fundamentals.py` | 算 F-Score / Altman Z / DuPont → `fundamentals.json` |
| `update_thesis_financials.py` | 更新 thesis 第二、三章 |
| `fetch_price_history.py` | 抓日線收盤價（預設 6 年）→ `prices.json` |
| `macd_analyzer.py` | MACD 計算（獨立工具） |
| `fetch_form8k_events.py` / `fetch_insider_institutional.py` | 8-K 事件與 13F/Form 4（獨立工具） |
