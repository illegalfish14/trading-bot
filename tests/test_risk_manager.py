from datetime import date, timedelta

from core.gear_engine import GearEngine
from risk.risk_manager import RiskManager

DAY = date(2026, 1, 5)


def make(capital=1000.0):
    gear = GearEngine(starting_capital=capital)
    return gear, RiskManager(gear_engine=gear, today=DAY)


def test_trading_allowed_by_default():
    _, risk = make()
    assert risk.can_trade(DAY) == (True, "")


def test_daily_loss_limit_stops_trading_for_the_day():
    gear, risk = make(1000.0)
    risk.record_trade(-110.0)                     # -11% on the day
    allowed, reason = risk.can_trade(DAY)
    assert not allowed and "Daily loss" in reason


def test_daily_stop_resets_next_day():
    _, risk = make(1000.0)
    risk.record_trade(-110.0)
    assert not risk.can_trade(DAY)[0]
    assert risk.can_trade(DAY + timedelta(days=1))[0]


def test_max_drawdown_halts_permanently():
    gear, risk = make(1000.0)
    gear.update(2000.0)                           # new peak
    gear.update(1390.0)                           # -30.5% from peak
    allowed, reason = risk.can_trade(DAY)
    assert not allowed and "drawdown" in reason
    assert not risk.can_trade(DAY + timedelta(days=30))[0]


def test_order_is_capped_to_gear_limits():
    gear, risk = make(50.0)                       # G1: 35% position, 15x
    approved, _, size, leverage = risk.validate_order(size=1000.0, leverage=50, symbol="BTC/USDT", today=DAY)
    assert approved
    assert size == 50.0 * 0.35
    assert leverage == 15


def test_tiny_orders_are_rejected():
    _, risk = make(10.0)
    approved, reason, _, _ = risk.validate_order(size=3.0, leverage=5, symbol="BTC/USDT", today=DAY)
    assert not approved and "too small" in reason
