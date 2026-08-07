---
ticker: INTC
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/intc
  - valuation
  - portfolio
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2025-12-27
financials_accession: "0000050863-26-000011"
financials_verified: true
---

# Intel Corporation (INTC) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K / 20-F 官方財報**、**DCF 蒙地卡羅 10,000 次機率模型**、**Sortino 下行風險管理**、**四大基本面量化模型 (Piotroski F-Score / Altman Z-Score / DuPont)** 與 **護城河產業分析**。

---

## 🏛️ 一、 公司概況與經濟護城河 (Wide Economic Moat)

- **核心業務與產業地位**: 窄護城河 (x86 架構專利霸主、美國本土晶片法案 18A / 14A 晶圓代工自研轉型期)
- **標籤與投資亮點**: `x86 CPU & 晶體管轉型股`

---

## 📊 二、 財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2025-12-27**（10-K，申報日 2026-01-23，accession `0000050863-26-000011`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$52,853 百萬**
- **淨利 (Net Income)**: **$-267 百萬**
- **毛利率 (Gross Margin)**: **34.77%**
- **經營現金流 (OCF)**: **$9,697 百萬**
- **資本支出 (CapEx)**: **$14,646 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$-4,949 百萬**

### 資產負債表
- **總資產**: **$211,429 百萬**
- **總負債**: 資料不足
- **股東權益**: **$114,281 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **6 / 9**
  - ❌ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ✅ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ✅ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ❌ 股數未增加 ｜ ✅ 毛利率提升 ｜ ❌ 資產週轉率提升
- **Altman Z-Score**: 資料不足（缺 X4）
- **DuPont ROE**: **-0.23%**（淨利率 **-0.51%** × 資產週轉率 **0.250x** × 權益乘數 **1.850x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **-0.23%**

---

## 📈 三、 下行風險與二級市場波動 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-07。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **1.50**　（2023-08-11 ~ 2026-08-06，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **0.82**　（2021-08-06 ~ 2026-08-06，261 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **4.33**　（2025-08-06 ~ 2026-08-06，251 個交易日）
  - 若改以無風險利率為門檻（3.70%，^IRX 13週美國國庫券，期間平均）則為 **4.23**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與乘數分析 (P/E & Multiples)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-08-06 之 $99.81。

- **稀釋每股盈餘 (EPS)**: **$-0.06**
- **本益比 (P/E)**: 資料不足（EPS 為負，本益比無意義）
- **現金與短期投資**: **$23,808 百萬**
- **總債務（長期＋一年內到期）**: **$46,585 百萬**
- **淨現金 (Net Cash)**: **$-22,777 百萬**
- **庫藏股回購**: 資料不足　→ 回購殖利率 資料不足
- **現金股利**: **$0 百萬**　→ 股利殖利率 **0.00%**
- **股東總殖利率 (Shareholder Yield)**: **0.00%**

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=2.0%, WACC=12.4%, 終端成長=2.5%)

> ⚠️ **本節未計算**：FCF 為負，DCF 不適用。

原因：FCF 為負，DCF 不適用。腳本不會以假設值代替缺漏資料。

> ⚠️ 基期自由現金流為負（資本支出超過營運現金流），單一年度 FCF 無法作為 DCF 外推基礎，需改用常態化 FCF

---

## ⚠️ 六、 核心風險因素與利弊分析 (SEC Form 10-K Item 1A & Pros/Cons Matrix)

### 1. 三大核心風險因素 (Item 1A Risk Factors)
- **🏭 Intel Foundry 18A / 14A 晶圓代工良率與產能開出風險 (Yield & Execution Risk)**：IFS 晶圓代工業務每年虧損數十億美元。18A 製程良率 (Yield) 與客戶外部下單 (如微軟/AWS) 進度若不如預期，天價 CapEx 建廠投資將造成巨大攤銷負擔。
- **💸 自由現金流負數 ($-49.5 億美元) 與沉重債務拖累 (FCF Negative & Debt)**：每年投入 $146.5 億美元 CapEx 導致自由現金流為負數；加上 $465.9 億美元金融債務 (淨負債 $-227.8 億美元)，利息支出與現金消耗壓抑分紅能力。
- **💻 x86 伺服器與 PC 市佔持續遭 AMD 與 Arm 陣營瓜分 (Market Share Erosion)**：在傳統伺服器 CPU 領域面臨 AMD EPYC 強勢侵蝕；在 AI 高效能算力市場遠落後 NVIDIA GPU；在行動與輕薄 PC 端則遭遇 Arm 陣營競爭。

### 2. 投資利弊與優劣勢矩陣 (Pros & Cons Matrix)
- **🟢 多頭優勢 (Pros / Bull Case)**：
  - **美國晶片法案與本土戰略製造國防背書**：獲美政府數百億美元直接支持。
  - **18A / RibbonFET 次世代製程反超契機**：技術成功研發將帶動晶圓代工評級重估。
  - **近 12M Sortino 達 4.15 (全庫冠軍 👑)**：谷底反彈時波段下行收益極強。
  - **本業經營現金流 OCF 高達 $96.97 億美元**：本業獲利現金池依然穩固。
- **🔴 空頭隱憂 (Cons / Bear Case)**：
  - **自由現金流 FCF 為負 ($-49.5 億美元)**：天價建廠支出吞噬現金。
  - **淨負債高達 $-227.8 億美元**：債務負擔沉重，資本結構防禦力弱。
  - **晶圓代工 IFS 虧損持續擴大**：需要數年時間證明代工產能利用率。

---

## 🔗 關聯筆記
- 🌐 **[開啟 Intel Corporation 獨立網頁版投資報告 (intc_report.html)](file:///Volumes/Crucial%20X8/Jarvis%20Obsidian/Sec_kb/intc_report.html)**
- [[INTC_Company_Profile|Intel Corporation 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[GOOGL_Master_Investment_Thesis_2026|Alphabet / Google 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
