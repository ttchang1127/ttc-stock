"""Compare each company's risk factors against the prior year's filing.

The vault holds 41 extracts of Item 1A (Item 3.D for 20-F filers) and used
them for one line of provenance. Comparing consecutive years is the one thing
that data can say which nothing else here can: what a company started warning
about, and what it stopped warning about. The second is usually the more
interesting -- adding a risk is cheap, and removing one is a statement.

What this is: a comparison of paragraphs. Not of meaning.

A filing rewrites its risk chapter every year, so most paragraphs return with
small edits. Those are matched and reported as unchanged or reworded. Only a
paragraph with no counterpart above a low similarity threshold is called added
or removed, and even then it may be a restructuring rather than a new risk --
the output says so, and the point is to send a reader to the passage, not to
conclude anything for them.

    python3 scripts/diff_risk_factors.py
    python3 scripts/diff_risk_factors.py --tickers NVDA TSLA
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FILINGS_DIR = REPO_ROOT / "20_Filings"
OUTPUT_PATH = REPO_ROOT / "risk_changes.json"

# Shorter than this is a heading, a page number or a caption, not a risk.
MIN_PARAGRAPH = 200

# Jaccard overlap on word sets. Above SAME the paragraph is the same risk with
# a year's worth of edits; between REWORDED and SAME it is a rewrite of
# something that was there; below REWORDED it has no counterpart at all.
SAME = 0.60
REWORDED = 0.32

# Page furniture that survives the extract.
NOISE = re.compile(r"^(table of contents|\d+|.{0,40}form 10-k.{0,20})$", re.I)


def reflow(lines):
    """Rejoin lines that a fixed-width layout split mid-sentence.

    Ondas and Nokia render their filings at a fixed column width, so every line
    breaks at about 135 characters regardless of where the sentence is. Without
    rejoining them no line reaches the paragraph threshold and the comparison
    sees an empty chapter. A line that does not end a sentence continues into
    the next one; a filing that is not wrapped ends its paragraphs with
    punctuation already and is left alone.
    """
    out, buffer = [], ""
    for line in lines:
        buffer = f"{buffer} {line}".strip() if buffer else line
        if line.endswith((".", "?", "!", ":", "”", '"', ";")):
            out.append(buffer)
            buffer = ""
    if buffer:
        out.append(buffer)
    return out


def paragraphs(path):
    """Substantive paragraphs, dropping furniture and mid-sentence fragments."""
    body = path.read_text().split("## 📄 章節全文內容\n\n", 1)[-1]
    raw = [l.strip() for l in body.split("\n") if l.strip()]
    out = []
    for line in reflow(raw):
        if len(line) < MIN_PARAGRAPH or NOISE.match(line):
            continue
        # A page break splits a paragraph, and the tail starts mid-sentence.
        # Reporting "unable to do so, we may have to curtail..." as a new risk
        # is noise; the head of the same paragraph is reported anyway.
        if not (line[0].isupper() or line[0] in "•“\"'"):
            continue
        out.append(line)
    return out


def words(text):
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def best_overlap(target, pool):
    best = 0.0
    for other in pool:
        union = target | other
        if not union:
            continue
        score = len(target & other) / len(union)
        if score > best:
            best = score
            if best >= SAME:
                break
    return best


def extracts_for(ticker):
    """Risk-factor extracts for one company, oldest first."""
    return sorted(FILINGS_DIR.glob(f"{ticker}/sections/{ticker}_*_Item_*Risk_Factors.md"))


def year_of(path):
    m = re.search(r"_(\d{4})_Item", path.name)
    return m.group(1) if m else "?"


def compare(previous, latest):
    old = [(p, words(p)) for p in paragraphs(previous)]
    new = [(p, words(p)) for p in paragraphs(latest)]

    unchanged = [p for p, w in new if best_overlap(w, [x for _, x in old]) >= SAME]
    candidates_new = [(p, w) for p, w in new
                      if best_overlap(w, [x for _, x in old]) < SAME]
    candidates_gone = [(p, w) for p, w in old
                       if best_overlap(w, [x for _, x in new]) < SAME]

    gone_words = [w for _, w in candidates_gone]
    new_words = [w for _, w in candidates_new]
    reworded = [p for p, w in candidates_new if best_overlap(w, gone_words) >= REWORDED]
    added = [p for p, w in candidates_new if best_overlap(w, gone_words) < REWORDED]
    removed = [p for p, w in candidates_gone if best_overlap(w, new_words) < REWORDED]

    return {
        "paragraphs_previous": len(old),
        "paragraphs_latest": len(new),
        "unchanged": len(unchanged),
        "reworded": len(reworded),
        "added": added,
        "removed": removed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    args = parser.parse_args()

    tickers = args.tickers or sorted(
        p.name for p in FILINGS_DIR.iterdir() if p.is_dir())
    results = {}

    print(f"{'ticker':8s}{'比較':>16s}{'段落':>10s}{'不變':>7s}{'改寫':>7s}{'新增':>7s}{'刪除':>7s}")
    for ticker in tickers:
        files = extracts_for(ticker)
        if len(files) < 2:
            results[ticker] = {
                "status": "資料不足",
                "reason": ("僅有 {} 個年度的原文拆解，無法比較"
                           .format(len(files)) if files else "無原文拆解"),
                "years_available": [year_of(f) for f in files],
            }
            print(f"{ticker:8s}{'—':>16s}  {results[ticker]['reason']}")
            continue

        previous, latest = files[-2], files[-1]
        diff = compare(previous, latest)
        results[ticker] = {
            "status": "已比較",
            "previous_year": year_of(previous),
            "latest_year": year_of(latest),
            "previous_file": str(previous.relative_to(REPO_ROOT)),
            "latest_file": str(latest.relative_to(REPO_ROOT)),
            "basis": "段落層級的字詞重疊比對；相似度 ≥{:.0%} 視為同一段，"
                     "{:.0%}~{:.0%} 視為改寫，低於 {:.0%} 才算新增或刪除"
                     .format(SAME, REWORDED, SAME, REWORDED),
            "caveat": "這是文字比對，不是語意比對。段落重組也可能被判為新增或刪除，"
                      "請以原文為準。",
            **diff,
        }
        print(f"{ticker:8s}{diff['paragraphs_previous']:>7d}→{diff['paragraphs_latest']:<8d}"
              f"{'':>2s}{diff['unchanged']:>7d}{diff['reworded']:>7d}"
              f"{len(diff['added']):>7d}{len(diff['removed']):>7d}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "20_Filings/*/sections/*Risk_Factors.md（由 fetch_sec.py 自 SEC 原文拆解）",
        "thresholds": {"same": SAME, "reworded": REWORDED,
                       "min_paragraph_chars": MIN_PARAGRAPH},
        "companies": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    comparable = sum(1 for v in results.values() if v["status"] == "已比較")
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)} "
          f"（{comparable} / {len(results)} 家可比較）")


if __name__ == "__main__":
    main()
