"""
core/gear_engine.py

The heart of the system. Detects current capital tier,
returns the correct parameters for that gear, and logs
any gear shift events.
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class GearConfig:
    gear:           int
    label:          str
    capital_min:    float
    capital_max:    float
    daily_target:   float   # target daily return as decimal (0.04 = 4%)
    max_leverage:   int
    position_size:  float   # max fraction of capital per trade
    max_daily_loss: float   # daily stop loss as decimal
    strategies:     list[str]


GEARS: list[GearConfig] = [
    GearConfig(
        gear=1, label="G1",
        capital_min=0,       capital_max=200,
        daily_target=0.040,  max_leverage=15,
        position_size=0.35,  max_daily_loss=0.15,
        strategies=["scalping"]
    ),
    GearConfig(
        gear=2, label="G2",
        capital_min=200,     capital_max=1_000,
        daily_target=0.025,  max_leverage=10,
        position_size=0.30,  max_daily_loss=0.12,
        strategies=["scalping", "momentum"]
    ),
    GearConfig(
        gear=3, label="G3",
        capital_min=1_000,   capital_max=5_000,
        daily_target=0.015,  max_leverage=7,
        position_size=0.25,  max_daily_loss=0.10,
        strategies=["scalping", "momentum", "funding_rate"]
    ),
    GearConfig(
        gear=4, label="G4",
        capital_min=5_000,   capital_max=20_000,
        daily_target=0.010,  max_leverage=4,
        position_size=0.20,  max_daily_loss=0.08,
        strategies=["momentum", "funding_rate", "stat_arb"]
    ),
    GearConfig(
        gear=5, label="G5",
        capital_min=20_000,  capital_max=100_000,
        daily_target=0.007,  max_leverage=2,
        position_size=0.15,  max_daily_loss=0.06,
        strategies=["momentum", "funding_rate", "stat_arb", "cross_exchange_arb"]
    ),
    GearConfig(
        gear=6, label="G6",
        capital_min=100_000, capital_max=float("inf"),
        daily_target=0.004,  max_leverage=1,
        position_size=0.10,  max_daily_loss=0.05,
        strategies=["funding_rate", "stat_arb", "cross_exchange_arb"]
    ),
]


class GearEngine:
    """
    Detects which gear the portfolio is currently in
    and provides the correct parameters for that tier.
    Fires a gear shift event when capital crosses a threshold.
    """

    def __init__(self, starting_capital: float = 50.0):
        self.current_capital = starting_capital
        self.peak_capital    = starting_capital
        self.current_gear    = self._detect_gear(starting_capital)
        self.gear_history: list[dict] = []
        logger.info(f"GearEngine initialised — capital: {starting_capital:.2f}, gear: {self.current_gear.label}")

    def update(self, new_capital: float, at=None) -> Optional[GearConfig]:
        """
        Update capital and check for gear shift.
        Returns new GearConfig if gear changed, else None.
        """
        self.current_capital = new_capital
        self.peak_capital = max(self.peak_capital, new_capital)

        new_gear = self._detect_gear(new_capital)

        if new_gear.gear != self.current_gear.gear:
            old_label = self.current_gear.label
            self.current_gear = new_gear
            self._log_gear_shift(old_label, new_gear.label, new_capital, at)
            return new_gear

        return None

    def get_config(self) -> GearConfig:
        """Return the current gear configuration."""
        return self.current_gear

    def get_max_position_gbp(self) -> float:
        """Return max position size (account currency) per trade based on current gear."""
        return self.current_capital * self.current_gear.position_size

    def get_daily_target_gbp(self) -> float:
        """Return target daily gain (account currency) based on current capital and gear."""
        return self.current_capital * self.current_gear.daily_target

    def get_drawdown_from_peak(self) -> float:
        """Return current drawdown as a decimal from peak capital."""
        if self.peak_capital == 0:
            return 0.0
        return (self.peak_capital - self.current_capital) / self.peak_capital

    def _detect_gear(self, capital: float) -> GearConfig:
        for gear in GEARS:
            if gear.capital_min <= capital < gear.capital_max:
                return gear
        return GEARS[-1]

    def _log_gear_shift(self, old_label: str, new_label: str, capital: float, at=None):
        event = {
            "event":      "gear_shift",
            "at":         at,
            "from":       old_label,
            "to":         new_label,
            "capital":    round(capital, 2),
        }
        self.gear_history.append(event)
        logger.info(f"GEAR SHIFT: {old_label} → {new_label} at {capital:.2f}")

    def summary(self) -> dict:
        g = self.current_gear
        return {
            "capital":          round(self.current_capital, 2),
            "peak_capital":     round(self.peak_capital, 2),
            "drawdown":         round(self.get_drawdown_from_peak(), 4),
            "gear":             g.label,
            "daily_target_%":   g.daily_target,
            "daily_target_gbp": round(self.get_daily_target_gbp(), 2),
            "max_position_gbp": round(self.get_max_position_gbp(), 2),
            "max_leverage":     g.max_leverage,
            "active_strategies": g.strategies,
        }
