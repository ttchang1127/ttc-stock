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

ema8 = calc_ema(prices, 8)
ema17 = calc_ema(prices, 17)
dif = [fast - slow for fast, slow in zip(ema8, ema17)]
sig = calc_ema(dif, 9)
hist = [d - s for d, s in zip(dif, sig)]

print("NVDA 8/17/9 MACD Analysis (2026-05-01 ~ 2026-07-31):")
print("-" * 85)
print(f"{'Date':12} {'Price':8} {'DIF(8-17)':10} {'Signal(9)':10} {'Hist':8} {'Event / Signal'}")
print("-" * 85)

for i in range(len(dates)):
    d = dates[i]
    if "2026-05-01" <= d <= "2026-07-31":
        p = prices[i]
        df = dif[i]
        sg = sig[i]
        ht = hist[i]
        prev_df = dif[i-1]
        prev_sg = sig[i-1]
        prev_ht = hist[i-1]

        event = ""
        if prev_df < prev_sg and df >= sg:
            event = "🟢 黃金交叉 (Golden Cross) <-- 買進訊號"
        elif prev_df > prev_sg and df <= sg:
            event = "🔴 死亡交叉 (Death Cross) <-- 賣出/結利訊號"
        elif prev_ht < 0 and ht >= 0:
            event = "🟢 柱體紅轉綠 (Red to Green)"
        elif prev_ht < 0 and ht > prev_ht and (ht - prev_ht) > 0.4:
            event = "🟠 紅柱大幅收縮 (止跌卡位點)"

        print(f"{d:12} ${p:6.2f}   {df:8.3f}   {sg:8.3f}   {ht:7.3f}   {event}")
