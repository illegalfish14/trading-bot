"""
tests/test_gear_engine.py
"""

import pytest
from core.gear_engine import GearEngine, GEARS


def test_initial_gear_detection():
    engine = GearEngine(starting_capital=50.0)
    assert engine.current_gear.label == "G1"


def test_gear_shift_on_capital_increase():
    engine = GearEngine(starting_capital=50.0)
    engine.update(250.0)
    assert engine.current_gear.label == "G2"


def test_gear_shifts_all_the_way():
    engine = GearEngine(starting_capital=50.0)
    milestones = [
        (50,      "G1"),
        (200,     "G2"),
        (1000,    "G3"),
        (5000,    "G4"),
        (20000,   "G5"),
        (100000,  "G6"),
    ]
    for capital, expected_gear in milestones:
        engine.update(capital)
        assert engine.current_gear.label == expected_gear, \
            f"At {capital}, expected {expected_gear} got {engine.current_gear.label}"


def test_peak_capital_tracking():
    engine = GearEngine(starting_capital=100.0)
    engine.update(500.0)
    engine.update(300.0)  # drawdown
    assert engine.peak_capital == 500.0


def test_drawdown_calculation():
    engine = GearEngine(starting_capital=1000.0)
    engine.update(700.0)
    assert abs(engine.get_drawdown_from_peak() - 0.30) < 0.001


def test_gear_history_logs_shifts():
    engine = GearEngine(starting_capital=50.0)
    engine.update(250.0)   # G1 → G2
    engine.update(1100.0)  # G2 → G3
    assert len(engine.gear_history) == 2


def test_max_position_scales_with_capital():
    engine = GearEngine(starting_capital=50.0)
    pos_g1 = engine.get_max_position_gbp()

    engine.update(5000.0)
    pos_g4 = engine.get_max_position_gbp()

    assert pos_g4 > pos_g1   # absolute size is larger
    # But % is smaller
    assert engine.current_gear.position_size < GEARS[0].position_size


def test_daily_target_in_pounds():
    engine = GearEngine(starting_capital=50.0)
    target = engine.get_daily_target_gbp()
    assert abs(target - 50.0 * 0.04) < 0.01  # 4% of 50 = 2
