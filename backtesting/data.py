"""
backtesting/data.py

Candle sources for the backtester.

- load_csv:          OHLCV candles from a CSV (Binance kline export format,
                     or any CSV with timestamp/open/high/low/close/volume columns)
- synthetic_candles: a seeded random walk with volatility clustering and
                     volume spikes, so the backtester runs offline with no data
"""

import csv
from pathlib import Path

import numpy as np

BINANCE_KLINE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def load_csv(path: str | Path) -> list[dict]:
    """Load candles from a CSV, oldest first."""
    candles = []
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    has_header = not rows[0][0].strip().isdigit()
    if has_header:
        header = [h.strip().lower() for h in rows[0]]
        rows   = rows[1:]
        idx    = {col: header.index(col) for col in BINANCE_KLINE_COLUMNS}
    else:
        idx = {col: i for i, col in enumerate(BINANCE_KLINE_COLUMNS)}

    for row in rows:
        ts = int(float(row[idx["timestamp"]]))
        if ts > 10**14:          # newer Binance exports use microseconds
            ts //= 1000
        candles.append({
            "timestamp": ts,
            "open":      float(row[idx["open"]]),
            "high":      float(row[idx["high"]]),
            "low":       float(row[idx["low"]]),
            "close":     float(row[idx["close"]]),
            "volume":    float(row[idx["volume"]]),
            "closed":    True,
        })

    candles.sort(key=lambda c: c["timestamp"])
    return candles


def synthetic_candles(
    n:           int   = 10_000,
    start_price: float = 65_000.0,
    seed:        int   = 42,
    interval_ms: int   = 60_000,
    start_ms:    int   = 1_704_067_200_000,   # 2024-01-01 00:00 UTC
) -> list[dict]:
    """
    Generate n one-minute candles from a seeded random walk.

    Volatility follows a slow mean-reverting process so there are calm and
    choppy regimes, and volume is correlated with the size of each move.
    Synthetic data is for exercising the machinery, not for judging a strategy.
    """
    rng = np.random.default_rng(seed)

    vol = np.empty(n)
    vol[0] = 0.0008
    for i in range(1, n):
        vol[i] = max(0.0002, vol[i - 1] + 0.02 * (0.0008 - vol[i - 1]) + rng.normal(0, 0.00005))

    returns = rng.normal(0, vol)
    closes  = start_price * np.exp(np.cumsum(returns))
    opens   = np.concatenate([[start_price], closes[:-1]])

    wick    = np.abs(rng.normal(0, vol)) * closes
    highs   = np.maximum(opens, closes) + wick
    lows    = np.minimum(opens, closes) - np.abs(rng.normal(0, vol)) * closes

    base_volume = rng.lognormal(mean=3.0, sigma=0.4, size=n)
    volumes     = base_volume * (1 + 400 * np.abs(returns))

    return [
        {
            "timestamp": start_ms + i * interval_ms,
            "open":      float(opens[i]),
            "high":      float(highs[i]),
            "low":       float(lows[i]),
            "close":     float(closes[i]),
            "volume":    float(volumes[i]),
            "closed":    True,
        }
        for i in range(n)
    ]
