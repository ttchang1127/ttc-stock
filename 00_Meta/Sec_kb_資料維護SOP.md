# Sec_kb 資料維護 SOP（機械化執行版）

> **這份文件寫給誰**：維護本知識庫的 AI 助理（目前為 Gemini 3.6 Flash）。
> **怎麼用**：找到對應的「任務」章節，**照抄指令、照順序執行、比對預期輸出**。
> **不要自己想辦法。** 遇到本文件沒寫到的狀況，一律停止並回報使用者。
>
> 儀表板網頁的維護請看 [[ttc-stock_Dashboard_維運SOP]]，那是另一條線。

最後更新：2026-08-08

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
        ├─ compute_financial_health.py ←── dcf_assumptions.json（取 WACC）
        │    financial_health.json
        ↓ compute_valuation.py  ←── dcf_assumptions.json（人類維護）
   valuation.json
        ↓ update_thesis_financials.py
   30_Analysis/*_Master_Investment_Thesis_2026.md 的第二 ~ 五章
        ↓ build_reports.py  ←── thesis 第一/六章（人工撰寫的質化敘述）
   *_report.html（14 份獨立網頁報告）
```

這七支腳本必須**照這個順序**執行，後面的依賴前面的產出。
`compute_financial_health.py` 和 `compute_valuation.py` 都只依賴 `fundamentals.json`，
彼此不相依，先跑哪個都可以。

| 檔案 | 由誰產生 | 你可以改嗎 |
|---|---|---|
| `financials.json` | `fetch_xbrl_financials.py` | ❌ |
| `fundamentals.json` | `compute_fundamentals.py` | ❌ |
| `financial_health.json` | `compute_financial_health.py` | ❌ |
| `valuation.json` | `compute_valuation.py` | ❌ |
| `*_report.html` | `build_reports.py` | ❌ **不准手改**，改了下次產生就被蓋掉 |
| **`dcf_assumptions.json`** | **人類維護** | ✅ **這是唯一允許手填數字的檔案** |
| `prices.json` | `fetch_price_history.py`（預設 6 年；含 `^IRX` 無風險利率） | ❌ |
| `20_Filings/**` | `fetch_sec.py` | ❌ |
| thesis 第二 ~ 五章 | `update_thesis_financials.py` | ❌ |
| thesis 第一章（及 AAPL 第六章） | 人類撰寫的敘述 | ⚠️ 只在使用者明確要求時 |

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

**A-4. 計算財務健全度**
```bash
python3 scripts/compute_financial_health.py
```
預期：一張表格，最後 `Wrote financial_health.json (14 companies)`

最右欄是警示數。`—` 代表沒有指標超過門檻；`資料不足 n/11` 代表**檢查本身沒跑完**，
不等於健全，兩者不可混為一談。

**A-5. 計算估值**
```bash
python3 scripts/compute_valuation.py
```
預期：一張表格，最後 `Wrote valuation.json (14 companies)`

**A-6. 更新 thesis 第二 ~ 五章**
```bash
python3 scripts/update_thesis_financials.py
```
預期：`已更新 14 份 thesis`

**A-7. 產生 14 份網頁報告**
```bash
python3 scripts/build_reports.py
```
預期：14 行，最後 `N / 14 份報告有變更並已寫入`。**沒有數字變動時 N 會是 0，這是正常的。**

若印出「⚠️ N 處無法驗證的宣稱」，代表 thesis 的第一或第六章寫了本庫資料無法佐證的說法
（如「全美股第 1」）。報告會**原樣呈現**，請到 `30_Analysis/` 對應的 thesis 修正措辭，
不要改 `*_report.html`。

**A-8. 確認只有該動的檔案被動到**
```bash
git status --short
```

允許出現的檔案**只有**：`financials.json`、`fundamentals.json`、`financial_health.json`、`valuation.json`、`*_report.html`、`30_Analysis/*_Master_Investment_Thesis_2026.md`

出現任何其他檔案 → **停止並回報**。

**A-9. 送出**
```bash
git add financials.json fundamentals.json financial_health.json valuation.json *_report.html 30_Analysis/ && git commit -m "chore: refresh SEC financials" && git push origin main
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

**B-3. 在 `dcf_assumptions.json` 的 companies 加入該代號（growth / wacc 可先填 null）**

**B-4. 重跑任務 A 的 A-2 ~ A-7**

**B-5.** 若使用者要求也加進儀表板表格，回覆：
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

**C-6. 財務健全度沒有把「資料不足」講成「健全」**
```bash
python3 -c "
import json
d=json.load(open('financial_health.json'))['companies']
for t in sorted(d):
    c=d[t]['coverage']
    if not d[t]['flags'] and not c['sufficient']:
        print(t, '無警示但只算出', c['computed'], '/', c['total'], '→ 必須標示資料不足')
"
```
預期：COHR 那一行會出現，這是**正確**的（它缺 ROIC / Z'' / 利息保障倍數）。
若某家公司在報告或對話中被描述成「財務健全」而它其實落在這份清單裡 → **停止並更正**。

**C-7. 兩個檔案的有息負債定義一致**
```bash
python3 -c "
import json
v=json.load(open('valuation.json'))['companies']
h=json.load(open('financial_health.json'))['companies']
bad=[t for t in v if h[t]['solvency']['total_debt'] is not None
     and v[t]['multiples']['total_debt']!=h[t]['solvency']['total_debt']]
print('不一致:', bad or '無')
"
```
預期：`不一致: 無`。

`compute_valuation.py` 直接 import `compute_financial_health.total_debt`，兩邊必然相同。
若這裡出現公司名單，代表有人把其中一支改成自己算負債了 → **停止並回報**。
（歷史：這兩支曾經各算各的，TSM 的淨現金因此虛報 $29B，並直接餵進 DCF。）

**C-8. 每個算不出來的指標都有說明**
```bash
python3 -c "
import json
d=json.load(open('financial_health.json'))['companies']
bad=[]
for t,v in d.items():
    s=v['solvency']
    if s['interest_coverage'] is None and not s['interest_coverage_note']: bad.append((t,'利息保障倍數'))
    if s['total_debt'] is None and not s['total_debt_note']: bad.append((t,'有息負債'))
    if v['profitability']['roic'] is None and not v['profitability']['roic_note']: bad.append((t,'ROIC'))
print('缺說明:', bad or '無')
"
```
預期：`缺說明: 無`。出現任何項目代表有 null 沒有交代原因 → **停止並回報**。

本庫的規則是「缺就是缺」，但**光是 null 還不夠** —— 讀者必須看得出是「這家公司沒有這件事」
還是「SEC 沒有這個標籤」。這兩者的處理方式完全不同。

**C-9. 網頁報告是產生出來的，不是手改的**
```bash
python3 scripts/build_reports.py && git status --short -- '*_report.html'
```
預期：**無輸出**（剛跑完管線的情況下會有輸出，那是正常的；這項檢查是在 commit 之後再跑一次）。

有輸出代表committed 的報告內容和生成器產生的不一致 —— 也就是有人直接編輯了 `*_report.html`。
**那些編輯下次執行就會消失**，必須改到來源（JSON 由管線產生，質化敘述在 `30_Analysis/` 的 thesis）。

---

## 5. 已知限制（不是 bug，不要「修」）

| 現象 | 原因 |
|---|---|
| TSM 停在 FY2024 | TSM 已於 2026-04-16 申報 FY2025 20-F，但該份在 SEC companyfacts 裡**只有封面股數一個標籤，零財務科目**。不是抓取程式的問題，等 SEC 更新，不要手動填。`financial_health.json` 會自動掛上「資料新鮮度」警示（門檻 15 個月） |
| NOK 幣別是 EUR | Nokia 只用歐元 tag，未提供美元。**不准自己換匯** |
| AMZN / GOOGL / META / COHR 有毛利率，但 `gross_margin_basis` 是 `revenue_less_cogs` | 這四家不 tag `GrossProfit`，改以「營收 − 銷貨成本」推導。**這是計算，不是估算**，兩個科目都來自同一份財報 |
| `fundamentals.json` 的 Altman Z 高達 60~90 且標「市值主導」 | 原始 Altman Z 是為高負債製造業設計的，對輕資產科技股不適用。**這個警語必須保留**。改看 `financial_health.json` 的 **Z''**，那才是適用非製造業的版本（門檻 >2.6 安全 / <1.1 危險） |
| Z'' 把 AAPL 從「安全」改判為灰色區 | **不是 bug**。AAPL 流動比率 0.89、負債佔資產 79%、保留盈餘為負（長年回購超過累積保留），原始 Z 用市值當分子把這些蓋掉了 |
| 有息負債是 8 個科目**加總**，不是取其中一個 | TSM 的長期公司債 $28.3B 和長期借款 $1.0B 分開列，只取一個會差一個數量級。組成明細在 `solvency.debt_components` |
| TSM 的有息負債註記說「TWD 部分未計入」 | TSM 的一年內到期公司債只有 TWD 標籤，其餘資產負債表是 USD。**不准自己換匯併進去**，低估約 $1.8B 已在註記中揭露 |
| 某家公司的有息負債是 null | 代表該公司**一個債務標籤都沒有**。**不准當成 0** —— 顯示 0.00 會讓有可轉債的公司看起來零負債 |
| Beneish M-Score 把 NVDA / MRVL / ONDS 標記出來 | **這不是舞弊指控**。M-Score 是 1990 年代以財報型態擬合的篩選模型，高速成長本身就會推高分數（ONDS 營收年增 605%）。`growth_caveat` 欄位會說明。要下任何結論必須人工查證原始財報 |
| TSM 沒有 M-Score | 缺 SGAI（IFRS 下 TSM 未 tag 銷管費用）。**不准用 1.0 代入補齊** —— 那等於宣稱「與去年持平」，但根本沒量到 |
| AAPL 沒有利息保障倍數 | Apple **FY2024 起不再單獨 tag 利息費用**，併入「Other income/(expense), net」。它有 $91.9B 有息負債，這個比率本應適用，屬於真實缺口。**不准用其他科目湊** |
| ARM 利息保障倍數 300x | ARM **沒有任何借款**，唯一利息來自融資租賃（$3M）。倍數高是因為沒有債務，不是償債能力特別強，註記已說明。**不准改用 `InterestIncomeExpenseNonoperatingNet`** —— 那是淨利息**收入** |
| COHR 沒有 ROIC / Z'' / 利息保障倍數 | Coherent **FY2025 起不再 tag `OperatingIncomeLoss`**。已實測「營收 − CostsAndExpenses」不可替代：FY2024 該差額為 **−148M**，而真正的營業利益是 **+96M**（`CostsAndExpenses` 已含利息與業外項目，差額等於稅前淨利）。**這個推導已測試並否決，不要再引入** |
| 報告的護城河／風險章節沒有 SEC 出處 | 這兩章是**人工撰寫的質化分析**，頁面上已標示。`20_Filings/*/sections/` 有 10-K 原文拆解，但目前只有 AAPL 與 NVDA 有，且尚未接上生成器 |
| 報告出現「本組合第 N / 14」 | 這是**每次產生時重算**的排名，只涵蓋本庫 14 家。**不准改寫成「全美股第 1」之類無法驗證的說法** |
| DCF 中位數與現價差很多（COHR −97%、ARM −94%） | **不是買賣訊號**。超過 ±50% 會自動掛「🚨 中位數不宜當作目標價」，請改看**現價隱含的 FCF 年成長率** —— 那才是可以判斷的陳述（COHR 隱含 65%／十年）。**不准把中位數寫成目標價或「折價 N%」** |
| 基期 FCF 不等於當期 FCF | 預設採**常態化**值（歷年 FCF 利潤率中位數 × 當期營收），以免資本支出高峰年被外推十年。AMZN 當期 $7.7B、常態化 $22.3B。差距超過 15% 時 thesis 會加註 |
| META 的 DCF 中位數高於現價 54% 也被標記 | 門檻是**雙向**的 ±50%。模型高於市價一樣是假設在說話 |
| 三個 Sortino 數值差很多 | **正常**。頻率（週/日）、期間（3年/5年/1年）、MAR 都不同，衡量的是不同的東西，**不准「統一」它們** |
| 12 個月那組用 MAR=0 而非無風險利率 | 實測對照 PortfoliosLab 公布值決定的（NVDA 0.76→0.75、TSLA 0.36→0.36）。改成無風險利率就對不上公開網站 |
| 各公司科目數 11~14 不等 | 每家 tag 的科目本來就不同 |

---

## 6. 尚未驗證的區塊（重要）

第二 ~ 五章**全部由腳本產生**，來源可追溯。但要分清楚兩種數字的性質：

| 章節 | 性質 |
|---|---|
| 二、三、四 | **事實** —— 由 SEC 財報與實際股價算出，可驗證 |
| 五（DCF） | **在特定假設下的推估** —— 依賴 `dcf_assumptions.json` 的 g 與 WACC |

DCF 不是事實。使用者若問「這檔值多少錢」，正確回答是：
> 在 `dcf_assumptions.json` 目前設定的 g=X%、WACC=Y% 之下，中位數為 $Z。改變假設會改變結論。

目前 **AAPL、ARM、COHR、INTC、MRVL、NOK 六家的假設為 null**，其第五章顯示「假設未設定」。
這是正確狀態，**不准自行填入數字讓它「看起來完整」** —— 要填必須由使用者決定並說明依據。

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
| `compute_financial_health.py` | 算流動性 / 償債 / ROIC−WACC / Altman Z'' → `financial_health.json` |
| `compute_valuation.py` | 算本益比 / 淨現金 / DCF 蒙地卡羅 / 隱含成長率 → `valuation.json` |
| `build_reports.py` | 由 JSON ＋ thesis 質化章節產生 14 份 `*_report.html` |
| `update_thesis_financials.py` | 更新 thesis 第二 ~ 五章 |
| `fetch_price_history.py` | 抓日線收盤價（預設 6 年）→ `prices.json` |
| `macd_analyzer.py` | MACD 計算（獨立工具） |
| `fetch_form8k_events.py` / `fetch_insider_institutional.py` | 8-K 事件與 13F/Form 4（獨立工具） |
