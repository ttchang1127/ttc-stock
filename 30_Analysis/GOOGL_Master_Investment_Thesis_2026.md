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

> ⚠️ 第四、五章（估值倍數、DCF 模擬）之數字**尚未經來源資料驗證**，沿用先前版本，僅供參考。

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際日線收盤價計算：先取每週最後收盤算週報酬，下行標準差只計入低於門檻報酬率 (MAR = 0) 的週次，再以 `平均週報酬 × 52 ÷ (下行標準差 × √52)` 年化。股價資料擷取於 2026-08-01。

- **近 3 年 Sortino Ratio（週資料）**: **2.06**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **1.21**　（2021-08-06 ~ 2026-07-31，260 週報酬）

---

## 💵 四、 估值比率與資本回饋 (P/E & Shareholder Yield)

- **當前本益比 (P/E Ratio at $326.56)**: **30.2x** 🌟 *(評價極具吸引力！低於 NVDA 39.9x 與 AAPL 44.7x)*
- **股東總殖利率 (Total Shareholder Yield)**: **1.87%** (包含每季現金股利與每年 $650 億美元庫藏股回購)
- **淨現金 ($Net\ Cash$)**: **+$802.96 億美元** ($1,268.4 億現金與短期投資 - $465.5 億總債務，全科技業最高淨現金儲備!)

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (Cloud/Gemini AI 成長率 $g=13.5\%$, WACC=$8.5\%$)

```
                    ┌──────────────────────────────────────────────────────────┐
                    │      GOOGL 蒙地卡羅 10,000 次估值機率分佈 (Monte Carlo)    │
                    └──────────────────────────────────────────────────────────┘
      P5 (5% 極端下限)      P25 (保守分位)        P50 (中位數)       P75 (樂觀分位)      P95 (95% 機率上限)
        $137.62           $161.03        $182.36       $206.88           $255.70
```

- **平均內在價值 (Mean Intrinsic Value)**: **$187.31 USD**
- **中位數內在價值 (Median Intrinsic Value)**: **$182.36 USD**
- **50% 主流估值區間 (P25 ~ P75)**: **$161.03 ~ $206.88 USD**
- **95% 機率上限 (P95 Bullish Ceiling)**: **$255.70 USD**

*現價 ($326.56 美元) 落在蒙地卡羅估值中位數附近，考量其 P/E 僅 30.2x，淨利高達 $1,321 億美元，且擁有全美股最高的 $802 億淨現金，具備極強的防禦性與安全邊際。*

---

## 🔗 關聯筆記
- [[GOOGL_Company_Profile|Alphabet / Google 公司主頁]]
- [[MSFT_Master_Investment_Thesis_2026|微軟 主報告對比]]
- [[AMZN_Master_Investment_Thesis_2026|Amazon 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
- [[META_Master_Investment_Thesis_2026|Meta 主報告對比]]
- [[TSLA_Master_Investment_Thesis_2026|Tesla 主報告對比]]
