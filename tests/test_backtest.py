import pytest

from backtesting.data import synthetic_candles, load_csv
from backtesting.engine import run_backtest, format_report


def test_synthetic_data_is_deterministic():
    assert synthetic_candles(500, seed=1) == synthetic_candles(500, seed=1)
    assert synthetic_candles(500, seed=1) != synthetic_candles(500, seed=2)


def test_candles_are_well_formed():
    for c in synthetic_candles(1000):
        assert c["low"] <= min(c["open"], c["close"]) <= max(c["open"], c["close"]) <= c["high"]
        assert c["volume"] > 0


def test_backtest_runs_end_to_end():
    result = run_backtest(synthetic_candles(5000, seed=3), starting_capital=50.0)
    m = result.metrics
    assert m["trades"] > 0
    assert 0.0 <= m["win_rate"] <= 1.0
    assert result.final_capital == pytest.approx(50.0 + sum(t.pnl for t in result.trades))
    assert "BACKTEST REPORT" in format_report(result)


def test_circuit_breaker_caps_drawdown():
    result = run_backtest(synthetic_candles(20_000, seed=42), starting_capital=50.0)
    # One losing trade can overshoot the 30% line slightly, but never by much
    assert result.metrics["max_drawdown"] < 0.35


def test_load_csv_with_header(tmp_path):
    p = tmp_path / "k.csv"
    p.write_text("timestamp,open,high,low,close,volume\n"
                 "1700000060000,2,3,1,2.5,10\n1700000000000,1,2,0.5,1.5,5\n")
    candles = load_csv(p)
    assert [c["close"] for c in candles] == [1.5, 2.5]    # sorted oldest first
