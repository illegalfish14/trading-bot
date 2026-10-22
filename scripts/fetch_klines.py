"""
scripts/fetch_klines.py

Download historical 1m candles from Binance's public REST API (no API key)
and save them as CSV for the backtester.

  python scripts/fetch_klines.py --symbol BTCUSDT --days 7 --out history/btcusdt_1m.csv
"""

import argparse
import csv
import json
import time
import urllib.request
from pathlib import Path

URL   = "https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start}&limit=1000"
STEP  = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def fetch(symbol: str, interval: str, days: int) -> list[list]:
    end   = int(time.time() * 1000)
    start = end - days * 86_400_000
    rows  = []
    while start < end:
        with urllib.request.urlopen(URL.format(symbol=symbol, interval=interval, start=start)) as resp:
            batch = json.load(resp)
        if not batch:
            break
        rows.extend(batch)
        start = batch[-1][0] + STEP[interval]
        time.sleep(0.2)   # stay well inside the public rate limit
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",   default="BTCUSDT")
    parser.add_argument("--interval", default="1m", choices=STEP)
    parser.add_argument("--days",     default=7, type=int)
    parser.add_argument("--out",      default="history/btcusdt_1m.csv")
    args = parser.parse_args()

    rows = fetch(args.symbol, args.interval, args.days)
    out  = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for r in rows:
            writer.writerow(r[:6])
    print(f"Saved {len(rows):,} candles to {out}")


if __name__ == "__main__":
    main()
