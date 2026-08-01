---
ticker: COHR
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/cohr
  - valuation
  - portfolio
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2025-06-30
financials_accession: "0000820318-25-000014"
financials_verified: true
---

# Coherent Corp. (COHR) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K / 20-F 官方財報**、**DCF 蒙地卡羅 10,000 次機率模型**、**Sortino 下行風險管理**、**四大基本面量化模型 (Piotroski F-Score / Altman Z-Score / DuPont)** 與 **護城河產業分析**。

---

## 🏛️ 一、 公司概況與經濟護城河 (Wide Economic Moat)

- **核心業務與產業地位**: 寬廣護城河 (800G/1.6T 光收發模組 800G Optical Transceivers 壟斷霸主、SiC 碳化矽)
- **標籤與投資亮點**: `AI 資料中心光通訊龍頭`

---

## 📊 二、 財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2025-06-30**（10-K，申報日 2025-08-15，accession `0000820318-25-000014`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$5,810 百萬**
- **淨利 (Net Income)**: **$49 百萬**
- **毛利率 (Gross Margin)**: 資料不足
- **經營現金流 (OCF)**: **$634 百萬**
- **資本支出 (CapEx)**: **$441 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$193 百萬**

### 資產負債表
- **總資產**: **$14,911 百萬**
- **總負債**: **$6,430 百萬**
- **股東權益**: **$5,645 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **6 / 8**（1 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ✅ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ✅ 長期負債比下降 ｜ ❌ 流動比率提升 ｜ ❌ 股數未增加 ｜ ⬜ 毛利率提升 ｜ ✅ 資產週轉率提升
- **Altman Z-Score**: 資料不足（缺 X3）
- **DuPont ROE**: **0.87%**（淨利率 **0.85%** × 資產週轉率 **0.390x** × 權益乘數 **2.642x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **0.87%**

---

## 📈 三、 下行風險與二級市場波動 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-01。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **1.93**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **1.18**　（2021-08-06 ~ 2026-07-31，260 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **2.26**　（2025-07-31 ~ 2026-07-31，251 個交易日）
  - 若改以無風險利率為門檻（3.71%，^IRX 13週美國國庫券，期間平均）則為 **2.19**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與乘數分析 (P/E & Multiples)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 $262.89。

- **稀釋每股盈餘 (EPS)**: **$0.32**
- **本益比 (P/E)**: **824.2x**
- **現金與短期投資**: **$909 百萬**
- **總債務（長期＋一年內到期）**: **$3,687 百萬**
- **淨現金 (Net Cash)**: **$-2,778 百萬**
- **庫藏股回購**: 資料不足　→ 回購殖利率 資料不足
- **現金股利**: 資料不足　→ 股利殖利率 資料不足
- **股東總殖利率 (Shareholder Yield)**: 資料不足

---

## 🎲 五、 DCF 蒙地卡羅估值模擬（假設未設定）

> ⚠️ **本節未計算**：假設未設定。

DCF 需要成長率 (g) 與折現率 (WACC)，兩者皆為判斷而非可從 SEC 推導的事實，因此必須由人填入 `dcf_assumptions.json`。

---

## 🔗 關聯筆記
- [[COHR_Company_Profile|Coherent Corp. 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[GOOGL_Master_Investment_Thesis_2026|Alphabet / Google 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
