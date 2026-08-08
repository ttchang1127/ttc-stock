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
import html as html_lib

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
    c = re.sub(r'</?(div|p|tr|h[1-6]|li|br|table)[^>]*>', '\n', c, flags=re.IGNORECASE)
    c = re.sub(r'</?(td|th)[^>]*>', ' ', c, flags=re.IGNORECASE)
    c = re.sub(r'<[^>]+>', ' ', c)
    # Do this after tag removal so an entity that decodes to '<' cannot
    # reintroduce markup, and use the real table rather than three hand-picked
    # entities -- the previous version left &#8211; and friends in the output.
    c = html_lib.unescape(c)
    # Filings use every space character Unicode offers: TSMC separates ITEM
    # from its number with a thin space, others use figure and en spaces.
    c = re.sub(r'[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]', ' ', c)
    c = c.replace('\u200b', '').replace('\ufeff', '')
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in c.splitlines()]
    return '\n'.join(line for line in lines if line)


# Where each core section starts and where the next one begins. 20-F numbers its
# items differently from 10-K, so foreign private issuers get their own map.
def loose(phrase):
    """Regex for a phrase whose letters may be split by stray spaces.

    Microsoft's 10-K renders headings through nested spans that leave spaces
    inside words -- the text extracts as "ITEM 1A. RIS K FACTORS" and
    "ITEM 1B. UNRESOLVE D STAFF COMMENTS". Matching letter by letter with an
    optional space after each reads those correctly. Only spaces and tabs are
    permitted between letters, never a newline, so a match still cannot span
    two lines and contents-table entries stay excluded.
    """
    out = []
    for ch in phrase:
        out.append(r'[ \t]+' if ch == ' ' else re.escape(ch) + r'[ \t]*')
    return ''.join(out)


def ITEM(number):
    """The "Item 1A." part of a heading, tolerant of spacing and punctuation."""
    return r'item[ \t]*' + loose(number) + r'[\.\:\-–—]?[ \t]*' 
SECTION_SPECS = {
    '10-K': [
        ('Item_1_Business', 'Item 1. Business 業務概述',
         ITEM('1') + loose('business') + r'[^\n]*',
         ITEM('1a') + loose('risk factors') + r'[^\n]*'),
        # Intel and TSMC head the chapter with a bare "Risk Factors" and no
        # item number, so that spelling is an accepted alternative.
        ('Item_1A_Risk_Factors', 'Item 1A. Risk Factors 風險因素',
         ITEM('1a') + loose('risk factors') + r'[^\n]*|' + loose('risk factors') + r'(?=\n)',
         ITEM('1b') + r'unresolved[^\n]*|' + ITEM('2') + loose('propert') + r'[^\n]*'),
        ('Item_7_MD_and_A', "Item 7. MD&A 管理層討論與分析",
         ITEM('7') + r'management.{0,3}s\s*discussion[^\n]*',
         ITEM('7a') + r'quantitative[^\n]*|' + ITEM('8') + loose('financial statements') + r'[^\n]*'),
    ],
    '20-F': [
        ('Item_3D_Risk_Factors', 'Item 3.D Risk Factors 風險因素',
         ITEM('3') + r'd\.?[ \t]*' + loose('risk factors') + r'[^\n]*|'
         + loose('risk factors') + r'(?=\n)',
         ITEM('4') + loose('information on the company') + r'[^\n]*'),
        ('Item_4_Business', 'Item 4. Information on the Company 公司業務',
         ITEM('4') + loose('information on the company') + r'[^\n]*',
         ITEM('4a') + r'unresolved[^\n]*|' + ITEM('5') + loose('operating') + r'[^\n]*'),
        ('Item_5_Operating_Review', 'Item 5. Operating and Financial Review 營運與財務回顧',
         ITEM('5') + loose('operating and financial') + r'[^\n]*',
         ITEM('6') + loose('directors') + r'[^\n]*'),
    ],
}

# Below this a "section" is a table-of-contents line or a cross-reference, not
# the section itself. Risk factor chapters in these filings run tens of
# thousands of characters.
MIN_SECTION_CHARS = 4000

