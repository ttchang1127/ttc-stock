# Sec_kb 資料維護 SOP（機械化執行版）

> **這份文件寫給誰**：維護本知識庫的 AI 助理（目前為 Gemini 3.6 Flash）。
> **怎麼用**：找到對應的「任務」章節，**照抄指令、照順序執行、比對預期輸出**。
> **不要自己想辦法。** 遇到本文件沒寫到的狀況，一律停止並回報使用者。
>
> 儀表板網頁的維護請看 [[ttc-stock_Dashboard_維運SOP]]，那是另一條線。
> 還沒完成的事情列在 [[Sec_kb_待辦事項]]，**已決定不做的**則在本文件第 5 節。

最後更新：2026-08-16

---

## 0. 紅線：以下事項絕對禁止

這些不是建議。**每一條都對應本庫真實發生過的錯誤。**

| # | 禁止事項 | 這條規則為什麼存在 |
|---|---|---|
| 1 | **手動輸入、估算、或「合理推測」任何無來源財務數字** | 舊版腳本寫死 `total_assets_2026 = 115000 # approximate`，真實值是 206,803，少報 44%；唯一例外是 `forward_looking_inputs.json` 中逐筆附官方 URL 的管理層指引／分部揭露 |
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
                            ←── risk_changes.json（風險因素年度比對）
   *_report.html（14 份獨立網頁報告）

公司官方 IR／SEC 附件（人工逐筆核對）
        ↓ forward_looking_inputs.json（最近一期；每筆強制附來源 URL 與日期）
        ↓ guidance_history.json（近 3 年；官方指引與後續實績分開追溯）
   管理層指引達標追蹤＋分部／營收來源表 ──→ build_reports.py

> ⚠️ **新增一家公司時，thesis 必須有第一章與第六章**，否則報告頁的
> 「🏛️ 護城河」與「⚠️ 核心風險因素」會印出「本公司尚無…章節」的預設字串。
> AMZN 就是這樣上線的：儀表板與所有量化章節都正常，只有這兩塊是空的。
> 這兩章**不會**被 `update_thesis_financials.py` 更新（它只重寫第二 ~ 五章），
> 所以第六章裡不要抄寫財務數字 —— 資料更新後那些數字會變成沒人會發現的錯值。
> **這條由 C-13 強制執行**，寫進去就過不了檢查。
> 需要引用數字時，寫「見第二節」並讓讀者看腳本重算過的那一份。

