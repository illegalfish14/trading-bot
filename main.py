"""
main.py

Entry point for the trading bot.

Usage:
  python main.py --mode backtest                         # Offline backtest on synthetic candles
  python main.py --mode backtest --data history/btc.csv  # Backtest on real candles (see scripts/fetch_klines.py)
  python main.py --mode paper                            # Live Binance data, simulated fills (default)
  python main.py --mode live                             # Real orders (needs BINANCE_API_KEY / BINANCE_API_SECRET)
"""

import argparse
import asyncio
import logging
import os
from datetime import datetime

from core.trader                import Trader
from execution.binance_executor import BinanceExecutor
from data.binance_feed          import BinanceFeed
from backtesting.data           import load_csv, synthetic_candles
from backtesting.engine         import run_backtest, format_report

logger = logging.getLogger("main")

LIVE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def setup_logging(level: int, to_file: bool):
    handlers = [logging.StreamHandler()]
    if to_file:
        os.makedirs("logs", exist_ok=True)
        handlers.append(logging.FileHandler(
            f"logs/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ))
    logging.basicConfig(
        level    = level,
        format   = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt  = "%Y-%m-%d %H:%M:%S",
        handlers = handlers,
    )
    logging.getLogger("websockets").setLevel(logging.WARNING)


def to_ccxt_symbol(stream_symbol: str) -> str:
    """BTCUSDT (WebSocket stream name) → BTC/USDT (ccxt market symbol)."""
    for quote in ("USDT", "USDC", "BUSD"):
        if stream_symbol.endswith(quote):
            return f"{stream_symbol[:-len(quote)]}/{quote}"
    return stream_symbol


def backtest(args):
    setup_logging(logging.WARNING, to_file=False)
    if args.data:
        candles = load_csv(args.data)
        source  = args.data
    else:
        candles = synthetic_candles(n=args.candles, seed=args.seed)
        source  = f"synthetic random walk (seed {args.seed})"

    print(f"Backtesting {len(candles):,} candles from {source}")
    result = run_backtest(candles, symbol=args.symbol, starting_capital=args.capital)
    print(format_report(result))


async def trade(args):
    setup_logging(logging.INFO, to_file=True)
    live = args.mode == "live"

    if live:
        api_key    = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        if not (api_key and api_secret):
            raise SystemExit("Live mode needs BINANCE_API_KEY and BINANCE_API_SECRET (see .env.example)")
        executor = BinanceExecutor(api_key=api_key, api_secret=api_secret, paper=False)
    else:
        executor = BinanceExecutor(paper=True)

    trader = Trader(starting_capital=args.capital, executor=executor)
    g = trader.gear.current_gear

    logger.info("=" * 60)
    logger.info(f"  Trading bot — {args.mode.upper()} | capital {args.capital:.2f}")
    logger.info(f"  Gear {g.label} | max leverage {g.max_leverage}x | position cap {g.position_size:.0%}")
    logger.info("=" * 60)

    def on_candle(stream_symbol, candle, candles):
        trader.on_candle(to_ccxt_symbol(stream_symbol), candle, candles)
        s = trader.risk.status()
        logger.info(
            f"[{stream_symbol}] close {candle['close']:.2f} | capital {s['capital']:.2f} | "
            f"gear {s['gear']} | day P&L {s['daily_pnl']:+.2f} | "
            f"drawdown {s['drawdown_from_peak']:.1%} | open {list(trader.open_trades)}"
        )

    feed = BinanceFeed(symbols=LIVE_SYMBOLS, interval="1m", on_candle=on_candle)
    logger.info("Streaming Binance candles — signals start after 30 closed candles. Ctrl+C to stop.")
    try:
        await feed.start()
    finally:
        feed.stop()
        logger.info(f"Final status: {trader.risk.status()}")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Gear-based crypto trading bot")
    parser.add_argument("--mode",    default="paper", choices=["paper", "live", "backtest"])
    parser.add_argument("--capital", default=50.0, type=float)
    parser.add_argument("--data",    help="CSV of candles for backtest mode")
    parser.add_argument("--symbol",  default="BTC/USDT", help="Symbol label for backtest mode")
    parser.add_argument("--candles", default=20_000, type=int, help="Synthetic candles to generate")
    parser.add_argument("--seed",    default=42, type=int, help="Seed for synthetic candles")
    args = parser.parse_args()

    if args.mode == "backtest":
        backtest(args)
    else:
        try:
            asyncio.run(trade(args))
        except KeyboardInterrupt:
            pass
