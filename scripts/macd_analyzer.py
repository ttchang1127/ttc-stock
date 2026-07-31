#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sec_kb MACD Technical Analyzer (High-Precision & Custom Date Range Edition)
支援指定歷史時間區間 (Date Range Analysis) 的專業 MACD 回測與動能診斷腳本。
"""

import sys
import os
import warnings
import subprocess
from datetime import datetime

# 忽略 urllib3 LibreSSL 警告
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "--quiet"])
    import yfinance as yf

def calc_ema(prices, period):
    ema = []
    k = 2.0 / (period + 1.0)
    for i, p in enumerate(prices):
        if i == 0:
            ema.append(p)
        else:
            ema.append(p * k + ema[-1] * (1.0 - k))
    return ema

def analyze_macd_range(ticker, start_date=None, end_date=None, fast_p=12, slow_p=26, signal_p=9):
    ticker = ticker.upper().strip()
    
    if start_date and end_date:
        print(f"正在擷取 {ticker} 在指定時間區間 [{start_date} ~ {end_date}] 的日線價格與 MACD 動能數據...")
        df = yf.Ticker(ticker).history(start=start_date, end=end_date)
    else:
        print(f"正在連線金融數據庫擷取 {ticker} 最新日線歷史價格與動能數據...")
        df = yf.Ticker(ticker).history(period="6mo")
        
    if df.empty or "Close" not in df.columns or len(df) < slow_p:
        print(f"\n❌ 錯誤: 無法從網絡連結獲取 [{ticker}] 在指定區間的歷史數據 (取得 {len(df)} 筆)。請確認日期格式 (YYYY-MM-DD) 或股票代號。")
        return
        
    closes = [float(c) for c in df["Close"].dropna().tolist()]
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    
    ema_fast = calc_ema(closes, fast_p)
    ema_slow = calc_ema(closes, slow_p)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal = calc_ema(dif, signal_p)
    hist = [(d - s) * 2 for d, s in zip(dif, signal)]
    
    golden_crosses = []
    death_crosses = []
    
    for i in range(1, len(dif)):
        if dif[i-1] < signal[i-1] and dif[i] >= signal[i]:
            golden_crosses.append((dates[i], closes[i], hist[i]))
        elif dif[i-1] > signal[i-1] and dif[i] <= signal[i]:
            death_crosses.append((dates[i], closes[i], hist[i]))
            
    last_close = closes[-1]
    last_date = dates[-1]
    last_dif = dif[-1]
    last_sig = signal[-1]
    last_hist = hist[-1]
    prev_hist = hist[-2] if len(hist) > 1 else last_hist
    
    if dif[-2] < signal[-2] and dif[-1] >= signal[-1]:
        signal_status = "🟢 剛觸發【黃金交叉】(Golden Cross - 多頭啟動訊號)"
    elif dif[-2] > signal[-2] and dif[-1] <= signal[-1]:
        signal_status = "🔴 剛觸發【死亡交叉】(Death Cross - 空頭/修正訊號)"
    elif dif[-1] > signal[-1]:
        signal_status = "🟢 多頭主導 - 綠柱體擴張中" if last_hist > prev_hist else "🟡 多頭主導 - 綠柱體收縮中"
    else:
        signal_status = "🔴 空頭主導 - 紅柱體擴張中" if last_hist < prev_hist else "🟠 空頭主導 - 紅柱體收縮中 (低檔醞釀反彈)"
        
    max_hist = max(hist)
    min_hist = min(hist)
    
    print(f"\n==================================================")
    print(f"📊 {ticker} 指定歷史區間 MACD 動態診斷報告")
    print(f"==================================================")
    print(f"分析時間區間   : {dates[0]} 至 {last_date} (共 {len(closes)} 個交易日)")
    print(f"區間收盤價範圍 : ${min(closes):.2f} ~ ${max(closes):.2f} USD (最新: ${last_close:.2f})")
    print(f"MACD 參數設定  : Fast={fast_p}, Slow={slow_p}, Signal={signal_p}")
    print(f"DIF (快線 12-26) : {last_dif:.4f}")
    print(f"Signal (慢線 9)  : {last_sig:.4f}")
    print(f"MACD 柱狀體      : {last_hist:.4f} (區間最大綠柱: +{max_hist:.4f}, 最大紅柱: {min_hist:.4f})")
    print(f"區間黃金交叉次數 : {len(golden_crosses)} 次 " + (f"({', '.join([g[0] for g in golden_crosses])})" if golden_crosses else ""))
    print(f"區間死亡交叉次數 : {len(death_crosses)} 次 " + (f"({', '.join([d[0] for d in death_crosses])})" if death_crosses else ""))
    print(f"區間結束日診斷   : {signal_status}")
    print(f"==================================================\n")

if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    start_date = sys.argv[2] if len(sys.argv) > 2 else None
    end_date = sys.argv[3] if len(sys.argv) > 3 else None
    analyze_macd_range(ticker, start_date, end_date)
