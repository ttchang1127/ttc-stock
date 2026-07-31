---
ticker: AAPL
analysis_type: PE_Ratio_Forecasting
base_year: 2025
forecast_year: 2026
tags:
  - analysis/pe_ratio
  - company/aapl
  - valuation
---

# Apple Inc. (AAPL) 2026 本益比 (P/E Ratio) 估算與目標價預測模型

## 🎯 本益比預測的核心公式
在專業機構研究中，本益比估值的公式為：

$$\text{目標價 (Target Price)} = \text{遠期每股盈餘 (Forward EPS)} \times \text{合理目標本益比 (Forward P/E Multiplier)}$$

根据 2025 10-K 與 2026 10-Q 財報：
- **2025 實質每股盈餘 ($EPS_{2025}$)**: **$7.46 USD** ($1,120.1 億美元淨利 / 150.05 億股)
- **2026 預估遠期每股盈餘 ($Forward\ EPS_{2026}$)**:
  - 基準推估 (+12% YoY): **$8.36 USD**
  - 樂觀推估 (+15% YoY): **$8.58 USD**

---

## 🏛️ 三大機構級具公信力的 P/E 預測計算方法

### 1. 戈登成長模型導出的理論本益比 (Gordon Growth Theoretical P/E)
根據戈登模型，理論遠期本益比公式為：

$$\text{Theoretical Forward P/E} = \frac{\text{Capital Payout Ratio (資本總發放率)}}{r - g}$$

- **參數設定**:
  - $r$ (權益成本 WACC): $8.5\%$
  - $g$ (長期 EPS 成長率): $3.5\%$
  - **Payout Ratio (股利 + 庫藏股總發放率)**: **$93.5\%$** ($154 億股利 + $893 億庫藏股回購 / $1,120 億淨利)
- **理論估算 P/E**: **$18.7x$**
- **👉 目標價推算**: **$156.34 USD** ($8.36 \times 18.7$)

---

### 2. PEG 成長估值模型 (Price/Earnings to Growth Model)
由 Peter Lynch 提出，結合 EPS 預期成長率 $g$ 的本益比模型：

$$\text{Target P/E} = \text{Benchmark PEG} \times \text{EPS Growth Rate } (g \times 100)$$

- **保守情境 (PEG = 1.0, P/E = 12.0x)**: 目標價 **$100.33 USD**
- **合理情境 (PEG = 1.5, P/E = 18.0x)**: 目標價 **$150.49 USD**
- **溢價情境 (PEG = 2.0, P/E = 24.0x)**: 目標價 **$200.66 USD**

---

### 3. 歷史本益比區間與均值回歸模型 (Historical P/E Band Model)
觀察 Apple 過去 5 年的歷史 P/E 交易區間（考慮 Apple 的獨占護城河與巨額庫藏股溢價）：

- **歷史下緣 (P/E = 22.0x)**: 目標價 **$183.93 USD**
- **歷史中位 (P/E = 26.5x)**: 目標價 **$221.56 USD**
- **歷史上緣 (P/E = 31.0x)**: 目標價 **$259.18 USD**

---

## 🔗 關聯筆記
- [[AAPL_2025_DCF_Valuation_Model|AAPL 2025 DCF 估值模型]]
- [[AAPL_2025_10K|AAPL 2025 10-K 主筆記]]
