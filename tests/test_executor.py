import pytest

from execution.binance_executor import BinanceExecutor, Order, OrderSide, OrderType


def open_order(side, price=100.0, size=10.0, leverage=10):
    return Order(symbol="BTC/USDT", side=side, order_type=OrderType.MARKET,
                 size=size, leverage=leverage, price=price)


def test_long_profit_uses_notional_and_deducts_fees():
    ex = BinanceExecutor(paper=True)
    ex.place_order(open_order(OrderSide.BUY))
    fill = ex.close_position("BTC/USDT", 101.0)
    # +1% on 100 notional = +1.00, minus 2 x 0.05% x 100 = 0.10 fees
    assert fill.pnl == pytest.approx(0.90)
    assert "BTC/USDT" not in ex.open_positions


def test_short_positions_are_tracked_and_profit_on_a_fall():
    ex = BinanceExecutor(paper=True)
    ex.place_order(open_order(OrderSide.SELL))
    assert "BTC/USDT" in ex.open_positions
    fill = ex.close_position("BTC/USDT", 99.0)
    assert fill.pnl == pytest.approx(0.90)


def test_cannot_double_up_on_a_symbol():
    ex = BinanceExecutor(paper=True)
    assert ex.place_order(open_order(OrderSide.BUY))
    assert ex.place_order(open_order(OrderSide.BUY)) is None


def test_closing_without_a_position_returns_none():
    assert BinanceExecutor(paper=True).close_position("ETH/USDT", 3000.0) is None
