from datetime import datetime, timezone

from core.trader import Trader
from strategies.scalping import ScalpSignal

T0 = 1_767_225_600_000   # 2026-01-01 UTC


class OneShotStrategy:
    """Fires a single long signal, then stays quiet."""
    def __init__(self):
        self.fired = False

    def analyse(self, candles, symbol="BTC/USDT"):
        if self.fired:
            return None
        self.fired = True
        price = candles[-1]["close"]
        return ScalpSignal(symbol, "long", 1.0, price, price * 1.004, price * 0.998, "test")


def candle(i, close, high=None, low=None):
    return {"timestamp": T0 + i * 60_000, "open": close, "close": close,
            "high": high or close, "low": low or close, "volume": 1.0}


def warm_trader():
    trader = Trader(starting_capital=50.0, strategy=OneShotStrategy(),
                    start_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    history = [candle(i, 100.0) for i in range(30)]
    trader.on_candle("BTC/USDT", history[-1], history)
    assert "BTC/USDT" in trader.open_trades
    return trader, history


def test_take_profit_closes_trade_and_grows_capital():
    trader, history = warm_trader()
    trader.on_candle("BTC/USDT", candle(31, 100.3, high=100.5), history)
    assert not trader.open_trades
    trade = trader.closed_trades[0]
    assert trade.exit_reason == "take_profit"
    assert trade.pnl > 0
    assert trader.gear.current_capital == 50.0 + trade.pnl


def test_stop_wins_when_both_levels_are_hit_in_one_candle():
    trader, history = warm_trader()
    trader.on_candle("BTC/USDT", candle(31, 100.0, high=101.0, low=99.0), history)
    assert trader.closed_trades[0].exit_reason == "stop_loss"
    assert trader.closed_trades[0].pnl < 0


def test_position_held_while_price_inside_range():
    trader, history = warm_trader()
    trader.on_candle("BTC/USDT", candle(31, 100.1, high=100.2, low=99.9), history)
    assert "BTC/USDT" in trader.open_trades
