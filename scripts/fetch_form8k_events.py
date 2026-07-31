#!/usr/bin/env python3
"""
SEC Form 8-K (Current Reports & Major Corporate Events) Downloader & Parser
Integrates into Sec_kb Financial Framework.
"""

import sys
import os
import json
import urllib.request
import re
import argparse

SEC_HEADERS = {
    'User-Agent': 'SecKBResearch user@example.com'
}

TICKER_CIKS = {
    'AAPL': '0000320193',
    'NVDA': '0001045810',
    'AMZN': '0001018724',
    'MSFT': '0000789019',
    'META': '0001326801',
    'TSLA': '0001318605',
    'GOOGL':'0001652044',
    'TSM':  '0001046179' # Form 6-K for TSM foreign issuer
}

ITEM_DESCRIPTIONS = {
    '2.02': '📊 季度業績發布 (Results of Operations / Earnings Release)',
    '5.02': '👔 高管或董事人事異動 (Officer/Director Change)',
    '7.01': '🎤 法說會與投資人會議簡報 (Regulation FD / Presentation Deck)',
    '8.01': '⚡ 重大即時事件公告 (Other Major Corporate Events)',
    '1.01': '🤝 重大商業合約或收購簽署 (Material Definitive Agreement)',
    '5.03': '📜 公司章程修訂 (Articles of Incorporation/Bylaws)'
}

def fetch_json(url):
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def fetch_text(url):
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode('utf-8', errors='ignore')

def get_recent_8k_events_for_ticker(ticker, limit=6):
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
    items_list = recent.get('items', [[]] * len(forms))
    
    target_forms = ['8-K', '8-K/A', '6-K']
    
    events = []
    for i in range(len(forms)):
        form_type = forms[i]
        if form_type in target_forms:
            acc_raw = acc_numbers[i]
            acc_clean = acc_raw.replace('-', '')
            doc = primary_docs[i]
            filing_date = filing_dates[i]
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
            interactive_url = f"https://www.sec.gov/ix?doc=/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
            
            raw_items = items_list[i] if i < len(items_list) else ""
            item_desc_str = ""
            if isinstance(raw_items, list):
                desc_items = [ITEM_DESCRIPTIONS.get(it, f"Item {it}") for it in raw_items]
                item_desc_str = ", ".join(desc_items)
            elif isinstance(raw_items, str) and raw_items:
                its = [it.strip() for it in raw_items.split(',') if it.strip()]
                desc_items = [ITEM_DESCRIPTIONS.get(it, f"Item {it}") for it in its]
                item_desc_str = ", ".join(desc_items)
            else:
                item_desc_str = "重大即時事項申報"
                
            events.append({
                'ticker': ticker,
                'form_type': form_type,
                'filing_date': filing_date,
                'items_summary': item_desc_str,
                'doc_url': doc_url,
                'interactive_url': interactive_url
            })
            
            if len(events) >= limit:
                break
                
    return events

def run_all_8k_analysis(output_dir):
    out_folder = os.path.join(output_dir, "50_Form8K_Corporate_Events")
    os.makedirs(out_folder, exist_ok=True)
    
    print("=== 開始抓取 SEC Form 8-K 法說會與第一手重大新聞報告 ===")
    
    ticker_events = {}
    for t in TICKER_CIKS.keys():
        print(f"[*] 抓取 {t} 最新 Form 8-K / 6-K 重大事件申報...")
        evs = get_recent_8k_events_for_ticker(t, limit=6)
        ticker_events[t] = evs
        
    master_note_path = os.path.join(out_folder, "Form8K_Major_Events_Master.md")
    
    md_content = """---
analysis_type: Form8K_Major_Corporate_Events
updated_at: 2026-07-28
tags:
  - corporate_events/form8k
  - earnings_release
  - real_time_news
---

# SEC Form 8-K / 6-K 法說會與第一手重大事件總覽報告

本報告自動抓取 SEC EDGAR 最新 **Form 8-K（美國公司重大即時事件）** 與 **Form 6-K（外商公司重大訊息）**。包含 **季度法說會業績發布 (Item 2.02)**、**高管人事異動 (Item 5.02)**、**法說會 Slide 簡報 (Item 7.01)** 與 **重大收購簽署 (Item 1.01)**。

---

"""
    for t, ev_list in ticker_events.items():
        md_content += f"## ⚡ [[{t}_Company_Profile|{t}]] 最新 8-K / 6-K 重大公告\n\n"
        if not ev_list:
            md_content += "近期無重大 Form 8-K 公告。\n\n"
            continue
            
        md_content += "| 申報日期 | 報告類型 | 事件分類 / Item 說明 | SEC EDGAR 原檔連結 |\n"
        md_content += "| :--- | :--- | :--- | :--- |\n"
        
        for ev in ev_list:
            md_content += f"| `{ev['filing_date']}` | **{ev['form_type']}** | {ev['items_summary']} | [檢視 SEC 原檔公告]({ev['doc_url']}) |\n"
        md_content += "\n---\n\n"
        
    with open(master_note_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"[+] 已更新 Form 8-K 重大事件筆記: {master_note_path}")

if __name__ == "__main__":
    out_dir = os.path.dirname(os.path.abspath(__file__)) + "/.."
    run_all_8k_analysis(out_dir)
