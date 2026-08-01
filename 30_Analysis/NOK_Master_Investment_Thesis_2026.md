---
ticker: NOK
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/nok
  - valuation
  - portfolio
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2025-12-31
financials_accession: "0001628280-26-015034"
financials_verified: true
---

# Nokia Corporation (NOK) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K / 20-F 官方財報**、**DCF 蒙地卡羅 10,000 次機率模型**、**Sortino 下行風險管理**、**四大基本面量化模型 (Piotroski F-Score / Altman Z-Score / DuPont)** 與 **護城河產業分析**。

---

## 🏛️ 一、 公司概況與經濟護城河 (Wide Economic Moat)

- **核心業務與產業地位**: 寬廣護城河 (全球 5G/6G 電信網絡基礎設施雙寡頭、貝爾實驗室專利組合)
- **標籤與投資亮點**: `5G/6G 網絡與低 P/E 防禦股`

---

## 📊 二、 財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2025-12-31**（20-F，申報日 2026-03-05，accession `0001628280-26-015034`）。幣別：EUR。

### 損益與現金流
- **營收 (Revenue)**: **€19,889 百萬**
- **淨利 (Net Income)**: **€660 百萬**
- **毛利率 (Gross Margin)**: **43.54%**
- **經營現金流 (OCF)**: **€2,071 百萬**
- **資本支出 (CapEx)**: 資料不足
- **自由現金流 (FCF = OCF − CapEx)**: 資料不足

### 資產負債表
- **總資產**: **€37,597 百萬**
- **總負債**: **€16,539 百萬**
- **股東權益**: **€21,058 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **4 / 7**（2 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ❌ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ⬜ 長期負債比下降 ｜ ❌ 流動比率提升 ｜ ⬜ 股數未增加 ｜ ❌ 毛利率提升 ｜ ✅ 資產週轉率提升
- **Altman Z-Score**: **2.76**（grey 區）
- **DuPont ROE**: **3.13%**（淨利率 **3.32%** × 資產週轉率 **0.529x** × 權益乘數 **1.785x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **3.13%**

---

## 📈 三、 下行風險與二級市場波動 (Sortino Ratio)

> 📌 由 `prices.json` 的實際日線收盤價計算：先取每週最後收盤算週報酬，下行標準差只計入低於門檻報酬率 (MAR = 0) 的週次，再以 `平均週報酬 × 52 ÷ (下行標準差 × √52)` 年化。股價資料擷取於 2026-08-01。

- **近 3 年 Sortino Ratio（週資料）**: **1.52**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **0.61**　（2021-08-06 ~ 2026-07-31，260 週報酬）

---

## 💵 四、 估值比率與乘數分析 (P/E & Multiples)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 €9.14。

- **稀釋每股盈餘 (EPS)**: 資料不足
- **本益比 (P/E)**: 資料不足
- **現金與短期投資**: **€5,462 百萬**
- **總債務（長期＋一年內到期）**: **€0 百萬**
- **淨現金 (Net Cash)**: **€5,462 百萬**
- **庫藏股回購**: **€624 百萬**　→ 回購殖利率 **1.19%**
- **現金股利**: **€759 百萬**　→ 股利殖利率 **1.45%**
- **股東總殖利率 (Shareholder Yield)**: **2.63%**

---

## 🎲 五、 DCF 蒙地卡羅估值模擬（假設未設定）

> ⚠️ **本節未計算**：假設未設定。

DCF 需要成長率 (g) 與折現率 (WACC)，兩者皆為判斷而非可從 SEC 推導的事實，因此必須由人填入 `dcf_assumptions.json`。

---

## 🔗 關聯筆記
- [[NOK_Company_Profile|Nokia Corporation 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[GOOGL_Master_Investment_Thesis_2026|Alphabet / Google 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
