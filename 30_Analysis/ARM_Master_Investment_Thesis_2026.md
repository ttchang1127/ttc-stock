---
ticker: ARM
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/arm
  - valuation
  - portfolio
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2026-03-31
financials_accession: "0001973239-26-000097"
financials_verified: true
---

# Arm Holdings plc (ARM) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K / 20-F 官方財報**、**DCF 蒙地卡羅 10,000 次機率模型**、**Sortino 下行風險管理**、**四大基本面量化模型 (Piotroski F-Score / Altman Z-Score / DuPont)** 與 **護城河產業分析**。

---

## 🏛️ 一、 公司概況與經濟護城河 (Wide Economic Moat)

- **核心業務與產業地位**: 壟斷級護城河 (v9 架構、全球 99% 智慧型手機 CPU IP 壟斷、CSS 客製晶片版稅升級)
- **標籤與投資亮點**: `IP 毛利率冠軍 (95.2%)`

---

## 📊 二、 財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2026-03-31**（20-F，申報日 2026-05-26，accession `0001973239-26-000097`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$4,920 百萬**
- **淨利 (Net Income)**: **$904 百萬**
- **毛利率 (Gross Margin)**: **97.54%**
- **經營現金流 (OCF)**: **$1,524 百萬**
- **資本支出 (CapEx)**: **$545 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$979 百萬**

### 資產負債表
- **總資產**: **$10,703 百萬**
- **總負債**: **$2,417 百萬**
- **股東權益**: **$8,286 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **6 / 8**（1 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ❌ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ⬜ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ❌ 股數未增加 ｜ ✅ 毛利率提升 ｜ ✅ 資產週轉率提升
- **Altman Z-Score**: **65.21**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 97%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **10.91%**（淨利率 **18.37%** × 資產週轉率 **0.460x** × 權益乘數 **1.292x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **10.91%**

---

## 📈 三、 下行風險與二級市場波動 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-01。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **1.75**　（2023-09-15 ~ 2026-07-31，150 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: 資料不足（股價歷史不足 5 年，僅 151 週，起始 2023-09-15）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **1.80**　（2025-07-31 ~ 2026-07-31，251 個交易日）
  - 若改以無風險利率為門檻（3.71%，^IRX 13週美國國庫券，期間平均）則為 **1.71**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與乘數分析 (P/E & Multiples)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 $239.69。

- **稀釋每股盈餘 (EPS)**: **$0.85**
- **本益比 (P/E)**: **283.2x**
- **現金與短期投資**: **$3,601 百萬**
- **總債務（長期＋一年內到期）**: **$0 百萬**
- **淨現金 (Net Cash)**: **$3,601 百萬**
- **庫藏股回購**: 資料不足　→ 回購殖利率 資料不足
- **現金股利**: 資料不足　→ 股利殖利率 資料不足
- **股東總殖利率 (Shareholder Yield)**: 資料不足

---

## 🎲 五、 DCF 蒙地卡羅估值模擬（假設未設定）

> ⚠️ **本節未計算**：假設未設定。

DCF 需要成長率 (g) 與折現率 (WACC)，兩者皆為判斷而非可從 SEC 推導的事實，因此必須由人填入 `dcf_assumptions.json`。

---

## 🔗 關聯筆記
- [[ARM_Company_Profile|Arm Holdings plc 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[GOOGL_Master_Investment_Thesis_2026|Alphabet / Google 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