20_Filings/*/sections/*Risk_Factors.md
        ↓ diff_risk_factors.py
   risk_changes.json ──→ build_reports.py ←── risk_zh.json（繁中譯文，人類維護）

sec_filing_alerts.json（SEC accession／官方主要文件 URL）
        ↓ ingest_periodic_filings.py（fail-closed；章節邊界不可靠即停止）
   periodic_filing_ingest.json ＋ 60_SEC_Filing_Radar/Periodic_Filing_Ingest.md
        └─→ 20_Filings/<Ticker>/（10-Q／8-K／6-K 主筆記與已驗證章節）
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
| `risk_changes.json` | `diff_risk_factors.py` | ❌ |
| `risk_zh.json` | **人類維護**（風險變化段落的繁中譯文） | ✅ 只能改 `zh` 欄；鍵是原文雜湊，不要手改 |
| **`dcf_assumptions.json`** | **人類維護**（14 家現皆為 `estimate_dcf_inputs.py` 推導值） | ✅ 可維護模型假設；`derived_at` 記錄整批假設推導日 |
| **`forward_looking_inputs.json`** | **人類逐筆核對官方 IR／SEC** | ✅ 只能加入附 `source_url`、`source_date` 的公司指引與分部揭露；禁止填入分析師共識或自行推估 |
| **`guidance_history.json`** | **人類逐期核對官方 IR／SEC** | ✅ 近 3 年指引回測；指引來源與 `quarterly_financials.json` 的實績來源分開，無一致區間者標示不可比較，不得算成未達標 |
| `prices.json` | `fetch_price_history.py`（預設 6 年；含 `^IRX` 無風險利率） | ❌ |
| `20_Filings/**` | `fetch_sec.py`（`--split-sections` 會拆出 Item 1A/1/7 原文） | ❌ |
| thesis 第二 ~ 五章 | `update_thesis_financials.py` | ❌ |
| thesis 第一章（及 AAPL 第六章） | 人類撰寫的敘述 | ⚠️ 只在使用者明確要求時 |

---

## 2. 任務 A：更新全部財務數據

> 🤖 **這件事現在每個交易日自動執行。**
> `.github/workflows/update-prices.yml` 會抓股價與 SEC 財報，
> **只有在 `prices.json` 或 `financials.json` 真的變動時**才重算下游並 commit。
>
> 所以平常你不需要跑任務 A。需要手動跑的情況只有三種：
> 1. 改了任何 `scripts/*.py` 的計算邏輯
> 2. 改了 `dcf_assumptions.json`（機器人不碰這個檔案）
> 3. 排程失敗，要人工補跑
>
> 手動跑的步驟與機器人完全相同，如下。
>
> 排程另會先執行 `check_new_annual_filings.py`。它只比較 SEC 最新 10-K／20-F
> 與 `20_Filings/` 已有 accession，發現新申報時在 Actions 顯示警告，**不下載、不改檔**。

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

例行自動更新允許出現的檔案**只有**：`financials.json`、`fundamentals.json`、`financial_health.json`、`valuation.json`、`*_report.html`、`30_Analysis/*_Master_Investment_Thesis_2026.md`。若本次工作明確是核對管理層指引／分部資料，才可額外出現 `forward_looking_inputs.json`；回溯驗證管理層指引時才可額外出現 `guidance_history.json`。

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

**B-6. 拆解核心章節原文（新增公司時建議一併執行）**
```bash
python3 scripts/fetch_sec.py AMD --years 5 --split-sections
```
預期：每個年度印出 3 行 `[✓] Item_xxx: N 字元`。
出現 `[!] ... 找不到符合的章節範圍` 是**正常**的 —— 代表該份申報的標題格式非標準，
抽取器拒絕輸出可能錯誤的內容。**不要為了讓它「成功」而放寬 `MIN_SECTION_CHARS`。**

---

## 4. 任務 C：驗證資料誠信（每次改動後必跑）

> 🤖 **所有資料誠信檢查現在由一支腳本一次跑完，排程也會跑。**
> ```bash
> python3 scripts/check_integrity.py
> ```
> 預期最後一行 `✅ N 項檢查全部通過`，離開碼 0。任一項失敗離開碼為 1；N 會隨新增防呆檢查增加。
>
> 排程在 commit **之前**執行它，不通過就讓整個 job 失敗，資料不會被推上去。
>
> 下面逐項的說明保留，是為了讓你知道每一項在防什麼、失敗時該怎麼判讀。
> **不要因為某項擋路就把它從腳本裡拿掉** —— C-7a／C-7c／C-10／C-11／C-13 各自對應一個
> 已經 commit、甚至已經上線的真實錯誤。

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

**C-7a. 兩個檔案的有息負債定義一致**
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

**C-7b. 沒有第四支腳本自己算負債**
```bash
python3 -c "
import re, pathlib
# 只有這三支可以直接指名債務科目，各有不可取代的理由。
ALLOWED = {
 'fetch_xbrl_financials.py': 'XBRL 科目對照表，本來就要列出標籤名',
 'compute_financial_health.py': 'total_debt 的實作處；另有 Beneish LVGI 與投入資本需要個別組成',
 'compute_fundamentals.py': 'Piotroski 第 5 項用的是長期負債比，與有息負債總額是不同的指標',
}
CONCEPTS = re.compile(r'[\'\"](long_term_debt|debt_current|bonds_(?:non)?current|finance_lease_\w+|convertible_debt_\w+)[\'\"]')
bad = []
for f in sorted(pathlib.Path('scripts').glob('*.py')):
    src = f.read_text()
    if not CONCEPTS.search(src) or f.name in ALLOWED:
        continue
    bad.append(f.name)
print('自行組裝負債的腳本:', bad or '無')
"
```
預期：`自行組裝負債的腳本: 無`。

出現任何檔名，代表那支腳本在自己加總債務科目，而不是 import
`compute_financial_health.total_debt` → **停止並回報**。

`compute_valuation.py` 與 `estimate_dcf_inputs.py` 都直接 import 共用函式，因此必然一致。

> 🔁 **這個 bug 出現過三次**，每次都是同一個型態：某支腳本自己寫
> `long_term_debt + debt_current`，漏掉公司債與融資租賃。
> 第一次讓 TSM 的淨現金虛報 **$29B** 並直接餵進 DCF；
> 第二次讓 TSM 的資金成本算成 **9.4%（真值 0.8%）**、ONDS 算成 **438%**，兩者都進了 WACC 權重。
> C-7a 只能抓到「有寫檔的兩支」，C-7b 才擋得住第四支。

**C-7c. 兩個檔案的毛利率一致**
```bash
python3 -c "
import json
f=json.load(open('fundamentals.json'))['companies']
h=json.load(open('financial_health.json'))['companies']
bad=[t for t in f if f[t].get('gross_margin')!=h[t]['profitability']['gross_margin']]
print('不一致:', bad or '無')
"
```
預期：`不一致: 無`。

> 🔁 **和 C-7a 是同一個型態**：同一個指標、兩支腳本、兩個答案。
> `compute_fundamentals.py` 在 filer 未標記 `GrossProfit` 時會用「營收 − 銷貨成本」補上，
> `compute_financial_health.py` 卻只在 Beneish 指標內部這樣做。結果 AMZN、GOOGL、META、COHR
> 在 `fundamentals.json` 有毛利率（50.29% / 59.65% / 82.00% / 35.17%），
> 在健全度計分卡上卻是**資料不足**。已改為共用同一個 `gross_profit()`。

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

**C-13. thesis 第六章沒有抄寫會過期的財務數字**
```bash
python3 scripts/check_integrity.py --quiet   # 只印失敗項
```
預期：C-13 不出現。

第六章是人寫的判斷，`update_thesis_financials.py` **只重寫第二 ~ 五章，從不碰第六章**。
所以數字一抄進去就凍在那一天。導入這條檢查時，13 家有 **9 家**的第六章本益比與同一頁第四節不符：

| | 第六章（凍住） | 第四節（腳本重算） |
|---|---|---|
| COHR | 824.2x | **1188.6x** |
| ARM | 283.2x | **333.8x** |
| TSLA | 289.4x | **305.5x** |
| MRVL | 61.1x | **71.2x** |
| NVDA | 41.0x | **45.7x** |
| MSFT | 25.9x | **27.9x** |
| META | 23.7x | **25.2x** |
| AAPL | 41.4x | **42.0x** |
| GOOGL | 33.0x | **32.7x** |

其中 **兩家的結論方向已經相反**，而且都掛在多空判斷上：

- **NVDA** 的「🟢 多頭優勢」寫著「現價 $200.75 較中位數 $313.44 **折價 36.0%**」，
  同一頁第五節寫的是「現價 $223.96 **高於**中位數 47.5%」—— 過期的那個正被當成買進理由。
- **MSFT** 寫著「P/E 25.9x **高於** DCF 保守中位數」，實際現價已略**低於**中位數。

另有 **三家把「現金與短期投資總額」寫成「淨現金」**：
NOK 的 **€54.6 億**實際淨現金只有 **€10.5 億**（有息負債 €44.1 億），差 **5.2 倍**；
ARM 與 ONDS 因幾乎沒有有息負債，誤差小但性質相同。

> 🔁 **這條檢查不比對數值，而是禁止數值出現。**
> 比對數值要維護一份「哪個數字對應哪個欄位」的對照表，那份表本身就會過期。
> 要引用就寫**「見第二節」**，讓讀者看腳本重算過的那一份。
> 年份、製程節點（2nm / 18A）、規格（800G / 1.6T）等不隨財報變動的數字不在此列；
> 需要說明「這裡先前寫錯了什麼」的更正句含「先前寫」三字即可豁免。

**C-9. 網頁報告是產生出來的，不是手改的**
```bash
python3 scripts/build_reports.py && git status --short -- '*_report.html'
```
預期：**無輸出**（剛跑完管線的情況下會有輸出，那是正常的；這項檢查是在 commit 之後再跑一次）。

有輸出代表committed 的報告內容和生成器產生的不一致 —— 也就是有人直接編輯了 `*_report.html`。
**那些編輯下次執行就會消失**，必須改到來源（JSON 由管線產生，質化敘述在 `30_Analysis/` 的 thesis）。

**C-10. 三個檔案的 WACC 一致**
```bash
python3 -c "
import json
a=json.load(open('dcf_assumptions.json'))['companies']
h=json.load(open('financial_health.json'))['companies']
v=json.load(open('valuation.json'))['companies']
bad=[t for t in a if a[t]['wacc'] is not None
     and not (a[t]['wacc']==h[t]['profitability']['wacc']==v[t]['assumptions']['wacc'])]
print('WACC 不一致:', bad or '無')
"
```
預期：`WACC 不一致: 無`。

`dcf_assumptions.json` 被**兩支**腳本讀取：`compute_financial_health.py` 拿它算 ROIC−WACC，
`compute_valuation.py` 拿它做折現。改了假設檔卻只重跑其中一支，兩邊就會各說各話。

> 🔁 **這件事發生過**：2026-08-08 把 8 家的假設換成推導值後只重跑了 valuation，
> 漏跑 `compute_financial_health.py`，導致報告上的 ROIC−WACC 用舊 WACC 算 ——
> NVDA 顯示 +67.0pp（真值 +62.2pp）、AMZN 顯示 +4.9pp（真值 +2.5pp），並已上線。
> **改 `dcf_assumptions.json` 後必須重跑任務 A 的 A-3 ~ A-7 全部，不能只挑一支。**

**C-11. 市值與股數基準合理**
```bash
python3 -c "
import json
f=json.load(open('fundamentals.json'))['companies']
bad=[]
for t,v in f.items():
    mc, rev = v.get('market_cap'), v.get('revenue')
    if mc and rev and mc/rev > 40 and t not in ('ARM','ONDS'):
        bad.append((t, round(mc/rev,1)))
print('市值/營收 異常:', bad or '無')
"
```
預期：`市值/營收 異常: 無`。ARM（IP 授權，高倍數）與 ONDS（營收極小）已知合理，故排除。

出現其他公司代表**股數基準錯了** —— 通常是把普通股股數乘上 ADR 報價。
`compute_fundamentals.py` 的 `ADR_ORDINARY_PER_SHARE` 記錄需要換算的公司。

> 🔁 **這件事發生過**：TSM 的封面股數是 259 億**普通股**，而 `prices.json` 存的是 **ADR 報價**
> （1 ADR = 5 普通股）。兩者相乘得到 **$10.9 兆** 市值 —— 是營收的 123 倍，NVDA 只有 25 倍。
> 那個數字餵進了 Altman Z、WACC 權重與 DCF 每股價值，TSM 的 DCF 中位數因此低報 5 倍
> （$28.07，真值 $142.73）。**是因為使用者問「為什麼 TSM 沒有自由現金流」才連帶查出來的。**

---

## 5. 已知限制（不是 bug，不要「修」）

| 現象 | 原因 |
|---|---|
| companyfacts 落後時會改讀申報自身的 XBRL | TSM 的 FY2025 20-F 在 companyfacts 裡**只有 2 個標籤，零財務科目**，frames API 也是 404 —— 但那份申報本身完整標記，SEC 也渲染了 169 份報表。`fetch_xbrl_financials.py` 會在 companyfacts 落後於 EDGAR 最新年報時，改由該申報的 R 檔取數。**只在落後時啟用，不取代主路徑**，來源記在 `filing_fallback` 欄位 |
| 這條後備路徑必須通過交叉驗證才會合併 | 申報會重述前幾年，那些數字我們已從 companyfacts 取得。解析結果必須與**至少 5 項**比較年度相符才合併，不符就拒絕。TSM 目前是 38 項相符。**不准為了讓它合併而放寬門檻** |
| 解析只讀主要財務報表，不讀附註 | 附註把同樣的概念標在維度下（分部／權益組成／工具別），而解析器讀值不讀 context。曾因此讓附註的遞延所得稅明細覆寫掉資產負債表的值 |
| 符號由比較年度校準 | 渲染報表顯示的是呈現層的值，negated label 會把費用顯示成負數（財務成本顯示 (10,495.4)，底層事實是 +10,495.4）。比較年度同時用來**確定每個科目的符號慣例**，符號不一致的科目一律拒絕 |
| NOK 幣別是 EUR | Nokia 只用歐元 tag，未提供美元。**不准自己換匯** |
| AMZN / GOOGL / META / COHR 有毛利率，但 `gross_margin_basis` 是 `revenue_less_cogs` | 這四家不 tag `GrossProfit`，改以「營收 − 銷貨成本」推導。**這是計算，不是估算**，兩個科目都來自同一份財報 |
| `fundamentals.json` 的 Altman Z 高達 60~90 且標「市值主導」 | 原始 Altman Z 是為高負債製造業設計的，對輕資產科技股不適用。**這個警語必須保留**。改看 `financial_health.json` 的 **Z''**，那才是適用非製造業的版本（門檻 >2.6 安全 / <1.1 危險） |
| Z'' 把 AAPL 從「安全」改判為灰色區 | **不是 bug**。AAPL 流動比率 0.89、負債佔資產 79%、保留盈餘為負（長年回購超過累積保留），原始 Z 用市值當分子把這些蓋掉了 |
| 有息負債是 8 個科目**加總**，不是取其中一個 | TSM 的長期公司債 $28.3B 和長期借款 $1.0B 分開列，只取一個會差一個數量級。組成明細在 `solvency.debt_components` |
| TSM 的有息負債註記可能說「TWD 部分未計入」 | 若某組成只有 TWD 標籤而其餘是 USD，該組成不會被併入。**不准自己換匯**，缺口已在註記中揭露 |
| 某家公司的有息負債是 null | 代表該公司**一個債務標籤都沒有**。**不准當成 0** —— 顯示 0.00 會讓有可轉債的公司看起來零負債 |
| Beneish M-Score 把 NVDA / MRVL / ONDS 標記出來 | **這不是舞弊指控**。M-Score 是 1990 年代以財報型態擬合的篩選模型，高速成長本身就會推高分數（ONDS 營收年增 605%）。`growth_caveat` 欄位會說明。要下任何結論必須人工查證原始財報 |
| TSM 沒有 M-Score | 缺 SGAI（IFRS 下 TSM 未 tag 銷管費用）。**不准用 1.0 代入補齊** —— 那等於宣稱「與去年持平」，但根本沒量到 |
| AAPL 沒有利息保障倍數 | Apple **FY2024 起不再單獨 tag 利息費用**，併入「Other income/(expense), net」。它有 $91.9B 有息負債，這個比率本應適用，屬於真實缺口。**不准用其他科目湊** |
| ARM 利息保障倍數 300x | ARM **沒有任何借款**，唯一利息來自融資租賃（$3M）。倍數高是因為沒有債務，不是償債能力特別強，註記已說明。**不准改用 `InterestIncomeExpenseNonoperatingNet`** —— 那是淨利息**收入** |
| COHR 沒有 ROIC / Z'' / 利息保障倍數 | Coherent **FY2025 起不再 tag `OperatingIncomeLoss`**。已實測「營收 − CostsAndExpenses」不可替代：FY2024 該差額為 **−148M**，而真正的營業利益是 **+96M**（`CostsAndExpenses` 已含利息與業外項目，差額等於稅前淨利）。**這個推導已測試並否決，不要再引入** |
| 報告的護城河章節沒有 SEC 出處 | 護城河一章是**人工撰寫的質化分析**，頁面上已標示。風險章節已接上出處（14/14 皆指向 `20_Filings/*/sections/` 的原文拆解與 SEC 線上檢視器連結），護城河一章沒有對應的單一原文章節，因此不做這件事 |
| 報告出現「本組合第 N / 14」 | 這是**每次產生時重算**的排名，只涵蓋本庫 14 家。**不准改寫成「全美股第 1」之類無法驗證的說法** |
| DCF 中位數與現價差很多（COHR −97%、ARM −94%） | **不是買賣訊號**。超過 ±50% 會自動掛「🚨 中位數不宜當作目標價」，請改看**現價隱含的 FCF 年成長率** —— 那才是可以判斷的陳述（COHR 隱含 65%／十年）。**不准把中位數寫成目標價或「折價 N%」** |
| 基期 FCF 不等於當期 FCF | 預設採**常態化**值（歷年 FCF 利潤率中位數 × 當期營收），以免資本支出高峰年被外推十年。AMZN 當期 $7.7B、常態化 $22.3B。差距超過 15% 時 thesis 會加註 |
| META 的 DCF 中位數高於現價 54% 也被標記 | 門檻是**雙向**的 ±50%。模型高於市價一樣是假設在說話 |
| INTC 與 NOK 走 `LAYOUT_OVERRIDES` 專屬規則 | 這兩家的編排非標準：Intel 的 10-K 本文完全沒有 Item 標題（Item 1B／Item 2 只在文末索引），章節名是自己的「Risk Factors」→「Other Key Information」；Nokia 是年報＋20-F 交叉引用表，且**目錄側欄每頁重印**，只有項目符號能標示當前章節。規則寫在 `fetch_sec.py` 的 `LAYOUT_OVERRIDES`，**只在通用規則失敗時才套用**，不會削弱其他 12 家的保護 |
| INTC／NOK 只有最新年度抽得出來 | 它們前幾年的版面又不一樣。報告只用最新年度，**不要為了補齊舊年度而放寬規則** |
| INTC 的 Item 1 Business 與 Item 7 MD&A 仍然失敗 | 刻意的。用同樣手法可以抓到 MD&A，但七份裡有六份起頭落在目錄、長度衝到 25 萬字元。**寧可沒有，也不要掛著正確標題的錯誤內容** |
| AAPL 章節拆解從 10 年變成 6 年 | 舊版 50 檔是早期腳本產生的，邊界切在交叉引用中間、HTML 實體沒解碼。2016–2019 的舊版式抽不出乾淨邊界，已捨棄。**少而正確優於多而錯誤** |
| MSFT 拆解檔裡寫著「RIS K FACTORS」 | 那是 SEC 原文就長這樣（Microsoft 的排版在字中插入空格）。**這是原文，不准修飾** |
| `dcf_assumptions.json` 的值不會自動更新 | **這是刻意的**。報告與儀表板會顯示 `derived_at` 距今多久，超過 `stale_after_days`（目前 90 天）轉為提醒，但不會自動重推。要更新就跑 `estimate_dcf_inputs.py`，採用後同步更新 `derived_at` 與 note 日期 |
| 換成推導值後 NVDA 的 DCF 從 +39% 變 −32% | **不是 bug**。原本手填的 WACC 9.5% 對 beta 2.14 的公司過低；推導值 14.4% 把估值砍半。先前 8 家手填 WACC 全部落在 8.5%~10.5%，**無一例外低於 CAPM 值** |
| META 的 DCF 高於現價 62% | 成長率用該公司自己的營收 CAGR 18.5%，而市場隱含只有 11.8%。這是模型與市場的真實分歧，已由 ±50% 門檻標記。**不准為了讓它落在區間內而回頭調整 g 或 WACC** |
| 機器人的 commit 現在有 20 幾個檔案 | **這是修好的行為**。它以前只 commit `prices.json`，導致所有衍生資料（市值、Altman Z、DCF、Sortino、報告股價）停在人類上次手動跑管線的時間。2026-08-04 與 08-05 都發生過股價更新但報告顯示舊值 |
| 機器人不更新 `dcf_assumptions.json` | **刻意的**。g 與 WACC 雖然是推導值，但要不要重新推導是判斷。workflow 的檔案守門會在它出現時**直接讓 job 失敗** |
| 週末與假日沒有機器人 commit | 正常。兩支抓取程式在資料沒動時都不寫檔，gate 就會擋下整個下游 |
| workflow 檔名還叫 `update-prices.yml` | GitHub 用**路徑**綁定排程，改檔名會讓這條 cron 退休、重新註冊一條新的。名字過時了，但排程比較值錢 |
| TSM 與 NOK 的 EPS 用流通股數而非稀釋股數 | 兩家在 IFRS 下都不 tag 稀釋股數。`eps_shares_basis` 欄位會註明用了哪一種 |
| ONDS 的 EPS 用流通股數 | 它的稀釋股數標籤是 221,769，真實流通股 4.96 億，差 2,235 倍。市值本來就已改用封面數，EPS 先前漏改，曾顯示 **−$596.27**（真值 −$0.27） |
| NOK 的資本支出含無形資產 | Nokia 的標籤是 PP&E ＋ 無形資產（不含商譽）＋ 投資性不動產的合計，比純 CapEx 廣，因此其 FCF 是較保守的一種定義 |
| 風險比對只在 `fetch_sec.py` 抓了新申報後才需要重跑 | 排程不跑它 —— 股價變動不會改變風險章節。抓了新年度的原文後執行 `python3 scripts/diff_risk_factors.py` |
| 抓了新申報後，風險變化會出現「尚未翻譯」 | **這是設計，不是錯誤**。譯文以原文摘錄的雜湊為鍵，新段落自然沒有譯文，頁面顯示原文並標示。執行 `python3 scripts/list_untranslated.py` 取得待翻清單，補進 `risk_zh.json` 後重跑 `build_reports.py`。**不要為了消除標示而改用機器直譯或刪掉該段** |
| 中文譯文只涵蓋每段開頭（約 320 字元） | 頁面顯示的本來就是段落開頭；每段都附「原文」可展開，且展開的是**完整段落**，不是被截斷的那一段。判讀以原文為準 |
| INTC／NOK／TSM 顯示「無法比對」 | 它們只有一個年度的原文拆解（其餘年度版面不同、抽取器拒絕輸出）。**不要為了湊出比對而放寬抽取規則** |
| COHR 的新增／刪除數特別高（39／72） | 它把整個風險章節重編了（段落 145→109）。文字比對在大幅重組時會把改寫判成一增一刪。**這是方法的已知限制，報告上已標明「這是文字比對，不是語意比對」** |
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

**14 家的假設目前全部有值**，皆由 `estimate_dcf_inputs.py` 於 2026-08-08 推導
（先前 AAPL、ARM、COHR、INTC、MRVL、NOK 六家為 null 的狀態已不存在）。

`INTC` 與 `ONDS` 的 DCF 仍顯示「未計算」，原因是**淨利為負、EPS 與模型不適用**，
不是假設缺漏。這是正確狀態，**不准自行填入數字讓它「看起來完整」**。

> ⚠️ 假設有值不等於假設是新的。這組值不會自動更新；報告與儀表板依
> `derived_at` 顯示距今多久，超過 90 天只提醒，由人決定是否重新推導。

---

## 7. 什麼時候必須停下來問人

### 外接磁碟上的 Git ref 污染

若 `git fetch`／`git pull` 出現 `bad object refs/codex/.../Icon?`，是 macOS Finder
把自訂資料夾圖示的空白 `Icon\r` 檔寫進 `.git/refs`，不是遠端缺 object。執行：

```bash
python3 scripts/configure_local_git.py
git fetch --dry-run origin main
```

清理器只移除 `.git/refs` 底下名稱精確為 `Icon\r` 且大小為 0 的檔案，並在本機設定
`fetch.hideRefs=refs/codex`，讓之後即使 Finder 再建立同類檔案也不會阻斷 fetch／pull。
可用 `python3 scripts/configure_local_git.py --check` 做唯讀檢查。不要手動刪除整個
`.git/refs/codex`，其中仍有 Codex checkpoint 使用的有效 refs。

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
| `fetch_sec.py` | 下載 10-K / 20-F 原文、拆解核心章節 → `20_Filings/*/sections/` |
| `fetch_xbrl_financials.py` | 抓 SEC XBRL 結構化財報 → `financials.json` |
| `compute_fundamentals.py` | 算 F-Score / Altman Z / DuPont → `fundamentals.json` |
| `compute_financial_health.py` | 算流動性 / 償債 / ROIC−WACC / Altman Z'' → `financial_health.json` |
| `estimate_dcf_inputs.py` | 由 beta／Rf／Kd／營收 CAGR 推導 g 與 WACC（**只印出，不寫檔**） |
| `check_new_annual_filings.py` | 比對 SEC 最新 10-K／20-F 與本地 accession（**只通知，不寫檔**） |
| `watch_sec_filings.py` | 台北時間週二至週六中午比對 14 家 SEC accession，更新每日雷達並由 GitHub Issue 通知 |
| `ingest_periodic_filings.py` | 依 accession 下載 10-Q／8-K／6-K 官方主要文件；安全拆分 10-Q MD&A／Controls／Risk Factors 與 8-K SEC Item；重解析失敗會移除該 accession 的舊版現役筆記，避免狀態顯示失敗但頁面仍殘留舊內容 |
| `configure_local_git.py` | 清除 `.git/refs` 內 0-byte Finder `Icon\r` 非法 ref，並設定 `fetch.hideRefs=refs/codex`，避免外接磁碟上的 macOS 圖示 metadata 阻斷 fetch／pull |
| `sec_specialized_radars.py` | 產生最新 10-Q 到件表、解析 Form 4 Ownership XML、依募資文件內文判別 ATM／股權／可轉債／一般債券／架上註冊 |
| `sec_advanced_radars.py` | 產生財報附註／附件、UPLOAD／CORRESP、13D／13G、DEF 14A、Form 144＋3／4／5、併購與 SEC 執法／停牌雷達；結果依 accession 快取 |
| `sec_13f_stock_radar.py` | 掃描 SEC 最新兩期完整 13F 資料集，以 14 家股票為主體彙總機構家數、股數、季變化與前大持有人；每月 20 日檢查新資料集 |
| `compute_valuation.py` | 算本益比 / 淨現金 / DCF 蒙地卡羅 / 隱含成長率 → `valuation.json` |
| `diff_risk_factors.py` | 比對風險因素的年度變化 → `risk_changes.json` |
| `risk_translations.py` | 譯文的摘錄／雜湊／查找（被 `build_reports.py` 引用，不單獨執行） |
| `list_untranslated.py` | 列出 `risk_zh.json` 還缺哪些段落的譯文 |
| `build_reports.py` | 由 JSON ＋ thesis 質化章節產生 14 份 `*_report.html` |
| `update_thesis_financials.py` | 更新 thesis 第二 ~ 五章 |
| `fetch_price_history.py` | 抓日線收盤價（預設 6 年）→ `prices.json` |
| `macd_analyzer.py` | MACD 計算（獨立工具） |
| `fetch_form8k_events.py` / `fetch_insider_institutional.py` | 8-K 事件與 13F/Form 4（獨立工具） |

SEC 進階雷達資料口徑：

- 公司申報流每個美國工作日後於台北時間中午檢查；狀態檔 schema 升級時，新表單先建基準而不回頭誤報。
- 13D／13G 用 SEC EFTS 回填近 3 年，因申報人是外部大股東，不只依賴發行公司 submissions feed。
- 13F 是季度、最晚可落後季底 45 天；`VALUE` 自 2023-01-03 起單位為整數美元，不可再乘 1,000。
- UPLOAD／CORRESP 公開時通常已距審閱結束至少 20 個工作日，不得畫成即時 SEC 執法。
- 關鍵字命中只是閱讀導航；重大內控缺失／重述需用正向除錯句型，不可把審計範本的「評估是否存在」當成公司已發生。