# A span that swallowed the rest of the filing is caught structurally rather
# than by length: Arm's risk factors legitimately run to 265,000 characters,
# and Intel's over-long span is 335,000, so no cap separates them. What does
# separate them is that Intel's contains the heading of a later section --
# Intel reorganises its 10-K so Item 1B and Item 2 appear only in an index at
# the very end, and the span runs straight through Item 7 to reach them.


def heading_positions(text, pattern):
    """Offsets where the pattern appears as a section heading, not a mention.

    A 10-K names each item several times: once in the table of contents, several
    times in cross-references inside other sections ("see Item 1A Risk Factors
    of this Annual Report"), and once at the section itself. Two properties
    separate the real heading from the rest, and together they leave exactly one
    match per item across every filing here:

      it begins a line -- a cross-reference sits mid-sentence;
      it contains no newline -- a contents-table entry is split across cells,
      giving "Item 1A.\\nRisk Factors\\n9".

    Patterns end in [^\\n]* so the whole heading line is consumed, which keeps
    long headings such as Item 7's from being treated as a partial match.
    """
    out = []
    for m in re.finditer(pattern, text, re.I):
        if "\n" in m.group(0):
            continue
        if text.rfind("\n", 0, m.start()) + 1 != m.start():
            continue
        # A contents entry that survived the newline test is followed by its
        # page number on the next line; a real heading is followed by prose.
        nxt = text[m.end():].lstrip("\n").split("\n", 1)[0].strip()
        if re.fullmatch(r"[0-9ivxlIVXL\-–—\.]{1,6}", nxt or "x"):
            continue
        out.append(m.start())
    return out


def extract_section(text, start_pattern, end_pattern, forbidden=()):
    """Text between a section's heading and the following section's heading.

    Returns None rather than a guess when either heading is missing, when the
    span is too short to be the chapter, or when it contains the heading of a
    section that should have come after it. A filing this fails on should be
    reported, not filled in with whatever happened to lie between two
    unrelated offsets.
    """
    starts = heading_positions(text, start_pattern)
    ends = heading_positions(text, end_pattern)
    if not starts:
        return None
    for s in starts:
        following = [e for e in ends if e > s]
        if not following:
            continue
        body = text[s:following[0]].strip()
        if len(body) < MIN_SECTION_CHARS:
            continue
        inner = body[MIN_SECTION_CHARS:]          # skip the section's own heading
        if any(heading_positions(inner, pat) for pat in forbidden):
            continue
        return body
    return None


def write_sections(sections_dir, ticker, name, year, form_type, note_name,
                   interactive_url, html_content):
    """Split one filing into its core sections. Returns the names written."""
    text = clean_html_to_text(html_content)
    written = []
    specs = SECTION_SPECS.get(form_type, [])
    for slug, title, start_pat, end_pat in specs:
        others = [sp for sl, _, sp, _ in specs if sl != slug]
        body = extract_section(text, start_pat, end_pat, forbidden=others)
        if not body:
            print(f"    [!] {slug}: 找不到符合的章節範圍，略過（不寫入空檔）")
            continue
        path = os.path.join(sections_dir, f"{ticker}_{year}_{slug}.md")
        content = f"""---
ticker: {ticker}
year: {year}
section: {slug}
form_type: "{form_type}"
source: SEC EDGAR 原文自動拆解
characters: {len(body)}
tags:
  - sec/{form_type.lower().replace('-', '')}_section
  - company/{ticker.lower()}
---

# {name} ({ticker}) - {year} {form_type} [{title}] 全文拆解

- **所屬報告**: [[{note_name}|{ticker} {year} {form_type} 主筆記]]
- **SEC iXBRL 互動視圖**: [SEC 線上檢視器]({interactive_url})
- **本檔為程式自動拆解的原文**，未經改寫或摘要；如與 SEC 原文不符，以原文為準。

---

## 📄 章節全文內容

{body}
"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        written.append((slug, len(body)))
        print(f"    [✓] {slug}: {len(body):,} 字元")
    return written

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
            
            if split_sections and html_content:
                print(f"[*] 拆解核心章節 ({form_type})...")
                write_sections(sections_dir, ticker, name, year, form_type,
                               f"{ticker}_{year}_{form_type.replace('-','')}",
                               sec_interactive_url, html_content)

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
