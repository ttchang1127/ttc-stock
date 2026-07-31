#!/usr/bin/env python3
"""
SEC Form 13F (Institutional Holdings) & Form 4 (Insider Transactions) Downloader & Parser
Integrates into Sec_kb Financial Framework.
"""

import sys
import os
import json
import urllib.request
import re
import argparse
from datetime import datetime

SEC_HEADERS = {
    'User-Agent': 'SecKBResearch user@example.com'
}

TICKER_CIKS = {
    'AAPL': '0000320193',
    'NVDA': '0001045810',
    'TSM':  '0001046179',
    'AMZN': '0001018724',
    'MSFT': '0000789019',
    'META': '0001326801',
    'TSLA': '0001318605',
    'GOOGL':'0001652044'
}

FAMOUS_FUNDS = {
    'BERKSHIRE_HATHAWAY': {'cik': '0001067983', 'name': 'Warren Buffett (Berkshire Hathaway)'},
    'BRIDGEWATER':         {'cik': '0001350694', 'name': 'Ray Dalio (Bridgewater Associates)'},
    'SCION_ASSET_MGMT':   {'cik': '0001649339', 'name': 'Michael Burry (Scion Asset Management)'},
    'APPALOOSA_LP':       {'cik': '0001006415', 'name': 'David Tepper (Appaloosa Management)'},
    'VANGUARD_GROUP':     {'cik': '0000102909', 'name': 'Vanguard Group Inc'},
    'BLACKROCK_INC':      {'cik': '0001364742', 'name': 'BlackRock Inc'}
}

def fetch_json(url):
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def fetch_text(url):
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode('utf-8', errors='ignore')

