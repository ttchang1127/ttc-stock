---
ticker: GOOGL
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/googl
  - valuation
  - gemini_ai
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2025-12-31
financials_accession: "0001652044-26-000018"
financials_verified: true
---

# Alphabet Inc. (GOOGL) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K 官方財報**、**DCF 蒙地卡羅機率模型**、**三大 P/E 估值矩陣**、**Sortino 下行風險**、**四大基本面量化模型** 與 **Search 壟斷 + Gemini AI + Google Cloud + TPU 護城河分析**。

---

## 🏛️ 一、 公司概況與四大寬廣經濟護城河 (Wide Economic Moat)

1. **Google Search 90%+ 搜尋市場絕對壟斷 (Search Monopoly)** 🌐：
   - 掌控全球超過 90% 的網頁搜尋流量，FY2026 搜尋廣告營收高達 **$2,245.32 億美元**，建構全網際網路最強大的數據與護城河。
2. **YouTube 串流影音生態系 (YouTube Ad & Subscription Empire)** 📺：
   - YouTube 廣告營收突破 **$403.67 億美元**，加上 YouTube Premium & Music 訂閱用戶飆升，成為影音娛樂產業龍頭。
3. **Google Cloud & TPU 自研 AI 晶片 (Cloud & AI Architecture)** ⚡：
   - Google Cloud 營收達 **$587.05 億美元** (年增 35.8%)，營業利潤高達 **$139.10 億美元** (暴增 +127.6%!)。自研 TPU (Tensor Processing Unit) 晶片大幅降低 AI 訓練成本。
4. **Gemini 多模態大模型與 Android 30 億裝置生態系** 📱：
   - 全球 30 億 Android 活躍裝置預載 Google 服務；Gemini 深入整合至 Search, Workspace, Cloud 與 Pixel 硬體。

---

## 📊 二、 近 10 年財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2025-12-31**（10-K，申報日 2026-02-05，accession `0001652044-26-000018`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$402,836 百萬**
- **淨利 (Net Income)**: **$132,170 百萬**
- **毛利率 (Gross Margin)**: 資料不足
- **經營現金流 (OCF)**: **$164,713 百萬**
- **資本支出 (CapEx)**: **$91,447 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$73,266 百萬**

### 資產負債表
- **總資產**: **$595,281 百萬**
- **總負債**: **$180,016 百萬**
- **股東權益**: **$415,265 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **5 / 8**（1 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ❌ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ❌ 長期負債比下降 ｜ ✅ 流動比率提升 ｜ ✅ 股數未增加 ｜ ⬜ 毛利率提升 ｜ ❌ 資產週轉率提升
- **Altman Z-Score**: **16.90**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 86%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **31.83%**（淨利率 **32.81%** × 資產週轉率 **0.677x** × 權益乘數 **1.433x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **31.83%**

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。股價資料擷取於 2026-08-01。

**長期（週資料，MAR = 0）**

- **近 3 年 Sortino Ratio（週資料）**: **2.06**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **1.21**　（2021-08-06 ~ 2026-07-31，260 週報酬）

**對照公開篩選器（日資料）**

- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **3.73**　（2025-07-31 ~ 2026-07-31，251 個交易日）
  - 若改以無風險利率為門檻（3.71%，^IRX 13週美國國庫券，期間平均）則為 **3.50**

> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站的公布值可比對（實測 NVDA、TSLA 皆吻合）。

---

## 💵 四、 估值比率與資本回饋 (P/E & Shareholder Yield)

> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，股價為 2026-07-31 之 $356.65。

- **稀釋每股盈餘 (EPS)**: **$10.81**
- **本益比 (P/E)**: **33.0x**
- **現金與短期投資**: **$126,843 百萬**
- **總債務（長期＋一年內到期）**: **$48,543 百萬**
- **淨現金 (Net Cash)**: **$78,300 百萬**
- **庫藏股回購**: **$45,709 百萬**　→ 回購殖利率 **1.05%**
- **現金股利**: **$10,049 百萬**　→ 股利殖利率 **0.23%**
- **股東總殖利率 (Shareholder Yield)**: **1.28%**

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (g=13.5%, WACC=8.5%, 終端成長=2.5%)

> 📌 假設來源：`dcf_assumptions.json`（沿用先前 thesis 標題：Cloud/Gemini g=13.5%, WACC=8.5%）。基期自由現金流 $73,266 百萬，預測 10 年後接終端價值，共 10,000 次有效模擬。

| 分位 | P5 | P25 | P50 (中位數) | P75 | P95 |
|---|---|---|---|---|---|
| 每股內在價值 | $164.16 | $206.99 | **$243.88** | $290.06 | $376.82 |

- **平均內在價值**: **$254.02**
- **50% 主流估值區間 (P25 ~ P75)**: **$206.99 ~ $290.06**
- **現價 $356.65 相對中位數**: 高於中位數 **46.2%**

> ⚠️ DCF 結果完全取決於上述假設。改變 g 或 WACC 會顯著改變結論，此處數值僅代表「在該組假設下」的推估，不構成投資建議。

---

## 🔗 關聯筆記
- [[GOOGL_Company_Profile|Alphabet / Google 公司主頁]]
- [[MSFT_Master_Investment_Thesis_2026|微軟 主報告對比]]
- [[AMZN_Master_Investment_Thesis_2026|Amazon 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[META_Master_Investment_Thesis_2026|Meta 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
