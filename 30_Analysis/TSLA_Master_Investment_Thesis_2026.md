---
ticker: TSLA
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/tsla
  - valuation
  - ev_robotaxi
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2025-12-31
financials_accession: "0001628280-26-003952"
financials_verified: true
---

# Tesla, Inc. (TSLA) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K 官方財報**、**DCF 蒙地卡羅機率模型**、**三大 P/E 估值矩陣**、**Sortino 下行風險**、**四大基本面量化模型** 與 **EV + FSD Cybercab + Megapack + Optimus 護城河分析**。

---

## 🏛️ 一、 公司概況與四大寬廣經濟護城河 (Wide Economic Moat)

1. **電動車極致製造規模與成本優勢 (Unmatched EV Scale & Cost Advantage)** ⚡：
   - 全球每年生產與交付約 165 萬至 180 萬輛電動車。透過 Gigafactory（上海、奧斯汀、柏林）一體化壓鑄 (Gigacasting) 與極致供應鏈控制，具備全球傳統車廠難以企及的生產效率。
2. **FSD 完全自動駕駛與 Cybercab Robotaxi 生態系 (FSD & Robotaxi)** 🤖：
   - 數百萬輛在路上行駛的 Tesla 實時採集真實現界視訊數據，透過 Dojo / AI 超級計算集群進行端到端 (End-to-End Neural Networks) 訓練，建構自動駕駛的極高數據壁壘。
3. **Megapack 儲能系統爆發成長 (Energy Storage Explosion)** 🔋：
   - Megapack 與 Powerwall 儲能業務營收突破 **$125 億美元**，成為第二大核心獲利支柱，強勢受惠於全球資料中心與電網對乾淨能源儲存的暴增需求。
4. **Optimus 人型機器人與全美 Supercharging 網路** 🔌：
   - 超過 55,000 個 Supercharger 充電樁已成為北美 NACS 標準；Optimus 機器人具備進軍工業製造與家庭服務的極大選擇權 (Option Value)。

---

## 📊 二、 近 10 年財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2025-12-31**（10-K，申報日 2026-01-29，accession `0001628280-26-003952`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$94,827 百萬**
- **淨利 (Net Income)**: **$3,794 百萬**
- **毛利率 (Gross Margin)**: **18.03%**
- **經營現金流 (OCF)**: **$14,747 百萬**
- **資本支出 (CapEx)**: **$8,527 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$6,220 百萬**

### 資產負債表
- **總資產**: **$137,806 百萬**
- **總負債**: **$54,941 百萬**
- **股東權益**: **$82,137 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **5 / 9**
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ❌ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ❌ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ❌ 股數未增加 ｜ ✅ 毛利率提升 ｜ ❌ 資產週轉率提升
- **Altman Z-Score**: **14.93**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 90%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **4.62%**（淨利率 **4.00%** × 資產週轉率 **0.688x** × 權益乘數 **1.678x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **4.62%**

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際日線收盤價計算：先取每週最後收盤算週報酬，下行標準差只計入低於門檻報酬率 (MAR = 0) 的週次，再以 `平均週報酬 × 52 ÷ (下行標準差 × √52)` 年化。股價資料擷取於 2026-08-01。

- **近 3 年 Sortino Ratio（週資料）**: **0.63**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **0.60**　（2021-08-06 ~ 2026-07-31，260 週報酬）

---

## 💵 四、 估值比率與資產負債表 (P/E & Balance Sheet)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 $311.21。

- **稀釋每股盈餘 (EPS)**: **$1.08**
- **本益比 (P/E)**: **289.4x**
- **現金與短期投資**: **$44,059 百萬**
- **總債務（長期＋一年內到期）**: **$8,153 百萬**
- **淨現金 (Net Cash)**: **$35,906 百萬**
- **庫藏股回購**: 資料不足　→ 回購殖利率 資料不足
- **現金股利**: 資料不足　→ 股利殖利率 資料不足
- **股東總殖利率 (Shareholder Yield)**: 資料不足

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=22.0%, WACC=9.0%, 終端成長=2.5%)

> 📌 假設來源：`dcf_assumptions.json`（沿用先前 thesis 標題：含 AI/Robotaxi 選項價值 g=22%, WACC=9.0%）。基期自由現金流 $6,220 百萬，預測 10 年後接終端價值，共 10,000 次有效模擬。

| 分位 | P5 | P25 | P50 (中位數) | P75 | P95 |
|---|---|---|---|---|---|
| 每股內在價值 | $67.48 | $93.22 | **$116.76** | $147.80 | $210.37 |

- **平均內在價值**: **$125.12**
- **50% 主流估值區間 (P25 ~ P75)**: **$93.22 ~ $147.80**
- **現價 $311.21 相對中位數**: 高於中位數 **166.5%**

> ⚠️ DCF 結果完全取決於上述假設。改變 g 或 WACC 會顯著改變結論，此處數值僅代表「在該組假設下」的推估，不構成投資建議。

---

## 🔗 關聯筆記
- [[TSLA_Company_Profile|Tesla 公司主頁]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
