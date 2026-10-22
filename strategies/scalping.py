"""
strategies/scalping.py

G1 primary strategy. Momentum-based scalping on 1m/5m candles.
Targets 0.3–0.5% moves on BTC/ETH perpetual futures.
Runs 8–15 trades per day depending on signal quality.
"""

import logging
from dataclasses import dataclass
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ScalpSignal:
    symbol:     str
    direction:  str         # "long" or "short"
    strength:   float       # 0.0 – 1.0
    entry_price: float
    take_profit: float
    stop_loss:   float
    reason:     str


class ScalpingStrategy:
    """
    Simple momentum scalping strategy.
    Uses EMA crossover + RSI + volume confirmation.
    Designed for G1 (50–200) but usable in G2.

    Signal logic:
    - EMA9 crosses above EMA21 → long signal
    - EMA9 crosses below EMA21 → short signal
    - RSI filter: long only if RSI < 65, short only if RSI > 35
    - Volume confirmation: current volume > 1.5x average volume
    """

    # Strategy parameters
    EMA_FAST       = 9
    EMA_SLOW       = 21
    RSI_PERIOD     = 14
    RSI_LONG_MAX   = 65
    RSI_SHORT_MIN  = 35
    VOLUME_MULT    = 1.5
    TP_PCT         = 0.004   # 0.4% take profit
    SL_PCT         = 0.002   # 0.2% stop loss (2:1 R/R)

    def __init__(self):
        self.last_signal: Optional[ScalpSignal] = None
        logger.info("ScalpingStrategy initialised")

    def analyse(self, candles: list[dict], symbol: str = "BTC/USDT") -> Optional[ScalpSignal]:
        """
        Analyse candle data and return a signal if conditions are met.

        candles: list of dicts with keys: open, high, low, close, volume
                 ordered oldest → newest, minimum 30 candles required
        """
        if len(candles) < 30:
            logger.warning(f"Insufficient candles: {len(candles)} (need 30+)")
            return None

        closes  = np.array([c["close"]  for c in candles])
        volumes = np.array([c["volume"] for c in candles])

        ema_fast = self._ema(closes, self.EMA_FAST)
        ema_slow = self._ema(closes, self.EMA_SLOW)
        rsi      = self._rsi(closes, self.RSI_PERIOD)
        avg_vol  = volumes[:-1].mean()
        cur_vol  = volumes[-1]

        current_price = float(closes[-1])
        cross_up   = ema_fast[-2] <= ema_slow[-2] and ema_fast[-1] > ema_slow[-1]
        cross_down = ema_fast[-2] >= ema_slow[-2] and ema_fast[-1] < ema_slow[-1]
        vol_ok     = cur_vol > avg_vol * self.VOLUME_MULT

        if cross_up and rsi[-1] < self.RSI_LONG_MAX and vol_ok:
            signal = ScalpSignal(
                symbol      = symbol,
                direction   = "long",
                strength    = self._signal_strength(rsi[-1], "long", cur_vol, avg_vol),
                entry_price = current_price,
                take_profit = round(current_price * (1 + self.TP_PCT), 2),
                stop_loss   = round(current_price * (1 - self.SL_PCT), 2),
                reason      = f"EMA crossover UP | RSI: {rsi[-1]:.1f} | Vol: {cur_vol/avg_vol:.1f}x"
            )
            self.last_signal = signal
            logger.info(f"LONG signal — {signal.reason}")
            return signal

        if cross_down and rsi[-1] > self.RSI_SHORT_MIN and vol_ok:
            signal = ScalpSignal(
                symbol      = symbol,
                direction   = "short",
                strength    = self._signal_strength(rsi[-1], "short", cur_vol, avg_vol),
                entry_price = current_price,
                take_profit = round(current_price * (1 - self.TP_PCT), 2),
                stop_loss   = round(current_price * (1 + self.SL_PCT), 2),
                reason      = f"EMA crossover DOWN | RSI: {rsi[-1]:.1f} | Vol: {cur_vol/avg_vol:.1f}x"
            )
            self.last_signal = signal
            logger.info(f"SHORT signal — {signal.reason}")
            return signal

        return None

    # ------------------------------------------------------------------
    # Indicator calculations
    # ------------------------------------------------------------------

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        alpha  = 2 / (period + 1)
        result = np.zeros_like(data)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    def _rsi(self, data: np.ndarray, period: int) -> np.ndarray:
        delta = np.diff(data)
        gains = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta < 0, -delta, 0.0)

        avg_gain = np.convolve(gains, np.ones(period) / period, mode="valid")
        avg_loss = np.convolve(losses, np.ones(period) / period, mode="valid")

        with np.errstate(divide="ignore", invalid="ignore"):
            rs = np.where(avg_loss == 0, 100.0, avg_gain / avg_loss)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _signal_strength(
        self, rsi: float, direction: str, cur_vol: float, avg_vol: float
    ) -> float:
        """Score signal strength 0–1 based on RSI extremity and volume."""
        vol_score = min((cur_vol / avg_vol - 1.5) / 2.0, 1.0)
        vol_score = max(vol_score, 0.0)

        if direction == "long":
            rsi_score = max(0.0, (self.RSI_LONG_MAX - rsi) / self.RSI_LONG_MAX)
        else:
            rsi_score = max(0.0, (rsi - self.RSI_SHORT_MIN) / (100 - self.RSI_SHORT_MIN))

        return round((vol_score + rsi_score) / 2, 3)
