"""
core/trader.py

Wires strategy, risk, gear engine and execution together.
The same Trader drives paper trading, live trading and the backtester,
so a backtest exercises exactly the code path that places real orders.

Per closed candle:
  1. If a position is open, check it against this candle's high/low
     for take-profit or stop-loss. If both are touched, assume the stop
     filled first (the conservative choice).
  2. Otherwise, ask the risk manager for permission, ask the strategy
     for a signal, size it through the gear engine, and open a position.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.gear_engine           import GearEngine
from risk.risk_manager          import RiskManager
from execution.binance_executor import BinanceExecutor, Order, OrderSide, OrderType
from strategies.scalping        import ScalpingStrategy, ScalpSignal

logger = logging.getLogger(__name__)

MIN_CANDLES = 30


@dataclass
class OpenTrade:
    symbol:      str
    direction:   str
    entry_price: float
    take_profit: float
    stop_loss:   float
    size:        float
    leverage:    int
    opened_at:   datetime
    gear:        str


@dataclass
class ClosedTrade:
    symbol:      str
    direction:   str
    entry_price: float
    exit_price:  float
    size:        float
    leverage:    int
    pnl:         float
    exit_reason: str
    opened_at:   datetime
    closed_at:   datetime
    gear:        str


class Trader:

    def __init__(
        self,
        starting_capital: float = 50.0,
        executor: Optional[BinanceExecutor] = None,
        strategy: Optional[ScalpingStrategy] = None,
        start_time: Optional[datetime] = None,
    ):
        self.gear     = GearEngine(starting_capital=starting_capital)
        self.risk     = RiskManager(
            gear_engine=self.gear,
            today=start_time.date() if start_time else None
        )
        self.executor = executor or BinanceExecutor(paper=True)
        self.strategy = strategy or ScalpingStrategy()

        self.open_trades:   dict[str, OpenTrade] = {}
        self.closed_trades: list[ClosedTrade]    = []

    # ------------------------------------------------------------------
    # Main entry point — call once per closed candle
    # ------------------------------------------------------------------

    def on_candle(self, symbol: str, candle: dict, candles: list[dict]) -> None:
        now = _candle_time(candle)

        if symbol in self.open_trades:
            self._check_exit(symbol, candle, now)
            return

        can_trade, reason = self.risk.can_trade(now.date())
        if not can_trade:
            logger.debug(f"Trading blocked: {reason}")
            return

        if len(candles) < MIN_CANDLES:
            return

        signal = self.strategy.analyse(candles, symbol=symbol)
        if signal:
            self._open(signal, now)

    # ------------------------------------------------------------------
    # Entries and exits
    # ------------------------------------------------------------------

    def _open(self, signal: ScalpSignal, now: datetime) -> None:
        gear_config = self.gear.get_config()
        approved, reason, size, leverage = self.risk.validate_order(
            size     = self.gear.get_max_position_gbp(),
            leverage = gear_config.max_leverage,
            symbol   = signal.symbol,
            today    = now.date(),
        )
        if not approved:
            logger.info(f"Order rejected: {reason}")
            return

        side = OrderSide.BUY if signal.direction == "long" else OrderSide.SELL
        fill = self.executor.place_order(Order(
            symbol     = signal.symbol,
            side       = side,
            order_type = OrderType.MARKET,
            size       = size,
            leverage   = leverage,
            price      = signal.entry_price,
        ))
        if not fill:
            return

        self.open_trades[signal.symbol] = OpenTrade(
            symbol      = signal.symbol,
            direction   = signal.direction,
            entry_price = fill.fill_price,
            take_profit = signal.take_profit,
            stop_loss   = signal.stop_loss,
            size        = size,
            leverage    = leverage,
            opened_at   = now,
            gear        = gear_config.label,
        )
        logger.info(
            f"OPEN {signal.direction.upper()} {signal.symbol} {size:.2f} x{leverage} "
            f"@ {fill.fill_price:.2f} | TP {signal.take_profit:.2f} SL {signal.stop_loss:.2f} "
            f"| {signal.reason}"
        )

    def _check_exit(self, symbol: str, candle: dict, now: datetime) -> None:
        trade = self.open_trades[symbol]

        if trade.direction == "long":
            hit_sl = candle["low"]  <= trade.stop_loss
            hit_tp = candle["high"] >= trade.take_profit
        else:
            hit_sl = candle["high"] >= trade.stop_loss
            hit_tp = candle["low"]  <= trade.take_profit

        if hit_sl:
            self._close(trade, trade.stop_loss, "stop_loss", now)
        elif hit_tp:
            self._close(trade, trade.take_profit, "take_profit", now)

    def _close(self, trade: OpenTrade, price: float, reason: str, now: datetime) -> None:
        fill = self.executor.close_position(trade.symbol, price)
        if not fill:
            return

        del self.open_trades[trade.symbol]
        self.risk.record_trade(fill.pnl, at=now)
        self.closed_trades.append(ClosedTrade(
            symbol      = trade.symbol,
            direction   = trade.direction,
            entry_price = trade.entry_price,
            exit_price  = price,
            size        = trade.size,
            leverage    = trade.leverage,
            pnl         = fill.pnl,
            exit_reason = reason,
            opened_at   = trade.opened_at,
            closed_at   = now,
            gear        = trade.gear,
        ))
        logger.info(
            f"CLOSE {trade.symbol} ({reason}) @ {price:.2f} | P&L {fill.pnl:+.2f} "
            f"| capital {self.gear.current_capital:.2f}"
        )

    def close_all(self, prices: dict[str, float], now: datetime) -> None:
        """Flatten every open position, e.g. at the end of a backtest."""
        for trade in list(self.open_trades.values()):
            self._close(trade, prices[trade.symbol], "end_of_data", now)


def _candle_time(candle: dict) -> datetime:
    ts = candle.get("timestamp")
    if not ts:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
