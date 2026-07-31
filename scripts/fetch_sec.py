#!/usr/bin/env python3
"""
SEC Filing Downloader & Obsidian Note Generator
Supports:
  - Form Types: 10-K (US Domestic) & 20-F (Foreign Private Issuers like TSM)
  - Option B: Official SEC iXBRL Interactive View Links
  - Option C: Core Section Splitting

Author: Sec_kb Assistant
"""

import sys
import os
import json
import urllib.request
import argparse
import re

SEC_HEADERS = {
    'User-Agent': 'SecKBResearch user@example.com'
}

def get_company_cik(ticker):
    ticker = ticker.upper()
    url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        for item in data.values():
            if item['ticker'] == ticker:
                cik_str = str(item['cik_str']).zfill(10)
                return cik_str, item['title']
    raise ValueError(f"Ticker {ticker} not found in SEC company database.")

def fetch_company_submissions(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def download_file(url, target_path):
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        content = resp.read()
        with open(target_path, 'wb') as f:
            f.write(content)
    return content

def clean_html_to_text(html_str):
    c = re.sub(r'<style[^>]*>.*?</style>', '', html_str, flags=re.DOTALL | re.IGNORECASE)
    c = re.sub(r'<script[^>]*>.*?</script>', '', c, flags=re.DOTALL | re.IGNORECASE)
    c = re.sub(r'</?(div|p|tr|h[1-6]|li|br)[^>]*>', '\n', c, flags=re.IGNORECASE)
    c = re.sub(r'&#160;', ' ', c)
    c = re.sub(r'&nbsp;', ' ', c)
    c = re.sub(r'&amp;', '&', c)
    c = re.sub(r'<[^>]+>', ' ', c)
    lines = [line.strip() for line in c.splitlines() if line.strip()]
    return '\n\n'.join(lines)

def generate_obsidian_notes(ticker, cik, name, filings, output_dir, max_years=5, download_raw=True, split_sections=True):
    company_dir = os.path.join(output_dir, "10_Companies", ticker)
    filings_dir = os.path.join(output_dir, "20_Filings", ticker)
    raw_dir = os.path.join(filings_dir, "raw")
    sections_dir = os.path.join(filings_dir, "sections")
    
    os.makedirs(company_dir, exist_ok=True)
    os.makedirs(filings_dir, exist_ok=True)
    if download_raw:
        os.makedirs(raw_dir, exist_ok=True)
    if split_sections:
        os.makedirs(sections_dir, exist_ok=True)

    recent = filings['filings']['recent']
    forms = recent['form']
    accession_numbers = recent['accessionNumber']
    filing_dates = recent['filingDate']
    primary_docs = recent['primaryDocument']
    report_dates = recent.get('reportDate', filing_dates)

    count = 0
    filing_notes_info = []

    target_forms = ['10-K', '20-F']

    for i in range(len(forms)):
        form_type = forms[i]
        if form_type in target_forms:
            acc_raw = accession_numbers[i]
            acc_clean = acc_raw.replace('-', '')
            doc = primary_docs[i]
            filing_date = filing_dates[i]
            report_date = report_dates[i] if i < len(report_dates) else filing_date
            year = filing_date.split('-')[0]
            sec_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
            sec_interactive_url = f"https://www.sec.gov/ix?doc=/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"

            raw_file_rel = ""
            raw_file_size = ""
            html_content = None
            if download_raw or split_sections:
                raw_filename = f"{ticker}_{year}_{form_type.replace('-','')}_raw.html"
                raw_filepath = os.path.join(raw_dir, raw_filename)
                print(f"[*] 下載/讀取原生 {form_type} HTML 檔案: {raw_filename}...")
                if not os.path.exists(raw_filepath):
                    html_bytes = download_file(sec_url, raw_filepath)
                    html_content = html_bytes.decode('utf-8', errors='ignore')
                else:
                    with open(raw_filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        html_content = f.read()
                
                size_mb = round(os.path.getsize(raw_filepath) / (1024 * 1024), 2)
                raw_file_size = f"{size_mb} MB"
                raw_file_rel = f"raw/{raw_filename}"
                print(f"[✓] 原生 HTML 準備完畢 ({raw_file_size})")

            filename = f"{ticker}_{year}_{form_type.replace('-','')}.md"
            filepath = os.path.join(filings_dir, filename)

            raw_link_str = f"- **本機完整原文 HTML**: [{raw_filename}]({raw_file_rel}) (檔案大小: {raw_file_size})" if raw_file_rel else ""

            content = f"""---
ticker: {ticker}
company_name: "{name}"
cik: "{cik}"
form_type: "{form_type}"
year: {year}
filing_date: {filing_date}
report_date: {report_date}
accession_number: "{acc_raw}"
sec_url: "{sec_url}"
sec_interactive_url: "{sec_interactive_url}"
raw_file: "{raw_file_rel}"
tags:
  - sec/{form_type.lower().replace('-','')}
  - company/{ticker.lower()}
  - financial_report
---

# {name} ({ticker}) - {year} {form_type} 年度報告

## 📌 報告基本資訊
- **公司名稱**: {name}
- **股票代號**: [[{ticker}_Company_Profile|{ticker}]]
- **中央索引號 (CIK)**: `{cik}`
- **報告類型**: {form_type} (Annual Report)
- **SEC 申報日期**: `{filing_date}`

---

## 🌐 方案 B: 官方全功能線上互動檢視 (SEC iXBRL)
- 🚀 **[開啟 SEC iXBRL 互動視圖（支援左側目錄點擊跳轉與全文搜尋）]({sec_interactive_url})**
- 📄 **[SEC 原生 HTML 文件下載連結]({sec_url})**
{raw_link_str}

---

## 🔗 關聯筆記
- **公司主頁**: [[{ticker}_Company_Profile]]
"""
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            filing_notes_info.append({
                'year': year,
                'filing_date': filing_date,
                'form_type': form_type,
                'note_name': f"{ticker}_{year}_{form_type.replace('-','')}"
            })
            count += 1
            print(f"[+] 已更新年度主筆記: {filename}\n")
            if count >= max_years:
                break

    # 建立 Company Profile
    profile_path = os.path.join(company_dir, f"{ticker}_Company_Profile.md")
    links_str = "\n".join([f"- [[{item['note_name']}|{item['year']} {item['form_type']} 報告]] (申報日: {item['filing_date']})" for item in filing_notes_info])
    
    profile_content = f"""---
ticker: {ticker}
company_name: "{name}"
cik: "{cik}"
sector: Semiconductors
tags:
  - company/{ticker.lower()}
  - sec/company
---

# {name} ({ticker}) 公司主頁

## 🏢 公司資訊
- **股票代號**: `{ticker}`
- **公司全稱**: {name}
- **SEC CIK**: `{cik}`
- **SEC 官方查詢頁面**: [SEC EDGAR Browse](https://www.sec.gov/edgar/browse/?CIK={cik})

---

## 📑 近年 {target_forms} 報告列表
{links_str}
"""
    with open(profile_path, 'w', encoding='utf-8') as f:
        f.write(profile_content)
    print(f"[+] 已更新公司主頁筆記: {ticker}_Company_Profile.md")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SEC Filing Downloader to Obsidian Notes")
    parser.add_argument("ticker", help="Company Stock Ticker (e.g. TSM)")
    parser.add_argument("--years", type=int, default=5, help="Number of years to fetch (default: 5)")
    parser.add_argument("--outdir", default=os.path.dirname(os.path.abspath(__file__)) + "/..", help="Output Obsidian Vault directory")
    parser.add_argument("--download-raw", action="store_true", help="Download raw HTML file locally")
    parser.add_argument("--split-sections", action="store_true", help="Split into section notes")
    args = parser.parse_args()

    print(f"正在查詢 SEC 資料庫獲取 {args.ticker} 的資訊...")
    cik, name = get_company_cik(args.ticker)
    print(f"找到公司: {name} (CIK: {cik})")
    
    filings = fetch_company_submissions(cik)
    generate_obsidian_notes(args.ticker, cik, name, filings, args.outdir, args.years, download_raw=args.download_raw, split_sections=args.split_sections)
    print("完成！所有筆記、互動連結已生成至 Sec_kb 資料夾中。")
