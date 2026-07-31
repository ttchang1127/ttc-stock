#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sec_kb MACD Technical Analyzer (Auto-Installing & High-Precision Edition)
自動檢測並安裝 yfinance 權威金融庫，100% 保障數據獲取與 MACD 計算。
"""

import sys
import os
import warnings
import subprocess

# 忽略 urllib3 LibreSSL 警告，保持輸出乾淨
warnings.filterwarnings("ignore")

# 自動檢測並安裝 yfinance 權威金融數據庫
try:
    import yfinance as yf
except ImportError:
    print("⚡ 正在為您自動安裝 yfinance 權威美股數據套件 (僅需數秒)...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "--quiet"])
        import yfinance as yf
        print("✓ yfinance 安裝成功！開始分析趨勢...\n")
    except Exception as e:
        print(f"❌ 自動安裝 yfinance 失敗。請手動執行: pip3 install yfinance ({e})")

def calc_ema(prices, period):
    ema = []
    k = 2.0 / (period + 1.0)
    for i, p in enumerate(prices):
        if i == 0:
            ema.append(p)
        else:
            ema.append(p * k + ema[-1] * (1.0 - k))
    return ema

def analyze_macd(ticker):
    ticker = ticker.upper().strip()
    print(f"正在連線金融數據庫擷取 {ticker} 最新日線歷史價格與動能數據...")
    
    closes = []
    source_name = "yfinance Official API"
    
    try:
        df = yf.Ticker(ticker).history(period="6mo")
        if not df.empty and "Close" in df.columns:
            closes = [float(c) for c in df["Close"].dropna().tolist()]
    except Exception as e:
        print(f"yfinance 抓取警告: {e}")
        
    if len(closes) < 30:
        print(f"\n❌ 錯誤: 無法從網絡連結獲取 [{ticker}] 的歷史價格數據 (取得 {len(closes)} 筆)。")
        print("💡 請檢查 Mac 是否連線網際網路，或嘗試執行： pip3 install yfinance --upgrade\n")
        return
        
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    dif = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal = calc_ema(dif, 9)
    hist = [(d - s) * 2 for d, s in zip(dif, signal)]
    
    last_close = closes[-1]
    last_dif = dif[-1]
    last_sig = signal[-1]
    last_hist = hist[-1]
    prev_hist = hist[-2]
    
    # 動態交叉判斷
    if dif[-2] < signal[-2] and dif[-1] >= signal[-1]:
        signal_status = "🟢 剛觸發【黃金交叉】(Golden Cross - 多頭啟動訊號)"
    elif dif[-2] > signal[-2] and dif[-1] <= signal[-1]:
        signal_status = "🔴 剛觸發【死亡交叉】(Death Cross - 空頭/修正訊號)"
    elif dif[-1] > signal[-1]:
        if last_hist > prev_hist:
            signal_status = "🟢 多頭主導 - 綠柱體擴張中 (多頭衝刺段)"
        else:
            signal_status = "🟡 多頭主導 - 綠柱體收縮中 (高檔動能放緩)"
    else:
        if last_hist < prev_hist:
            signal_status = "🔴 空頭主導 - 紅柱體擴張中 (下修殺盤段)"
        else:
            signal_status = "🟠 空頭主導 - 紅柱體收縮中 (低檔醞釀反彈)"
            
    zero_line = "高於 0 軸 (強勢多頭水庫區)" if last_dif > 0 else "低於 0 軸 (弱勢修整水庫區)"
    
    print(f"\n==================================================")
    print(f"📊 {ticker} MACD 技術面動態診斷報告 (數據源: {source_name})")
    print(f"==================================================")
    print(f"當前最新收盤價 : ${last_close:.2f} USD")
    print(f"DIF (快線 12-26) : {last_dif:.4f}")
    print(f"Signal (慢線 9)  : {last_sig:.4f}")
    print(f"MACD 柱狀體      : {last_hist:.4f}")
    print(f"零軸控制位置     : {zero_line}")
    print(f"當前趨勢診斷     : {signal_status}")
    print(f"==================================================\n")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    analyze_macd(target)
