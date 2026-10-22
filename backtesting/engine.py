"""
backtesting/engine.py

Replays historical candles through the same Trader used for paper and live
trading, then reports performance. No lookahead: at each step the strategy
only sees candles up to and including the one that just closed.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.trader import Trader, ClosedTrade
from execution.binance_executor import BinanceExecutor

logger = logging.getLogger(__name__)

LOOKBACK = 100   # candles handed to the strategy, matching the live buffer


@dataclass
class BacktestResult:
    starting_capital: float
    final_capital:    float
    peak_capital:     float
    trades:           list[ClosedTrade]
    equity_curve:     list[tuple[datetime, float]]
    gear_shifts:      list[dict]
    halted:           bool
    halt_reason:      str
    candles:          int
    start:            datetime
    end:              datetime
    metrics:          dict = field(default_factory=dict)


def run_backtest(
    candles:          list[dict],
    symbol:           str   = "BTC/USDT",
    starting_capital: float = 50.0,
) -> BacktestResult:
    if not candles:
        raise ValueError("No candles to backtest")

    start  = _ts(candles[0])
    trader = Trader(
        starting_capital = starting_capital,
        executor         = BinanceExecutor(paper=True),
        start_time       = start,
    )

    equity = [(start, starting_capital)]
    for i, candle in enumerate(candles):
        window = candles[max(0, i + 1 - LOOKBACK): i + 1]
        n_closed = len(trader.closed_trades)
        trader.on_candle(symbol, candle, window)
        if len(trader.closed_trades) != n_closed:
            equity.append((_ts(candle), trader.gear.current_capital))

    end = _ts(candles[-1])
    trader.close_all({symbol: candles[-1]["close"]}, end)
    equity.append((end, trader.gear.current_capital))

    result = BacktestResult(
        starting_capital = starting_capital,
        final_capital    = trader.gear.current_capital,
        peak_capital     = trader.gear.peak_capital,
        trades           = trader.closed_trades,
        equity_curve     = equity,
        gear_shifts      = trader.gear.gear_history,
        halted           = trader.risk.state.system_halted,
        halt_reason      = trader.risk.state.halt_reason,
        candles          = len(candles),
        start            = start,
        end              = end,
    )
    result.metrics = compute_metrics(result)
    return result


def compute_metrics(r: BacktestResult) -> dict:
    pnls   = [t.pnl for t in r.trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    max_dd, peak = 0.0, r.starting_capital
    for _, capital in r.equity_curve:
        peak   = max(peak, capital)
        max_dd = max(max_dd, (peak - capital) / peak if peak else 0.0)

    gross_loss = abs(sum(losses))
    return {
        "trades":         len(pnls),
        "win_rate":       len(wins) / len(pnls) if pnls else 0.0,
        "total_return":   (r.final_capital - r.starting_capital) / r.starting_capital,
        "profit_factor":  sum(wins) / gross_loss if gross_loss else float("inf") if wins else 0.0,
        "avg_win":        sum(wins) / len(wins) if wins else 0.0,
        "avg_loss":       sum(losses) / len(losses) if losses else 0.0,
        "max_drawdown":   max_dd,
        "gear_shifts":    len(r.gear_shifts),
    }


def format_report(r: BacktestResult) -> str:
    m = r.metrics
    pf = "n/a" if m["profit_factor"] in (0.0, float("inf")) else f"{m['profit_factor']:.2f}"
    lines = [
        "",
        "=" * 56,
        "  BACKTEST REPORT",
        "=" * 56,
        f"  Period          {r.start:%Y-%m-%d %H:%M} → {r.end:%Y-%m-%d %H:%M} UTC",
        f"  Candles         {r.candles:,}",
        f"  Capital         {r.starting_capital:,.2f} → {r.final_capital:,.2f}"
        f"  ({m['total_return']:+.1%})",
        f"  Peak capital    {r.peak_capital:,.2f}",
        f"  Max drawdown    {m['max_drawdown']:.1%}",
        "-" * 56,
        f"  Trades          {m['trades']}",
        f"  Win rate        {m['win_rate']:.1%}",
        f"  Avg win / loss  {m['avg_win']:+.2f} / {m['avg_loss']:+.2f}",
        f"  Profit factor   {pf}",
        f"  Gear shifts     {m['gear_shifts']}",
    ]
    for shift in r.gear_shifts:
        at = shift.get("at")
        when = f"{at:%Y-%m-%d %H:%M}" if at else "?"
        lines.append(f"                  {when}  {shift['from']} → {shift['to']} at {shift['capital']:,.2f}")
    if r.halted:
        lines.append(f"  CIRCUIT BREAKER {r.halt_reason}")
    lines.append("=" * 56)
    return "\n".join(lines)


def _ts(candle: dict) -> datetime:
    return datetime.fromtimestamp(candle["timestamp"] / 1000, tz=timezone.utc)
