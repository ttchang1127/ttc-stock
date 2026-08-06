import json

with open("prices.json") as f:
    pdb = json.load(f)

nvda = pdb["series"]["NVDA"]
dates = nvda["dates"]
prices = nvda["closes"]

def calc_ema(data, p):
    k = 2 / (p + 1)
    ema = []
    for i, v in enumerate(data):
        if i == 0:
            ema.append(v)
        else:
            ema.append(v * k + ema[i-1] * (1 - k))
    return ema

# 8/17/9 for Buy
ema8 = calc_ema(prices, 8)
ema17 = calc_ema(prices, 17)
dif_buy = [f - s for f, s in zip(ema8, ema17)]
sig_buy = calc_ema(dif_buy, 9)

# 12/25/9 for Sell
ema12 = calc_ema(prices, 12)
ema25 = calc_ema(prices, 25)
dif_sell = [f - s for f, s in zip(ema12, ema25)]
sig_sell = calc_ema(dif_sell, 9)

print("NVDA 2026/05/01 ~ 2026/07/31 每筆黃金買點與對應 12/25/9 賣點價差精算：")
print("=" * 85)

# Trade 1: 5/8 Buy
b1_d = "2026-05-08"
b1_p = prices[dates.index(b1_d)]
s1_d = "2026-05-21"
s1_p = prices[dates.index(s1_d)]
diff1 = s1_p - b1_p
ret1 = (diff1 / b1_p) * 100

print(f"交易 1:")
print(f"  🟢 買進日期 (8/17/9 金叉):  {b1_d}  收盤價: ${b1_p:.2f}")
print(f"  🔴 賣出日期 (12/25/9 死叉): {s1_d}  收盤價: ${s1_p:.2f}")
print(f"  💵 實際收盤價差 (Sell - Buy): +${diff1:.2f} USD  (波段報酬率: +{ret1:.2f}%)")

# Optional peak exit during Trade 1
peak1_d = "2026-05-14"
peak1_p = prices[dates.index(peak1_d)]
peak1_diff = peak1_p - b1_p
peak1_ret = (peak1_diff / b1_p) * 100
print(f"  ⭐ 若於波段極值高點 ({peak1_d}) 結利: ${peak1_p:.2f}  (最大價差: +${peak1_diff:.2f} USD, +{peak1_ret:.2f}%)")
print("-" * 85)

# Trade 2: 7/7 Buy
b2_d = "2026-07-07"
b2_p = prices[dates.index(b2_d)]
s2_d = "2026-07-27"
s2_p = prices[dates.index(s2_d)]
diff2 = s2_p - b2_p
ret2 = (diff2 / b2_p) * 100

print(f"交易 2 (二次打底成功勝率最佳買點):")
print(f"  🟢 買進日期 (8/17/9 金叉):  {b2_d}  收盤價: ${b2_p:.2f}")
print(f"  🔴 賣出日期 (12/25/9 死叉): {s2_d}  收盤價: ${s2_p:.2f}")
print(f"  💵 實際收盤價差 (Sell - Buy): -${abs(diff2):.2f} USD  (波段報酬率: {ret2:.2f}%)")

# Optional peak exit during Trade 2
peak2_d = "2026-07-15"
peak2_p = prices[dates.index(peak2_d)]
peak2_diff = peak2_p - b2_p
peak2_ret = (peak2_diff / b2_p) * 100
print(f"  ⭐ 若於波段極值高點 ({peak2_d}) 結利: ${peak2_p:.2f}  (最大價差: +${peak2_diff:.2f} USD, +{peak2_ret:.2f}%)")
print("=" * 85)
