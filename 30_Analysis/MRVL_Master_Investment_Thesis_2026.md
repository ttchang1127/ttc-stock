---
ticker: MRVL
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/mrvl
  - valuation
  - portfolio
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2026-01-31
financials_accession: "0001835632-26-000011"
financials_verified: true
---

# Marvell Technology, Inc. (MRVL) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K / 20-F 官方財報**、**DCF 蒙地卡羅 10,000 次機率模型**、**Sortino 下行風險管理**、**四大基本面量化模型 (Piotroski F-Score / Altman Z-Score / DuPont)** 與 **護城河產業分析**。

---

## 🏛️ 一、 公司概況與經濟護城河 (Wide Economic Moat)

- **核心業務與產業地位**: 寬廣護城河 (客製化 AI ASIC 晶片、PAM4 800G/1.6T 光電轉接 DSP 雙雄)
- **標籤與投資亮點**: `雲端 Custom AI ASIC 雙雄`

---

## 📊 二、 財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2026-01-31**（10-K，申報日 2026-03-11，accession `0001835632-26-000011`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$8,195 百萬**
- **淨利 (Net Income)**: **$2,670 百萬**
- **毛利率 (Gross Margin)**: **51.02%**
- **經營現金流 (OCF)**: **$1,750 百萬**
- **資本支出 (CapEx)**: **$354 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$1,396 百萬**

### 資產負債表
- **總資產**: **$22,285 百萬**
- **總負債**: **$7,977 百萬**
- **股東權益**: **$14,308 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **7 / 9**
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ✅ ROA 較前一年提升 ｜ ❌ OCF > 淨利（應計品質） ｜ ✅ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ❌ 股數未增加 ｜ ✅ 毛利率提升 ｜ ✅ 資產週轉率提升
- **Altman Z-Score**: **14.68**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 94%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **18.66%**（淨利率 **32.58%** × 資產週轉率 **0.368x** × 權益乘數 **1.558x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **18.66%**

---

## 📈 三、 下行風險與二級市場波動 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-07。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **1.68**　（2023-08-11 ~ 2026-08-06，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **1.18**　（2021-08-06 ~ 2026-08-06，261 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **2.78**　（2025-08-06 ~ 2026-08-06，251 個交易日）
  - 若改以無風險利率為門檻（3.70%，^IRX 13週美國國庫券，期間平均）則為 **2.70**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與乘數分析 (P/E & Multiples)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-08-06 之 $210.54。

- **稀釋每股盈餘 (EPS)**: **$3.07**
- **本益比 (P/E)**: **68.6x**
- **現金與短期投資**: **$2,639 百萬**
- **總債務（長期＋一年內到期）**: **$3,971 百萬**
- **淨現金 (Net Cash)**: **$-1,332 百萬**
- **庫藏股回購**: **$2,040 百萬**　→ 回購殖利率 **1.11%**
- **現金股利**: **$205 百萬**　→ 股利殖利率 **0.11%**
- **股東總殖利率 (Shareholder Yield)**: **1.22%**

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=22.5%, WACC=14.2%, 終端成長=2.5%)

> 📌 假設來源：`dcf_assumptions.json`（CAPM 推導：beta 2.16 × ERP 5.0% + Rf 3.71%，稅後 Kd 4.13% 加權；營收 CAGR 22.50%）。基期自由現金流 $1,396 百萬，預測 10 年後接終端價值，共 10,000 次有效模擬。

| 分位 | P5 | P25 | P50 (中位數) | P75 | P95 |
|---|---|---|---|---|---|
| 每股內在價值 | $28.53 | $39.69 | **$50.57** | $64.28 | $90.84 |

- **平均內在價值**: **$53.95**
- **50% 主流估值區間 (P25 ~ P75)**: **$39.69 ~ $64.28**
- **現價 $210.54 相對中位數**: 高於中位數 **316.3%**

> ⚠️ DCF 結果完全取決於上述假設。改變 g 或 WACC 會顯著改變結論，此處數值僅代表「在該組假設下」的推估，不構成投資建議。

---

## ⚠️ 六、 核心風險因素與利弊分析 (SEC Form 10-K Item 1A & Pros/Cons Matrix)

### 1. 三大核心風險因素 (Item 1A Risk Factors)
- **🥊 Broadcom (博通) 惡性價格競爭與 ASIC 訂單分流 (Broadcom ASIC Rivalry)**：在客製化 AI ASIC 領域與龍頭 Broadcom (AVGO) 進行正面競爭。CSP 雲端巨頭常採用雙供應商策略，若 Broadcom 降價搶單，可能擠壓 Marvell 的客製化晶片毛利。
- **💸 P/E 61.1x 高估值與 $39.7 億美元債務負擔 (Valuation & Debt Friction)**：目前本益比 61.1x 已反映極高的 AI 成長預期；此外因歷史並購 (Inphi / Innovium) 累積了 $39.7 億美元金融債務 (淨現金為 $-13.3 億美元)，利息支出負擔相對較大。
- **📡 傳統企業網路與電信 5G 基礎設施景氣修正 (Legacy Enterprise Slowdown)**：除了資料中心 AI 成長爆發外，傳統企業網路 (Enterprise Networking) 與電信基礎設施 (Carrier Infrastructure) 需求相對平淡，傳統業務復甦腳步可能拖累短期整體營收增速。

### 2. 投資利弊與優劣勢矩陣 (Pros & Cons Matrix)
- **🟢 多頭優勢 (Pros / Bull Case)**：
  - **雲端 Custom AI ASIC 雙雄地位**：卡位四大雲端巨頭客製化晶片趨勢，直接受惠 AI 算力擴產。
  - **PAM4 800G/1.6T 光電轉接 DSP 絕對壟斷**：掌控 AI 資料中心高速傳輸心臟。
  - **Piotroski F-Score 7/9 良好會計品質**：會計獲利與營運現金流品質極度健康。
  - **12M 日線 Sortino Ratio 2.37**：全持股中下行防禦與爆發力兼具的前三強標的。
  - **每年買回超 $20 億美元庫藏股**：持續執行庫藏股回購回饋股東。
- **🔴 空頭隱憂 (Cons / Bear Case)**：
  - **本益比 (P/E 61.1x) 處於高位**：顯著高於 DCF 蒙地卡羅保守模型中位數 ($50.57)。
  - **Broadcom 競爭威脅強大**：在 ASIC 與網通晶片領域面臨 Broadcom 價格與技術競爭。
  - **淨現金為負 ($-13.3 億美元)**：負債 $39.7 億美元，資產負債表防禦力低於 NVDA/GOOG。
  - **傳統企業網通業務復甦緩慢**：非 AI 資料中心業務成長動能較為平淡。

---

## 🔗 關聯筆記
- 🌐 **[開啟 Marvell Technology 獨立網頁版投資報告 (mrvl_report.html)](file:///Volumes/Crucial%20X8/Jarvis%20Obsidian/Sec_kb/mrvl_report.html)**
- [[MRVL_Company_Profile|Marvell Technology, Inc. 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[GOOGL_Master_Investment_Thesis_2026|Alphabet / Google 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