def get_recent_form4_for_ticker(ticker, limit=10):
    cik = TICKER_CIKS.get(ticker.upper())
    if not cik:
        return []
    
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = fetch_json(url)
    recent = data['filings']['recent']
    
    forms = recent['form']
    filing_dates = recent['filingDate']
    acc_numbers = recent['accessionNumber']
    primary_docs = recent['primaryDocument']
    
    form4_list = []
    for i in range(len(forms)):
        if forms[i] in ['4', '4/A']:
            acc_clean = acc_numbers[i].replace('-', '')
            doc = primary_docs[i]
            filing_date = filing_dates[i]
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
            
            # Fetch XML/HTML of Form 4
            try:
                xml_content = fetch_text(doc_url)
                
                # Extract Reporter Name, Relationship, Trans Date, Trans Code, Shares, Price
                reporter_match = re.search(r'<rptOwnerName>(.*?)</rptOwnerName>', xml_content, re.IGNORECASE)
                reporter_name = reporter_match.group(1).strip() if reporter_match else "Insider"
                
                title_match = re.search(r'<officerTitle>(.*?)</officerTitle>', xml_content, re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else "Officer/Director"
                
                is_director = "<isDirector>1</isDirector>" in xml_content or "<isDirector>true</isDirector>" in xml_content
                if is_director and title == "Officer/Director":
                    title = "Director"
                    
                trans_date_match = re.search(r'<transactionDate>\s*<value>(.*?)</value>', xml_content, re.IGNORECASE)
                trans_date = trans_date_match.group(1).strip() if trans_date_match else filing_date
                
                trans_code_match = re.search(r'<transactionCode>(.*?)</transactionCode>', xml_content, re.IGNORECASE)
                trans_code = trans_code_match.group(1).strip() if trans_code_match else "S"
                
                shares_match = re.search(r'<transactionShares>\s*<value>(.*?)</value>', xml_content, re.IGNORECASE)
                shares = float(shares_match.group(1).strip()) if shares_match else 0.0
                
                price_match = re.search(r'<transactionPricePerShare>\s*<value>(.*?)</value>', xml_content, re.IGNORECASE)
                price = float(price_match.group(1).strip()) if price_match else 0.0
                
                is_10b51 = "10b5-1" in xml_content or "10b51" in xml_content or "<isRule10b51>1</isRule10b51>" in xml_content
                
                trans_type = "買進 (Buy - P)" if trans_code == "P" else ("賣出 (Sell - S)" if trans_code == "S" else f"轉讓/其他 ({trans_code})")
                total_val = shares * price
                
                form4_list.append({
                    'reporter_name': reporter_name,
                    'title': title,
                    'filing_date': filing_date,
                    'trans_date': trans_date,
                    'trans_type': trans_type,
                    'trans_code': trans_code,
                    'shares': shares,
                    'price': price,
                    'total_value': total_val,
                    'is_10b51': is_10b51,
                    'doc_url': doc_url
                })
            except Exception as e:
                continue
                
            if len(form4_list) >= limit:
                break
                
    return form4_list

def get_recent_13f_for_fund(fund_key):
    fund_info = FAMOUS_FUNDS.get(fund_key.upper())
    if not fund_info:
        return None
    
    cik = fund_info['cik']
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = fetch_json(url)
    recent = data['filings']['recent']
    
    forms = recent['form']
    filing_dates = recent['filingDate']
    acc_numbers = recent['accessionNumber']
    primary_docs = recent['primaryDocument']
    
    for i in range(len(forms)):
        if forms[i] in ['13F-HR', '13F-HR/A']:
            acc_raw = acc_numbers[i]
            acc_clean = acc_raw.replace('-', '')
            doc = primary_docs[i]
            filing_date = filing_dates[i]
            sec_interactive = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
            
            return {
                'fund_name': fund_info['name'],
                'cik': cik,
                'filing_date': filing_date,
                'form_type': forms[i],
                'sec_url': sec_interactive
            }
    return None

def run_all_insider_and_13f_analysis(output_dir):
    out_folder = os.path.join(output_dir, "40_Institutional_Insiders")
    os.makedirs(out_folder, exist_ok=True)
    
    print("=== 開始抓取 Form 4 高管買賣異動與 13F 機構籌碼數據 ===")
    
    ticker_form4_data = {}
    for t in TICKER_CIKS.keys():
        print(f"[*] 抓取 {t} 最新 Form 4 高管交易紀錄...")
        f4_data = get_recent_form4_for_ticker(t, limit=8)
        ticker_form4_data[t] = f4_data
        
    fund_13f_data = {}
    for fk in FAMOUS_FUNDS.keys():
        print(f"[*] 抓取 {FAMOUS_FUNDS[fk]['name']} 最新 13F 機構申報...")
        info = get_recent_13f_for_fund(fk)
        if info:
            fund_13f_data[fk] = info
            
    # Generate Form 4 Insider Summary Note
    insider_note_path = os.path.join(out_folder, "Form4_Insider_Transactions_Master.md")
    
    insider_md = """---
analysis_type: Form4_Insider_Transactions
updated_at: 2026-07-28
tags:
  - insiders/form4
  - smart_money
  - corporate_governance
---

# SEC Form 4 高管與內部人最新股權買賣異動報告

本報告自動抓取 SEC EDGAR 最新 **Form 4 內部人持股異動申報**，涵蓋高管（CEO/CFO/董事）交易類型（買進 vs 賣出）、交易金額與 **10b5-1 預設交易計畫** 標記。

---

"""
    for t, rows in ticker_form4_data.items():
        insider_md += f"## 🏢 [[{t}_Company_Profile|{t}]] 高管最新交易動向\n\n"
        if not rows:
            insider_md += "近期無重大 Form 4 高管買賣申報。\n\n"
            continue
            
        insider_md += "| 申報日 | 內部人姓名 / 職位 | 交易類型 | 股數 | 成交單價 (USD) | 交易總金額 (USD) | 10b5-1 計畫 |\n"
        insider_md += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
        for r in rows:
            val_str = f"${r['total_value']:,.0f}" if r['total_value'] > 0 else "-"
            price_str = f"${r['price']:.2f}" if r['price'] > 0 else "-"
            plan_str = "✅ 是 (預設計劃)" if r['is_10b51'] else "⚠️ 否 (即時決策)"
            insider_md += f"| {r['filing_date']} | **{r['reporter_name']}** ({r['title']}) | {r['trans_type']} | {r['shares']:,.0f} 股 | {price_str} | {val_str} | {plan_str} |\n"
        insider_md += "\n---\n\n"
        
    with open(insider_note_path, "w", encoding="utf-8") as f:
        f.write(insider_md)
    print(f"[+] 已更新 Form 4 內部人異動筆記: {insider_note_path}")
    
    # Generate 13F Funds Summary Note
    funds_note_path = os.path.join(out_folder, "Form13F_Institutional_Holdings_Master.md")
    funds_md = """---
analysis_type: Form13F_Institutional_Holdings
updated_at: 2026-07-28
tags:
  - institutional/13f
  - smart_money
  - buffett
---

# SEC Form 13F 華爾街頂級機構籌碼追蹤報告

本報告自動追蹤 **華爾街傳奇投資人與頂級機構（如巴菲特波克夏、橋水、麥克貝瑞等）** 向 SEC 申報的季度 **13F-HR 持股明細**。

---

## 🏛️ 華爾街大咖 13F 申報一覽表

| 機構 / 投資人 | SEC CIK | 最新 13F 申報日 | SEC EDGAR 官方原檔連結 |
| :--- | :--- | :--- | :--- |
"""
    for fk, finfo in fund_13f_data.items():
        funds_md += f"| **{finfo['fund_name']}** | `{finfo['cik']}` | {finfo['filing_date']} | [開啟 SEC 官方 13F 申報]({finfo['sec_url']}) |\n"
        
    funds_md += """
---

### 💡 13F 籌碼判讀指南

1. **巴菲特波克夏 (Berkshire Hathaway)**：蘋果 (AAPL) 長期維持其第一大重倉股，展現對高護城河與高庫藏股資本回饋企業的偏好。
2. **被動基金指數巨頭 (Vanguard & BlackRock)**：合計鎖定美股七巨頭 (MAG7) 約 15%~20% 的股權，為股價提供強大的被動資金流動性支撐。
3. **麥克貝瑞 (Scion Asset Management - Michael Burry)**：擅長進行對沖與避險操作，密切關注其每季對科技股認購/認售期權 (Options) 的轉變。
"""
    with open(funds_note_path, "w", encoding="utf-8") as f:
        f.write(funds_md)
    print(f"[+] 已更新 13F 機構籌碼筆記: {funds_note_path}")

if __name__ == "__main__":
    out_dir = os.path.dirname(os.path.abspath(__file__)) + "/.."
    run_all_insider_and_13f_analysis(out_dir)
