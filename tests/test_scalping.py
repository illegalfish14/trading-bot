from strategies.scalping import ScalpingStrategy

CHOP = [100.0 + (0.2 if i % 2 else -0.2) for i in range(38)]


def candles_from(closes, volumes):
    return [{"open": c, "high": c, "low": c, "close": c, "volume": v} for c, v in zip(closes, volumes)]


def test_needs_30_candles():
    assert ScalpingStrategy().analyse(candles_from([100] * 10, [1] * 10)) is None


def test_long_signal_on_crossover_with_volume():
    # Choppy range, a dip pulls EMA9 under EMA21, then an up-candle on 4x volume crosses back
    closes  = CHOP + [99.7, 100.5]
    volumes = [10.0] * 39 + [40.0]
    signal = ScalpingStrategy().analyse(candles_from(closes, volumes), symbol="ETH/USDT")
    assert signal is not None
    assert signal.direction == "long"
    assert signal.symbol == "ETH/USDT"
    assert signal.stop_loss < signal.entry_price < signal.take_profit


def test_no_signal_without_volume_confirmation():
    closes  = CHOP + [99.7, 100.5]
    volumes = [10.0] * 40
    assert ScalpingStrategy().analyse(candles_from(closes, volumes)) is None
