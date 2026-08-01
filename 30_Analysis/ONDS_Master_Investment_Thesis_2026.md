---
ticker: ONDS
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/onds
  - valuation
  - autonomous_drones
  - counter_uas
  - defense_tech
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2025-12-31
financials_accession: "0001213900-26-035981"
financials_verified: true
---

# Ondas Holdings Inc. (ONDS) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K 官方財報**、**DCF 蒙地卡羅機率模型**、**Sortino 下行風險**、**四大基本面量化模型** 與 **自主無人機 (Airobotics) + 反無人機 (Counter-UAS) + 私有無線專網 (FullMax) 護城河分析**。

---

## 🏛️ 一、 公司概況與三大核心經濟護城河 (Wide Economic Moat)

1. **Ondas Autonomous Systems (Airobotics / American Robotics) 無人機機巢平台** 🛸：
   - 全球極少數獲得 **FAA (美國聯邦航空管理局) 商業視距外飛行 (BVLOS - Beyond Visual Line of Sight)** 審查核准的自主無人機 (Drone-in-a-Box) 機巢基礎設施。廣泛應用於智慧城市、鐵路巡檢與關鍵基礎設施維安。
2. **Iron Drone & Counter-UAS 反無人機國防防空系統** 🛡️：
   - 具備軍事與國防等級的自主反無人機攔截網與 AI 識別防空系統，直接對接政府國防部、機場與執法單位採購。
3. **FullMax 私有無線專網協定 (Class I Railroad Standards)** 📶：
   - 美國 Class I 鐵路龍頭 (如 Union Pacific, CSX) 指定採用其 900MHz 軟體定義無線電 (SDR) 專利協定，提供超低延遲、高安全度的鐵路自動化通訊。

---

## 📊 二、 近 10 年財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2025-12-31**（10-K，申報日 2026-03-30，accession `0001213900-26-035981`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$51 百萬**
- **淨利 (Net Income)**: **$-132 百萬**
- **毛利率 (Gross Margin)**: **39.73%**
- **經營現金流 (OCF)**: **$-39 百萬**
- **資本支出 (CapEx)**: **$2 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$-41 百萬**

### 資產負債表
- **總資產**: **$1,133 百萬**
- **總負債**: **$661 百萬**
- **股東權益**: **$438 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **4 / 8**（1 項因資料不足未計入）
  - ❌ ROA > 0 ｜ ❌ 營運現金流 > 0 ｜ ✅ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ⬜ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ❌ 股數未增加 ｜ ✅ 毛利率提升 ｜ ❌ 資產週轉率提升
- **Altman Z-Score**: **3.37**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 100%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **-30.20%**（淨利率 **-260.66%** × 資產週轉率 **0.045x** × 權益乘數 **2.587x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **-30.20%**
- ⚠️ **股數異常**: diluted=221,769 與 dei 流通股數=495,762,650 相差 2235 倍，已改用 dei 計算市值

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-01。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **2.08**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **1.00**　（2021-08-06 ~ 2026-07-31，260 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **2.79**　（2025-07-31 ~ 2026-07-31，251 個交易日）
  - 若改以無風險利率為門檻（3.71%，^IRX 13週美國國庫券，期間平均）則為 **2.74**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與市值指標

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 $7.49。

- **稀釋每股盈餘 (EPS)**: **$-596.27**
- **本益比 (P/E)**: 資料不足（EPS 為負，本益比無意義）
- **現金與短期投資**: **$551 百萬**
- **總債務（長期＋一年內到期）**: **$0 百萬**
- **淨現金 (Net Cash)**: **$551 百萬**
- **庫藏股回購**: 資料不足　→ 回購殖利率 資料不足
- **現金股利**: 資料不足　→ 股利殖利率 資料不足
- **股東總殖利率 (Shareholder Yield)**: 資料不足

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=38.0%, WACC=10.5%, 終端成長=2.5%)

> ⚠️ **本節未計算**：FCF 為負，DCF 不適用。

原因：FCF 為負，DCF 不適用。腳本不會以假設值代替缺漏資料。

---

## 🔗 關聯筆記
- [[ONDS_Company_Profile|Ondas Holdings 公司主頁]]
- [[User_Portfolio_Master_Analysis_2026|個人投資組合主報告]]
