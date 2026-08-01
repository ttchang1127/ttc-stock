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
- **Altman Z-Score**: **8.33**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 79%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **30.23%**（淨利率 **40.31%** × 資產週轉率 **0.438x** × 權益乘數 **1.714x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **30.23%**

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際日線收盤價計算：先取每週最後收盤算週報酬，下行標準差只計入低於門檻報酬率 (MAR = 0) 的週次，再以 `平均週報酬 × 52 ÷ (下行標準差 × √52)` 年化。股價資料擷取於 2026-08-01。

- **近 3 年 Sortino Ratio（週資料）**: **0.97**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **0.80**　（2021-08-06 ~ 2026-07-31，260 週報酬）

---

## 💵 四、 估值比率與資本回饋 (P/E & Shareholder Yield)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 $464.72。

- **稀釋每股盈餘 (EPS)**: **$17.95**
- **本益比 (P/E)**: **25.9x**
- **現金與短期投資**: **$76,843 百萬**
- **總債務（長期＋一年內到期）**: **$40,294 百萬**
- **淨現金 (Net Cash)**: **$36,549 百萬**
- **庫藏股回購**: **$22,271 百萬**　→ 回購殖利率 **0.65%**
- **現金股利**: **$26,445 百萬**　→ 股利殖利率 **0.77%**
- **股東總殖利率 (Shareholder Yield)**: **1.41%**

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=13.0%, WACC=8.5%, 終端成長=2.5%)

> 📌 假設來源：`dcf_assumptions.json`（沿用先前 thesis 標題：Azure/AI g=13%, WACC=8.5%）。基期自由現金流 $66,987 百萬，預測 10 年後接終端價值，共 10,000 次有效模擬。

| 分位 | P5 | P25 | P50 (中位數) | P75 | P95 |
|---|---|---|---|---|---|
| 每股內在價值 | $234.54 | $296.15 | **$351.04** | $419.70 | $547.42 |

- **平均內在價值**: **$366.03**
- **50% 主流估值區間 (P25 ~ P75)**: **$296.15 ~ $419.70**
- **現價 $464.72 相對中位數**: 高於中位數 **32.4%**

> ⚠️ DCF 結果完全取決於上述假設。改變 g 或 WACC 會顯著改變結論，此處數值僅代表「在該組假設下」的推估，不構成投資建議。

---

## 🔗 關聯筆記
- [[MSFT_Company_Profile|微軟 公司主頁]]
- [[AMZN_Master_Investment_Thesis_2026|Amazon 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
