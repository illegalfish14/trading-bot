"""
data/candle_buffer.py

Rolling buffer of OHLCV candles per symbol.
Strategies read from here — always get the latest N candles.
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)


class CandleBuffer:
    """
    Maintains a rolling window of closed candles for one symbol.
    Thread-safe for async WebSocket updates + strategy reads.
    """

    def __init__(self, symbol: str, maxlen: int = 100):
        self.symbol  = symbol
        self.maxlen  = maxlen
        self._candles: deque = deque(maxlen=maxlen)
        self._live: dict = {}   # current unclosed candle

    def update(self, candle: dict):
        """Update buffer with latest candle data."""
        if candle.get("closed"):
            self._candles.append(candle)
            self._live = {}
        else:
            self._live = candle

    def get_candles(self, n: int = None) -> list[dict]:
        """
        Return closed candles as a list, oldest first.
        Optionally limit to last n candles.
        """
        candles = list(self._candles)
        if n:
            candles = candles[-n:]
        return candles

    def get_live(self) -> dict:
        """Return the current unclosed candle (may be incomplete)."""
        return self._live.copy()

    def latest_close(self) -> float:
        """Return the most recent closed price."""
        if self._candles:
            return self._candles[-1]["close"]
        return 0.0

    def latest_volume(self) -> float:
        """Return the most recent closed volume."""
        if self._candles:
            return self._candles[-1]["volume"]
        return 0.0

    def is_ready(self, min_candles: int = 30) -> bool:
        """Return True if buffer has enough candles for strategy analysis."""
        return len(self._candles) >= min_candles

    def __len__(self):
        return len(self._candles)

    def __repr__(self):
        return (
            f"CandleBuffer({self.symbol}, "
            f"candles={len(self._candles)}/{self.maxlen}, "
            f"latest={self.latest_close():.2f})"
        )
