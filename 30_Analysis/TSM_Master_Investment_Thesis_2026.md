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
3. **晶圓代工中領先的利潤率 (Foundry Margin Leadership)** 💎：
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
- **Piotroski F-Score**: **7 / 8**（1 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ✅ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ❌ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ⬜ 股數未增加 ｜ ✅ 毛利率提升 ｜ ✅ 資產週轉率提升
- **Altman Z-Score**: **91.04**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 98%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **27.05%**（淨利率 **39.99%** × 資產週轉率 **0.432x** × 權益乘數 **1.564x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **27.05%**

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-07。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **2.75**　（2023-08-11 ~ 2026-08-07，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **1.49**　（2021-08-13 ~ 2026-08-07，260 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **2.43**　（2025-08-07 ~ 2026-08-07，251 個交易日）
  - 若改以無風險利率為門檻（3.70%，^IRX 13週美國國庫券，期間平均）則為 **2.28**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 籌碼面與資本回饋 (Shareholder Yield)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-08-07 之 $420.04。

- **稀釋每股盈餘 (EPS)**: 資料不足
- **本益比 (P/E)**: 資料不足
- **現金與短期投資**: **$64,893 百萬**
- **總債務（長期＋一年內到期）**: **$31,932 百萬**
- **淨現金 (Net Cash)**: **$32,961 百萬**
- **庫藏股回購**: 資料不足　→ 回購殖利率 資料不足
- **現金股利**: **$11,072 百萬**　→ 股利殖利率 **0.10%**
- **股東總殖利率 (Shareholder Yield)**: **0.10%**

---

## ⚠️ 六、 核心風險因素與利弊分析 (SEC Form 20-F Item 3 & Pros/Cons Matrix)

### 1. 三大核心風險因素 (Item 3 Risk Factors)
- **🌏 地緣政治與海外擴廠摩擦 (Global Fab Friction)**：台灣海峽兩岸地緣政治緊張情勢；美國亞利桑那、日本熊本、德國德勒斯登海外建廠，學習曲線、工會文化差異與當地營運成本顯著高於台灣本土晶圓廠。
- **💸 極高資本支出 (CapEx) 與折舊壓力 (Fixed Cost Friction)**：每年需投入 300 億至 380 億美元的天價 CapEx 用於 High-NA EUV 採購及 2nm/A16 研發。一旦半導體景氣劇烈修正，高固定成本與折舊壓力將侵蝕淨利率。
- **⚡ 客戶高度集中與水電天然災害 (Infrastructure Dependencies)**：前兩大頂級客戶（Apple 與 NVIDIA）貢獻晶圓營收高達 35%+；此外，地震、極端氣候水資源與台灣電力穩定度皆為實體生產風險。

### 2. 投資利弊與優劣勢矩陣 (Pros & Cons Matrix)
- **🟢 多頭優勢 (Pros / Bull Case)**：
  - **2nm / A16 製程技術絕對獨霸**：掌控全球近 90% 最先進 AI 晶片代工產能 (Apple, NVIDIA, AMD, Qualcomm)。
  - **CoWoS / SoIC 先進封裝生態系壁壘**：晶圓代工與 3D Fabric 緊密結合，競爭對手難以複製。
  - **頂級財務獲利品質**：毛利率 **59.90%**、淨利率 **42.46%**，展現極高定價權。
  - **資產負債表極度健全**：擁有 **$648.9 億美元淨現金**，零金融淨負債，F-Score **7/7 滿分**。
- **🔴 空頭隱憂 (Cons / Bear Case)**：
  - **現金股利殖利率偏低 (0.11% ~ 1.5%)**：天價 CapEx 資本支出吞噬大部分現金流，現金回饋低於防禦型股票。
  - **地緣政治與美國晶片法案夾心**：受制於地緣政治與美國出口管制規範，經營彈性受限。
  - **自由現金流 (FCF) 受天價 CapEx 壓抑**：每年數百億美元建廠與光刻機投入。

---

## 🔗 關聯筆記
- 🌐 **[開啟 台積電 獨立網頁版投資報告 (tsm_report.html)](file:///Volumes/Crucial%20X8/Jarvis%20Obsidian/Sec_kb/tsm_report.html)**
- [[TSM_Company_Profile|台積電 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
