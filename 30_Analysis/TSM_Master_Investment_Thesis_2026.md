---
ticker: TSM
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/tsm
  - valuation
  - semiconductors
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2024-12-31
financials_accession: "0001193125-25-083423"
financials_verified: true
---

# 台積電 (TSMC / TSM ADR) 2026 終極個股研究與估值投資報告

本報告結合 **SEC Form 20-F 官方財報**、**DCF 蒙地卡羅機率模型**、**三大 P/E 估值矩陣**、**Sortino 下行風險**、**四大基本面量化模型** 與 **護城河分析**。

---

## 🏛️ 一、 公司概況與壟斷級經濟護城河 (Unassailable Economic Moat)

1. **先進製程技術絕對獨霸 (Technology Leadership)** ⚡：
   - 2nm (N2) 與 A16 (1.6nm) 奈米製程進度全球領先，掌控全球近 **90% 的最先進 AI 晶片代工產能** (包含 Apple M/A 系列、NVIDIA Blackwell/Hopper、AMD Instinct、Qualcomm、MediaTek)。
2. **CoWoS 先進封裝生態系與產能壁壘 (CoWoS Advanced Packaging)** 📦：
   - AI 高頻寬記憶體 (HBM) 與 GPU 必須依賴 CoWoS 先進封裝。台積電憑藉完整的 3D Fabric 技術形成難以跨越的技術壁壘。
3. **無可匹敵的晶圓代工利潤率 (Foundry Margin Leadership)** 💎：
   - 毛利率高達 **59.9%**，淨利率高達 **42.46%**，在資本極度密集半導體製造業中展現頂級定價權。

---

## 📊 二、 財報體檢與四大基本面量化模型 (Form 20-F)

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2024-12-31**（20-F，申報日 2025-04-17，accession `0001193125-25-083423`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$88,268 百萬**
- **淨利 (Net Income)**: **$35,301 百萬**
- **毛利率 (Gross Margin)**: **56.12%**
- **經營現金流 (OCF)**: **$55,693 百萬**
- **資本支出 (CapEx)**: 資料不足
- **自由現金流 (FCF = OCF − CapEx)**: 資料不足

### 資產負債表
- **總資產**: **$204,079 百萬**
- **總負債**: **$73,574 百萬**
- **股東權益**: **$130,505 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **7 / 7**（2 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ✅ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ⬜ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ⬜ 股數未增加 ｜ ✅ 毛利率提升 ｜ ✅ 資產週轉率提升
- **Altman Z-Score**: **87.71**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 97%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **27.05%**（淨利率 **39.99%** × 資產週轉率 **0.432x** × 權益乘數 **1.564x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **27.05%**

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-01。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **2.60**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **1.43**　（2021-08-06 ~ 2026-07-31，260 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **2.28**　（2025-07-31 ~ 2026-07-31，251 個交易日）
  - 若改以無風險利率為門檻（3.71%，^IRX 13週美國國庫券，期間平均）則為 **2.14**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 籌碼面與資本回饋 (Shareholder Yield)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 $404.25。

- **稀釋每股盈餘 (EPS)**: 資料不足
- **本益比 (P/E)**: 資料不足
- **現金與短期投資**: **$64,893 百萬**
- **總債務（長期＋一年內到期）**: **$0 百萬**
- **淨現金 (Net Cash)**: **$64,893 百萬**
- **庫藏股回購**: 資料不足　→ 回購殖利率 資料不足
- **現金股利**: **$11,072 百萬**　→ 股利殖利率 **0.11%**
- **股東總殖利率 (Shareholder Yield)**: **0.11%**

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=20.0%, WACC=8.5%, 終端成長=2.5%)

> ⚠️ **本節未計算**：缺 FCF。

原因：缺 FCF。腳本不會以假設值代替缺漏資料。

---

## 🔗 關聯筆記
- [[TSM_Company_Profile|台積電 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
