"""
data/binance_feed.py

Live WebSocket connection to Binance.
Streams real-time 1m kline (candle) data for specified symbols.
Feeds into CandleBuffer for strategy consumption.
"""

import asyncio
import json
import logging
import websockets
from datetime import datetime
from data.candle_buffer import CandleBuffer

logger = logging.getLogger(__name__)


BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"


class BinanceFeed:
    """
    Connects to Binance WebSocket and streams live candle data.
    Supports multiple symbols simultaneously via combined stream.

    Usage:
        feed = BinanceFeed(symbols=["BTCUSDT", "ETHUSDT"], interval="1m")
        asyncio.run(feed.start())
    """

    def __init__(
        self,
        symbols:  list[str] = None,
        interval: str = "1m",
        on_candle = None
    ):
        self.symbols  = symbols or ["BTCUSDT"]
        self.interval = interval
        self.buffers: dict[str, CandleBuffer] = {
            s: CandleBuffer(symbol=s, maxlen=100) for s in self.symbols
        }
        self.on_candle  = on_candle   # optional callback on closed candle
        self.running    = False
        self._ws        = None

        logger.info(f"BinanceFeed initialised — symbols: {self.symbols} | interval: {interval}")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self):
        """Start the WebSocket feed. Runs until stopped."""
        self.running = True
        url = self._build_url()
        logger.info(f"Connecting to Binance WebSocket: {url}")

        while self.running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    self._ws = ws
                    logger.info("WebSocket connected")
                    await self._listen(ws)
            except websockets.ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e} — reconnecting in 3s")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WebSocket error: {e} — reconnecting in 5s")
                await asyncio.sleep(5)

    def stop(self):
        """Stop the feed gracefully."""
        self.running = False
        logger.info("BinanceFeed stopping")

    def get_buffer(self, symbol: str) -> "CandleBuffer":
        """Return the candle buffer for a given symbol."""
        return self.buffers.get(symbol)

    def get_candles(self, symbol: str) -> list[dict]:
        """Return latest candles for a symbol, ready for strategy consumption."""
        buf = self.buffers.get(symbol)
        return buf.get_candles() if buf else []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _listen(self, ws):
        async for message in ws:
            if not self.running:
                break
            try:
                data = json.loads(message)
                self._process(data)
            except Exception as e:
                logger.error(f"Message processing error: {e}")

    def _process(self, data: dict):
        """Parse incoming kline message and update buffer."""
        stream = data.get("stream", "")
        kline  = data.get("data", {}).get("k", {})

        if not kline:
            return

        symbol   = kline.get("s", "")
        is_closed = kline.get("x", False)   # True when candle is closed

        candle = {
            "symbol":    symbol,
            "open":      float(kline.get("o", 0)),
            "high":      float(kline.get("h", 0)),
            "low":       float(kline.get("l", 0)),
            "close":     float(kline.get("c", 0)),
            "volume":    float(kline.get("v", 0)),
            "timestamp": int(kline.get("t", 0)),
            "closed":    is_closed,
        }

        buf = self.buffers.get(symbol)
        if buf:
            buf.update(candle)

        # Fire callback only on closed candles — avoids noisy mid-candle signals
        if is_closed and self.on_candle:
            self.on_candle(symbol, candle, buf.get_candles())
            logger.debug(
                f"[{symbol}] Candle closed — "
                f"O:{candle['open']:.2f} H:{candle['high']:.2f} "
                f"L:{candle['low']:.2f} C:{candle['close']:.2f} "
                f"V:{candle['volume']:.2f}"
            )

    def _build_url(self) -> str:
        streams = "/".join(
            f"{s.lower()}@kline_{self.interval}" for s in self.symbols
        )
        return f"{BINANCE_WS_BASE}?streams={streams}"
