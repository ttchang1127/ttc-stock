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
- **Piotroski F-Score**: **5 / 8**（1 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ❌ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ✅ 長期負債比下降 ｜ ❌ 流動比率提升 ｜ ⬜ 股數未增加 ｜ ❌ 毛利率提升 ｜ ✅ 資產週轉率提升
- **Altman Z-Score**: **2.81**（grey 區）
- **DuPont ROE**: **3.13%**（淨利率 **3.32%** × 資產週轉率 **0.529x** × 權益乘數 **1.785x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **3.13%**

---

## 📈 三、 下行風險與二級市場波動 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-07。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **1.56**　（2023-08-11 ~ 2026-08-07，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **0.63**　（2021-08-13 ~ 2026-08-07，260 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **2.80**　（2025-08-07 ~ 2026-08-07，251 個交易日）
  - 若改以無風險利率為門檻（3.70%，^IRX 13週美國國庫券，期間平均）則為 **2.69**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與乘數分析 (P/E & Multiples)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-08-07 之 €9.36。

- **稀釋每股盈餘 (EPS)**: 資料不足
- **本益比 (P/E)**: 資料不足
- **現金與短期投資**: **€5,462 百萬**
- **總債務（長期＋一年內到期）**: **€4,413 百萬**
- **淨現金 (Net Cash)**: **€1,049 百萬**
- **庫藏股回購**: **€624 百萬**　→ 回購殖利率 **1.16%**
- **現金股利**: **€759 百萬**　→ 股利殖利率 **1.41%**
- **股東總殖利率 (Shareholder Yield)**: **2.57%**

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=2.0%, WACC=6.7%, 終端成長=2.5%)

> ⚠️ **本節未計算**：缺 FCF。

原因：缺 FCF。腳本不會以假設值代替缺漏資料。

---

## ⚠️ 六、 核心風險因素與利弊分析 (SEC Form 20-F Item 3 & Pros/Cons Matrix)

### 1. 三大核心風險因素 (Item 3 Risk Factors)
- **📡 電信營運商 5G CapEx 建置放緩風險 (Telecom CapEx Slowdown)**：全球主要電信商 (如 AT&T, T-Mobile) 5G 基礎設施高峰期已過，電信 CapEx 縮減可能壓抑 Mobile Networks 事業體的營收增速。
- **🤝 單一頂級客戶單訂單流失風險 (Customer Concentration Risk)**：如先前 AT&T 選擇 Ericsson 作為 Open RAN 單一供應商，引發短線營收衝擊，展現電信設備招標的顧客集中風險。
- **🌐 Open RAN (開放式無線接入網) 架構白牌化競爭**：Open RAN 趨勢允許電信商解耦軟硬體，未來可能招致傳統白牌設備商競爭，分流傳統專利一體化基站的利潤。

### 2. 投資利弊與優劣勢矩陣 (Pros & Cons Matrix)
- **🟢 多頭優勢 (Pros / Bull Case)**：
  - **貝爾實驗室專利金雞母**：每年提供極高毛利的固定專利授權金收入。
  - **高股東殖利率 (2.63%)**：穩定股利分紅與庫藏股回購回饋股東。
  - **資產負債表極度健全**：擁有 **€54.6 億歐元純淨現金**，完全零金融淨債務。
  - **近 12M Sortino 達 2.76**：防禦抗跌屬性優異，適合保守型資產配置。
- **🔴 空頭隱憂 (Cons / Bear Case)**：
  - **營收成長動能較為平淡**：受制於全球電信 CapEx 週期。
  - **DuPont ROE (3.13%) 偏低**：帳面淨利率較薄，資本回報有待提升。

---

## 🔗 關聯筆記
- 🌐 **[開啟 Nokia Corporation 獨立網頁版投資報告 (nok_report.html)](file:///Volumes/Crucial%20X8/Jarvis%20Obsidian/Sec_kb/nok_report.html)**
- [[NOK_Company_Profile|Nokia Corporation 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[GOOGL_Master_Investment_Thesis_2026|Alphabet / Google 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
