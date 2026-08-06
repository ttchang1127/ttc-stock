"""Build-time price fetcher for dashboard.html.

GitHub Pages is static and Yahoo's chart API sends no CORS headers, so the
browser can never fetch quotes directly. Instead we pull real daily closes here
with yfinance and commit the result as prices.json, which dashboard.html loads
as a same-origin file.

Usage:
    python3 scripts/fetch_price_history.py
    python3 scripts/fetch_price_history.py --tickers NVDA TSM --years 2
"""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "prices.json"

# Covers titansData in dashboard.html plus the quick-select chips. GOOGL and
# AMZN are here for the Sortino window in the thesis notes; the dashboard uses
# GOOG and does not track AMZN.
DEFAULT_TICKERS = [
    "NVDA", "GOOG", "GOOGL", "AMZN", "ARM", "MRVL", "COHR", "TSLA",
    "INTC", "NOK", "ONDS", "TSM", "AAPL", "MSFT", "META",
    # Market proxy, needed to regress beta for a CAPM cost of equity.
    "SPY",
    # ETFs in user portfolio
    "VGT", "VOO",
]


def fetch_series(ticker, start, end):
    frame = yf.download(
        ticker,
        start=start.isoformat(),
        end=end.isoformat(),
        interval="1d",
        progress=False,
        auto_adjust=False,
    )
    if frame.empty:
        return None

    closes = frame["Close"]
    # yfinance returns a MultiIndex column frame for single tickers too.
    if hasattr(closes, "columns"):
        closes = closes[closes.columns[0]]
    closes = closes.dropna()
    if closes.empty:
        return None

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in closes.index],
        "closes": [round(float(v), 4) for v in closes.values],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument(
        "--years",
        type=int,
        default=6,
        help="How far back to fetch. MACD needs only a few months of warmup, "
             "but the 5-year Sortino window in the thesis notes needs 5 full "
             "years plus margin.",
    )
    args = parser.parse_args()

    end = date.today() + timedelta(days=1)  # yfinance end is exclusive
    start = end - timedelta(days=365 * args.years)

    series = {}
    failed = []
    for ticker in args.tickers:
        data = fetch_series(ticker, start, end)
        if data is None:
            failed.append(ticker)
            print(f"  {ticker:6s} FAILED (no rows returned)")
            continue
        series[ticker] = data
        print(f"  {ticker:6s} {len(data['dates']):4d} bars  "
              f"{data['dates'][0]} -> {data['dates'][-1]}  "
              f"last close ${data['closes'][-1]:.2f}")

    if not series:
        raise SystemExit("No tickers fetched; refusing to overwrite prices.json")

    # 13-week T-bill yield, the conventional risk-free proxy. Needed as the MAR
    # for a Sortino comparable to what public screeners publish; without it the
    # only alternative is to invent a rate. Fetched before the unchanged check
    # below, which compares it.
    risk_free = None
    rf = fetch_series("^IRX", start, end)
    if rf:
        risk_free = {
            "symbol": "^IRX",
            "description": "13-week US Treasury bill discount rate, percent per annum",
            "dates": rf["dates"],
            "values": rf["closes"],
        }
        print(f"  {'^IRX':6s} {len(rf['dates']):4d} bars  latest {rf['closes'][-1]:.3f}%")
    else:
        print("  ^IRX   FAILED - Sortino against a risk-free MAR will be unavailable")

    # USD/TWD, for tab 3's portfolio P/L in NT$. The rate input there used to
    # default to a number typed by hand with no way to tell how stale it was;
    # fetching it here gives the dashboard a real quote and a real quote date
    # instead of a value someone has to remember to update manually.
    fx_usdtwd = None
    fx = fetch_series("TWD=X", start, end)
    if fx:
        fx_usdtwd = {
            "symbol": "TWD=X",
            "description": "USD/TWD, Yahoo Finance daily close",
            "dates": fx["dates"],
            "values": fx["closes"],
        }
        print(f"  {'TWD=X':6s} {len(fx['dates']):4d} bars  latest {fx['closes'][-1]:.3f}")
    else:
        print("  TWD=X  FAILED - the portfolio tab's FX rate will fall back to manual entry")

    # generated_at changes on every run, so rewriting unconditionally would make
    # the file differ even when the market data is identical -- the nightly job
    # would then commit on weekends and holidays too. Leave the file untouched
    # unless the quotes themselves moved.
    if OUTPUT_PATH.exists():
        try:
            previous = json.loads(OUTPUT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            previous = None
        if (previous is not None and previous.get("series") == series
                and previous.get("risk_free") == risk_free
                and previous.get("fx_usdtwd") == fx_usdtwd):
            print(f"\nNo new quotes; leaving {OUTPUT_PATH.relative_to(REPO_ROOT)} "
                  f"unchanged (fetched {previous.get('generated_at', 'unknown')}).")
            if failed:
                print(f"Missing: {', '.join(failed)}")
            return

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Yahoo Finance via yfinance (daily close, auto_adjust=False)",
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "risk_free": risk_free,
        "fx_usdtwd": fx_usdtwd,
        "series": series,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, separators=(",", ":")) + "\n")

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)} "
          f"({len(series)} tickers, {size_kb:.1f} KB)")
    if failed:
        print(f"Missing: {', '.join(failed)}")


if __name__ == "__main__":
    main()
