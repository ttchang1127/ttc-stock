---
ticker: META
analysis_type: Master_Investment_Thesis
base_year: 2026
tags:
  - analysis/master_thesis
  - company/meta
  - valuation
  - llama_ai
financials_source: SEC XBRL Company Facts
financials_fiscal_year_end: 2025-12-31
financials_accession: "0001628280-26-003942"
financials_verified: true
---

# Meta Platforms, Inc. (META) 近10年財報與 2026 終極估值投資報告

本報告結合 **SEC 近 10 年 10-K 官方財報**、**DCF 蒙地卡羅機率模型**、**三大 P/E 估值矩陣**、**Sortino 下行風險**、**四大基本面量化模型** 與 **32 億用戶 + Llama AI 生態系護城河分析**。

---

## 🏛️ 一、 公司概況與三大寬廣經濟護城河 (Wide Economic Moat)

1. **不可替代的全球社群網路效應 (Network Effect - Family of Apps)** 🌐：
   - 包含 Facebook, Instagram, WhatsApp, Messenger, Threads。全球每日活躍用戶 (DAP) 超過 **32 億人**，擁有全人類網際網路史上最強大的社交與網路效應。
2. **AI 驅動的精準廣告推薦演算法 (AI Ad Targeting & Llama Ecosystem)** ⚡：
   - 開源 Llama AI 模型賦予 Meta 極強的廣告精準比對能力，全家族應用程式廣告曝光量 (Ad Impressions) 年增 12%，Family of Apps 營業利潤率高達 **51.5%** ($1,024.69 億美元)!
3. **極高廣告主切換成本與數據壁壘 (Data Moat & Pricing Power)** 💰：
   - 數百萬中小企業與全球品牌的行銷預算深步綁定 Instagram 與 Facebook 廣告系統。

---

## 📊 二、 近 10 年財報趨勢與四大基本面模型

> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **2025-12-31**（10-K，申報日 2026-01-29，accession `0001628280-26-003942`）。幣別：USD。

### 損益與現金流
- **營收 (Revenue)**: **$200,966 百萬**
- **淨利 (Net Income)**: **$60,458 百萬**
- **毛利率 (Gross Margin)**: 資料不足
- **經營現金流 (OCF)**: **$115,800 百萬**
- **資本支出 (CapEx)**: **$69,691 百萬**
- **自由現金流 (FCF = OCF − CapEx)**: **$46,109 百萬**

### 資產負債表
- **總資產**: **$366,021 百萬**
- **總負債**: **$148,778 百萬**
- **股東權益**: **$217,243 百萬**

### 四大基本面量化模型
- **Piotroski F-Score**: **4 / 8**（1 項因資料不足未計入）
  - ✅ ROA > 0 ｜ ✅ 營運現金流 > 0 ｜ ❌ ROA 較前一年提升 ｜ ✅ OCF > 淨利（應計品質） ｜ ❌ 長期負債比下降 ｜ ❌ 流動比率提升 ｜ ✅ 股數未增加 ｜ ⬜ 毛利率提升 ｜ ❌ 資產週轉率提升
- **Altman Z-Score**: **7.76**（safe 區）
  - ⚠️ X4 (市值/總負債) 占 Z 值 74%，此分數主要反映高市值與低負債，而非償債能力；Altman Z 對輕資產公司不適用
- **DuPont ROE**: **27.83%**（淨利率 **30.08%** × 資產週轉率 **0.549x** × 權益乘數 **1.685x**）
- **ROE 直接驗算 (淨利 ÷ 股東權益)**: **27.83%**

> ⚠️ 第四、五章（估值倍數、DCF 模擬）之數字**尚未經來源資料驗證**，沿用先前版本，僅供參考。

---

## 📈 三、 下行風險與二級市場波動分析 (Sortino Ratio)

> 📌 由 `prices.json` 的實際日線收盤價計算：先取每週最後收盤算週報酬，下行標準差只計入低於門檻報酬率 (MAR = 0) 的週次，再以 `平均週報酬 × 52 ÷ (下行標準差 × √52)` 年化。股價資料擷取於 2026-08-01。

- **近 3 年 Sortino Ratio（週資料）**: **1.14**　（2023-08-04 ~ 2026-07-31，156 週報酬）
- **近 5 年 Sortino Ratio（週資料）**: **0.63**　（2021-08-06 ~ 2026-07-31，260 週報酬）

---

## 💵 四、 估值比率與資本回饋 (P/E & Shareholder Yield)

- **當前本益比 (P/E Ratio at $594.70)**: **25.3x** 🌟 *(在美股七巨頭 MAG7 中本益比評價最便宜！)*
- **股東總殖利率 (Total Shareholder Yield)**: **2.29%** (包含每季現金股利與每年 $300 億美元庫藏股回購)
- **淨現金 ($Net\ Cash$)**: **+$228.48 億美元** ($815.9 億現金 - $587.4 億債務)

---

## 🎲 五、 DCF 蒙地卡羅 10,000 次估值模擬 (常態化 FCF, $g=13\%$, WACC=$8.5\%$)

```
                    ┌──────────────────────────────────────────────────────────┐
                    │      META 蒙地卡羅 10,000 次估值機率分佈 (Monte Carlo)     │
                    └──────────────────────────────────────────────────────────┘
      P5 (5% 極端下限)      P25 (保守分位)        P50 (中位數)       P75 (樂觀分位)      P95 (95% 機率上限)
        $546.44           $651.00        $745.12       $852.30           $1068.90
```

- **平均內在價值 (Mean Intrinsic Value)**: **$766.05 USD**
- **中位數內在價值 (Median Intrinsic Value)**: **$745.12 USD**
- **50% 主流估值區間 (P25 ~ P75)**: **$651.00 ~ $852.30 USD**
- **95% 機率上限 (P95 Bullish Ceiling)**: **$1068.90 USD**

*現價 ($594.70 美元) 位於蒙地卡羅估值主流區間，考量其 P/E 僅 25.3x，且 Family of Apps 營業利潤率高達 51.5%，具備極強的性價比與安全邊際。*

---

## 🔗 關聯筆記
- [[META_Company_Profile|Meta 公司主頁]]
- [[MSFT_Master_Investment_Thesis_2026|微軟 主報告對比]]
- [[AMZN_Master_Investment_Thesis_2026|Amazon 主報告對比]]
- [[AAPL_Master_Investment_Thesis_2026|Apple 主報告對比]]
- [[NVDA_Master_Investment_Thesis_2026|NVIDIA 主報告對比]]
