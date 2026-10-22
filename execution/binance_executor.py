"""
execution/binance_executor.py

Handles all order placement and fills on Binance.
Supports both paper trading mode and live mode.
Uses ccxt for exchange abstraction.

Sizes are expressed as margin in account currency. Notional exposure
is margin x leverage, and both fees and P&L are calculated on notional.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY  = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT  = "limit"


@dataclass
class Order:
    symbol:     str
    side:       OrderSide
    order_type: OrderType
    size:       float           # margin committed, account currency
    leverage:   int
    price:      Optional[float] = None
    order_id:   Optional[str]   = None
    filled_at:  Optional[float] = None
    status:     str             = "pending"


@dataclass
class Fill:
    order_id:   str
    symbol:     str
    side:       OrderSide
    size:       float
    leverage:   int
    fill_price: float
    fee:        float
    timestamp:  float
    pnl:        float = 0.0

    @property
    def notional(self) -> float:
        return self.size * self.leverage


class BinanceExecutor:
    """
    Execution layer for Binance Futures.
    Paper mode simulates fills without placing real orders.
    """

    FEE_RATE = 0.0005  # 0.05% per side (Binance USD-M futures taker fee, VIP 0)

    def __init__(self, api_key: str = "", api_secret: str = "", paper: bool = True):
        self.paper      = paper
        self.api_key    = api_key
        self.api_secret = api_secret
        self.exchange   = None
        self.open_positions: dict[str, Fill] = {}

        if not paper:
            self._init_exchange()

        mode = "PAPER" if paper else "LIVE"
        logger.info(f"BinanceExecutor initialised — mode: {mode}")

    def place_order(self, order: Order) -> Optional[Fill]:
        """Open a position. Returns Fill on success, None on failure."""
        if order.symbol in self.open_positions:
            logger.warning(f"Already in a position on {order.symbol} — order skipped")
            return None

        fill = self._paper_fill(order) if self.paper else self._live_order(order)
        if fill:
            self.open_positions[order.symbol] = fill
        return fill

    def close_position(self, symbol: str, current_price: float) -> Optional[Fill]:
        """Close an open position at current_price. The returned Fill carries net P&L."""
        if symbol not in self.open_positions:
            logger.warning(f"No open position for {symbol}")
            return None

        entry = self.open_positions[symbol]
        close_side = OrderSide.SELL if entry.side == OrderSide.BUY else OrderSide.BUY

        close_order = Order(
            symbol     = symbol,
            side       = close_side,
            order_type = OrderType.MARKET,
            size       = entry.size,
            leverage   = entry.leverage,
            price      = current_price
        )

        fill = self._paper_fill(close_order) if self.paper else self._live_order(close_order, reduce_only=True)
        if not fill:
            return None

        move = (fill.fill_price - entry.fill_price) / entry.fill_price
        if entry.side == OrderSide.SELL:
            move = -move

        pnl = move * entry.notional - (entry.fee + fill.fee)
        fill.pnl = round(float(pnl), 4)

        del self.open_positions[symbol]
        logger.info(f"Position closed — {symbol} | P&L: {pnl:+.4f}")
        return fill

    # ------------------------------------------------------------------
    # Paper trading simulation
    # ------------------------------------------------------------------

    def _paper_fill(self, order: Order) -> Fill:
        """Simulate an immediate fill at the order price."""
        fill_price = order.price or self._get_mock_price(order.symbol)
        fee        = order.size * order.leverage * self.FEE_RATE

        fill = Fill(
            order_id   = f"PAPER-{int(time.time()*1000)}",
            symbol     = order.symbol,
            side       = order.side,
            size       = order.size,
            leverage   = order.leverage,
            fill_price = fill_price,
            fee        = fee,
            timestamp  = time.time()
        )

        logger.debug(
            f"[PAPER] {order.side.value.upper()} {order.symbol} "
            f"{order.size:.2f} x{order.leverage} @ {fill_price:.4f} | fee: {fee:.4f}"
        )
        return fill

    # ------------------------------------------------------------------
    # Live trading
    # ------------------------------------------------------------------

    def _init_exchange(self):
        try:
            import ccxt
            self.exchange = ccxt.binanceusdm({
                "apiKey": self.api_key,
                "secret": self.api_secret,
            })
            self.exchange.load_markets()
            logger.info("Binance exchange connected")
        except ImportError:
            logger.error("ccxt not installed — run: pip install ccxt")
        except Exception as e:
            logger.error(f"Binance connection failed: {e}")

    def _live_order(self, order: Order, reduce_only: bool = False) -> Optional[Fill]:
        if not self.exchange:
            logger.error("Exchange not connected")
            return None
        try:
            if not reduce_only:
                self.exchange.set_leverage(order.leverage, order.symbol)

            # ccxt expects the amount in base currency (e.g. BTC), not margin
            price  = order.price or self.exchange.fetch_ticker(order.symbol)["last"]
            amount = self.exchange.amount_to_precision(
                order.symbol, order.size * order.leverage / price
            )
            result = self.exchange.create_order(
                symbol = order.symbol,
                type   = order.order_type.value,
                side   = order.side.value,
                amount = float(amount),
                params = {"reduceOnly": True} if reduce_only else {},
            )
            fill_price = result.get("average") or result.get("price") or price

            fill = Fill(
                order_id   = str(result["id"]),
                symbol     = order.symbol,
                side       = order.side,
                size       = order.size,
                leverage   = order.leverage,
                fill_price = fill_price,
                fee        = order.size * order.leverage * self.FEE_RATE,
                timestamp  = time.time()
            )

            logger.info(f"[LIVE] Order filled — {order.symbol} @ {fill_price}")
            return fill

        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return None

    def _get_mock_price(self, symbol: str) -> float:
        """Returns a mock price for paper trading when no price provided."""
        mock_prices = {
            "BTC/USDT": 65000.0,
            "ETH/USDT": 3500.0,
            "BNB/USDT": 580.0,
            "SOL/USDT": 145.0,
        }
        return mock_prices.get(symbol, 100.0)
