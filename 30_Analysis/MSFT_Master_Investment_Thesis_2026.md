---
ticker: MSFT
analysis_type: Master_Investment_Thesis
base_year: 2025
tags:
  - analysis/master_thesis
  - company/msft
  - valuation
  - azure_cloud
  - openai
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2026-06-30
financials_accession: "0001193125-26-323660"
financials_verified: true
---

# Microsoft Corporation (MSFT) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K 官方財報**、**DCF 蒙地卡羅機率模型**、**三大 P/E 估值矩陣**、**Sortino 下行風險**、**四大基本面量化模型** 與 **Azure + OpenAI 生態系護城河分析**。

---

## 🏛️ 一、 公司概況與三大寬廣經濟護城河 (Wide Economic Moat)

1. **Azure 企業級 AI 與雲端平台 (Azure & Intelligent Cloud)** ⚡：
   - 包含 Azure 雲端、OpenAI GPT-4/Copilot API 整合。FY2025 包含 Azure 在內的 **Microsoft Cloud 營收高達 $1,689.0 億美元** (年增 23%)，Azure 單項增速高達 **+34%**！
2. **Office 365 與企業生產力極高切換成本 (Productivity & Office 365)** 🔒：
   - 全球企業商業辦公軟體絕對龍頭，Microsoft 365 Commercial 商業訂閱續約率逼近 100%，具備極強的定價權與高毛利。
3. **Windows 桌面生態系與 Gaming 帝國 (Windows OS & Xbox/Activision)** 🎮：
   - Windows 掌控全球個人電腦 OS 市場，並成功收購動視暴雪 (Activision Blizzard)，強勢擴張 Xbox 訂閱內容。

---

## 📊 二、 近 10 年財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2026-06-30**（10-K，申報日 2026-07-29，accession `0001193125-26-323660`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$331,839 百萬**
- **淨利 (Net Income)**: **$133,749 百萬**
- **毛利率 (Gross Margin)**: **67.94%**
- **經營現金流 (OCF)**: **$182,935 百萬**
- **資本支出 (CapEx)**: **$115,948 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$66,987 百萬**

### 資產負債表
- **總資產**: **$758,376 百萬**
- **總負債**: **$315,989 百萬**
- **股東權益**: **$442,387 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **6 / 9**
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ✅ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ✅ 長期負債比下降 ｜ ❌ 流動比率提升 ｜ ✅ 股數未增加 ｜ ❌ 毛利率提升 ｜ ❌ 資產週轉率提升
- **Altman Z-Score**: **8.83**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 80%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **30.23%**（淨利率 **40.31%** × 資產週轉率 **0.438x** × 權益乘數 **1.714x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **30.23%**

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-07。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **1.18**　（2023-08-11 ~ 2026-08-07，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **0.88**　（2021-08-13 ~ 2026-08-07，260 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **0.05**　（2025-08-07 ~ 2026-08-07，251 個交易日）
  - 若改以無風險利率為門檻（3.70%，^IRX 13週美國國庫券，期間平均）則為 **-0.13**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與資本回饋 (P/E & Shareholder Yield)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-08-07 之 $499.99。

- **稀釋每股盈餘 (EPS)**: **$17.95**
- **本益比 (P/E)**: **27.9x**
- **現金與短期投資**: **$76,843 百萬**
- **總債務（長期＋一年內到期）**: **$40,294 百萬**
- **淨現金 (Net Cash)**: **$36,549 百萬**
- **庫藏股回購**: **$22,271 百萬**　→ 回購殖利率 **0.60%**
- **現金股利**: **$26,445 百萬**　→ 股利殖利率 **0.71%**
- **股東總殖利率 (Shareholder Yield)**: **1.31%**

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=13.0%, WACC=8.5%, 終端成長=2.5%)

> 📌 假設來源：`dcf_assumptions.json`（沿用先前 thesis 標題：Azure/AI g=13%, WACC=8.5%）。基期自由現金流 $66,987 百萬，預測 10 年後接終端價值，共 10,000 次有效模擬。

| 分位 | P5 | P25 | P50 (中位數) | P75 | P95 |
|---|---|---|---|---|---|
| 每股內在價值 | $234.54 | $296.15 | **$351.04** | $419.70 | $547.42 |

- **平均內在價值**: **$366.03**
- **50% 主流估值區間 (P25 ~ P75)**: **$296.15 ~ $419.70**
- **現價 $499.99 相對中位數**: 高於中位數 **42.4%**

> ⚠️ DCF 結果完全取決於上述假設。改變 g 或 WACC 會顯著改變結論，此處數值僅代表「在該組假設下」的推估，不構成投資建議。

---

## ⚠️ 六、 核心風險因素與利弊分析 (SEC Form 10-K Item 1A & Pros/Cons Matrix)

### 1. 三大核心風險因素 (Item 1A Risk Factors)
- **💸 天價 AI 資料中心與 GPU 資本支出飆升 ($1,159.5 億美元 CapEx)**：建置 AI 超級資料中心與採購 NVIDIA GPU 的 CapEx 飆升至 $1,159.5 億美元，短期吞噬了部分自由現金流 (FCF) 的換算率。
- **🤝 OpenAI 獨家夥伴關係與監管審查風險 (OpenAI Dependence)**：投資 OpenAI 的巨額承諾與獨家授權協議面臨 FTC、歐盟反壟斷調查，若 OpenAI 股權或架構變動可能影響 Copilot 整合進度。
- **☁️ Amazon AWS 與 Google Cloud 在雲端基礎設施的激烈競爭**：在企業級雲端與 AI 晶片層面面臨 AWS 與 Google Cloud (TPU) 的強大競爭。

### 2. 投資利弊與優劣勢矩陣 (Pros & Cons Matrix)
- **🟢 多頭優勢 (Pros / Bull Case)**：
  - **本組合第 1 大 OCF（14 家中，$1,829 億）**：本業現金創造能力居本知識庫追蹤名單之首。
  - **Azure 雲端與 Copilot 生態系領先**：企業級 AI 商業化最快變現的龍頭。
  - **Office 365 轉換成本極高**：擁有全球企業辦公軟體的訂閱壟斷。
  - **資產負債表零淨債務 ($365 億淨現金)**：極高的防禦抗風險能力。
- **🔴 空頭隱憂 (Cons / Bear Case)**：
  - **CapEx 資本支出飆升壓抑近季 FCF**：建置 AI 資料中心投入 $1,159 億。
  - **本益比 (P/E 25.9x) 高於 DCF 保守中位數**：市場已賦予 AI 溢價。

---

## 🔗 關聯筆記
- 🌐 **[開啟 Microsoft 獨立網頁版投資報告 (msft_report.html)](file:///Volumes/Crucial%20X8/Jarvis%20Obsidian/Sec_kb/msft_report.html)**
- [[MSFT_Company_Profile|微軟 公司主頁]]
- [[AMZN_Master_Investment_Thesis_2026|Amazon 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
