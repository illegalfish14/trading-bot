"""
risk/risk_manager.py

The safety layer. Enforces all circuit breaker rules.
Nothing executes without passing through here first.
Sacred rules — never override.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from core.gear_engine import GearEngine

logger = logging.getLogger(__name__)


GLOBAL_MAX_DRAWDOWN  = 0.30   # Full system shutdown
GLOBAL_MAX_DAILY_LOSS = 0.10  # Daily stop — no trades for rest of day
GLOBAL_MAX_LEVERAGE  = 15     # Hard cap — never exceeded


@dataclass
class RiskState:
    system_halted:      bool  = False
    daily_trading_stopped: bool = False
    halt_reason:        str   = ""
    day_start_capital:  float = 0.0
    today:              date  = field(default_factory=date.today)
    trades_today:       int   = 0
    daily_pnl:          float = 0.0


class RiskManager:
    """
    Enforces circuit breaker rules before every trade.
    Works in tandem with GearEngine for position sizing.
    """

    MIN_ORDER_SIZE = 5.0   # Below this, fees dominate and exchange minimums bite

    def __init__(self, gear_engine: GearEngine, today: Optional[date] = None):
        self.gear   = gear_engine
        self.state  = RiskState(
            day_start_capital=gear_engine.current_capital,
            today=today or date.today()
        )
        logger.info("RiskManager initialised")

    # ------------------------------------------------------------------
    # Primary gate — call this before placing any order
    # ------------------------------------------------------------------

    def can_trade(self, today: Optional[date] = None) -> tuple[bool, str]:
        """
        Returns (True, "") if trading is allowed.
        Returns (False, reason) if blocked.

        `today` lets the backtester drive the clock; live trading uses the wall clock.
        """
        self._check_new_day(today or date.today())

        if self.state.system_halted:
            return False, f"SYSTEM HALTED: {self.state.halt_reason}"

        if self.state.daily_trading_stopped:
            return False, "Daily loss limit hit — no more trades today"

        drawdown = self.gear.get_drawdown_from_peak()
        if drawdown >= GLOBAL_MAX_DRAWDOWN:
            self._halt_system(f"Max drawdown breached: {drawdown:.1%}")
            return False, self.state.halt_reason

        daily_loss = self._get_daily_loss_pct()
        if daily_loss >= GLOBAL_MAX_DAILY_LOSS:
            self._stop_daily_trading(f"Daily loss limit hit: {daily_loss:.1%}")
            return False, self.state.halt_reason

        return True, ""

    def validate_order(
        self,
        size: float,
        leverage: int,
        symbol: str,
        today: Optional[date] = None
    ) -> tuple[bool, str, float, int]:
        """
        Validate and adjust an order before execution.
        Returns (approved, reason, adjusted_size, adjusted_leverage)
        """
        allowed, reason = self.can_trade(today)
        if not allowed:
            return False, reason, 0.0, 0

        gear_config = self.gear.get_config()

        # Cap leverage
        safe_leverage = min(leverage, gear_config.max_leverage, GLOBAL_MAX_LEVERAGE)
        if safe_leverage < leverage:
            logger.warning(f"Leverage capped: {leverage}x → {safe_leverage}x")

        # Cap position size
        max_size = self.gear.get_max_position_gbp()
        safe_size = min(size, max_size)
        if safe_size < size:
            logger.warning(f"Position size capped: {size:.2f} → {safe_size:.2f}")

        if safe_size < self.MIN_ORDER_SIZE:
            return False, f"Position too small after risk adjustment: {safe_size:.2f}", 0.0, 0

        return True, "approved", safe_size, safe_leverage

    # ------------------------------------------------------------------
    # Post-trade update
    # ------------------------------------------------------------------

    def record_trade(self, pnl: float, at=None):
        """Call after every closed trade to update daily P&L and capital."""
        self.state.trades_today += 1
        self.state.daily_pnl    += pnl
        self.gear.update(self.gear.current_capital + pnl, at=at)

        logger.info(
            f"Trade recorded — P&L: {pnl:+.2f} | "
            f"Day P&L: {self.state.daily_pnl:+.2f} | "
            f"Capital: {self.gear.current_capital:.2f}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_daily_loss_pct(self) -> float:
        if self.state.day_start_capital == 0:
            return 0.0
        loss = self.state.day_start_capital - self.gear.current_capital
        return max(0.0, loss / self.state.day_start_capital)

    def _check_new_day(self, today: date):
        if today != self.state.today:
            logger.info(f"New trading day — resetting daily state. Previous day P&L: {self.state.daily_pnl:+.2f}")
            self.state.today                = today
            self.state.day_start_capital    = self.gear.current_capital
            self.state.trades_today         = 0
            self.state.daily_pnl            = 0.0
            self.state.daily_trading_stopped = False

    def _halt_system(self, reason: str):
        self.state.system_halted = True
        self.state.halt_reason   = reason
        logger.critical(f"SYSTEM HALTED — {reason}")

    def _stop_daily_trading(self, reason: str):
        self.state.daily_trading_stopped = True
        self.state.halt_reason           = reason
        logger.warning(f"DAILY TRADING STOPPED — {reason}")

    def status(self) -> dict:
        return {
            "system_halted":        self.state.system_halted,
            "daily_stopped":        self.state.daily_trading_stopped,
            "halt_reason":          self.state.halt_reason,
            "trades_today":         self.state.trades_today,
            "daily_pnl":            round(self.state.daily_pnl, 2),
            "daily_loss_%":         round(self._get_daily_loss_pct(), 4),
            "drawdown_from_peak":   round(self.gear.get_drawdown_from_peak(), 4),
            **self.gear.summary()
        }
