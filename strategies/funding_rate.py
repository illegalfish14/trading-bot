"""
strategies/funding_rate.py

Delta-neutral funding rate harvest strategy.
Long spot + Short perpetual futures simultaneously.
Collects the funding rate payment (paid every 8 hours on Binance)
with near-zero directional risk.

Unlocked at G3 (1,000+). Standalone module: not yet wired into the live loop.. Runs as a passive baseline 24/7.
Average funding rate: 0.01–0.03% per 8 hours = 0.03–0.09% daily.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


FUNDING_INTERVAL_HOURS = 8
FUNDING_PAYMENTS_PER_DAY = 3   # 24h / 8h


@dataclass
class FundingPosition:
    symbol:         str
    spot_size:      float
    perp_size:      float
    entry_spot:     float
    entry_perp:     float
    funding_earned: float = 0.0
    payments:       int   = 0


@dataclass
class FundingOpportunity:
    symbol:         str
    funding_rate:   float   # current 8h rate as decimal
    annualised:     float   # annualised rate
    daily_yield:    float   # estimated daily yield
    viable:         bool
    reason:         str


class FundingRateHarvester:
    """
    Identifies high funding rate opportunities and manages
    delta-neutral positions to collect funding payments.

    Minimum threshold: 0.01% per 8h (viable)
    Strong threshold:  0.03% per 8h (preferred)
    """

    MIN_FUNDING_RATE   = 0.0001   # 0.01% — minimum to open position
    STRONG_FUNDING_RATE = 0.0003  # 0.03% — preferred
    MIN_CAPITAL        = 1000.0   # Only active at G3+
    CAPITAL_ALLOCATION = 0.30     # Use 30% of capital for funding harvest

    # Symbols to monitor (highest liquidity = tightest spreads)
    WATCH_LIST = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]

    def __init__(self):
        self.positions: dict[str, FundingPosition] = {}
        self.total_earned: float = 0.0
        logger.info("FundingRateHarvester initialised")

    def scan(self, funding_rates: dict[str, float]) -> list[FundingOpportunity]:
        """
        Scan current funding rates and return viable opportunities.

        funding_rates: dict of symbol → current 8h funding rate (decimal)
        e.g. {"BTC/USDT": 0.0002, "ETH/USDT": 0.00015}
        """
        opportunities = []

        for symbol in self.WATCH_LIST:
            rate = funding_rates.get(symbol, 0.0)
            annualised = rate * FUNDING_PAYMENTS_PER_DAY * 365
            daily      = rate * FUNDING_PAYMENTS_PER_DAY

            viable = abs(rate) >= self.MIN_FUNDING_RATE
            strong = abs(rate) >= self.STRONG_FUNDING_RATE

            reason = ""
            if not viable:
                reason = f"Rate too low: {rate:.4%}"
            elif strong:
                reason = f"Strong rate: {rate:.4%}/8h = {annualised:.2%} annualised"
            else:
                reason = f"Viable rate: {rate:.4%}/8h = {annualised:.2%} annualised"

            opportunities.append(FundingOpportunity(
                symbol      = symbol,
                funding_rate = rate,
                annualised  = annualised,
                daily_yield = daily,
                viable      = viable,
                reason      = reason
            ))

            if viable:
                logger.info(f"Funding opportunity — {symbol}: {reason}")

        return sorted(opportunities, key=lambda x: abs(x.funding_rate), reverse=True)

    def open_position(
        self,
        opportunity: FundingOpportunity,
        capital: float
    ) -> Optional[FundingPosition]:
        """Open a delta-neutral funding position."""
        if capital < self.MIN_CAPITAL:
            logger.info(f"Capital too low for funding harvest: {capital:.2f}")
            return None

        if not opportunity.viable:
            logger.info(f"Opportunity not viable: {opportunity.reason}")
            return None

        if opportunity.symbol in self.positions:
            logger.info(f"Already in position: {opportunity.symbol}")
            return None

        allocation = capital * self.CAPITAL_ALLOCATION
        half       = allocation / 2

        position = FundingPosition(
            symbol       = opportunity.symbol,
            spot_size    = half,
            perp_size    = half,
            entry_spot   = 0.0,   # set by executor on fill
            entry_perp   = 0.0,
        )

        self.positions[opportunity.symbol] = position
        logger.info(
            f"Funding position opened — {opportunity.symbol} "
            f"{allocation:.2f} deployed ({half:.2f} spot + {half:.2f} short perp)"
        )
        return position

    def record_funding_payment(self, symbol: str, payment: float):
        """Record a received funding payment."""
        if symbol in self.positions:
            self.positions[symbol].funding_earned += payment
            self.positions[symbol].payments       += 1
            self.total_earned                     += payment
            logger.info(
                f"Funding received — {symbol}: {payment:.4f} "
                f"(total: {self.total_earned:.4f})"
            )

    def close_position(self, symbol: str) -> Optional[float]:
        """Close a funding position. Returns total funding earned."""
        if symbol not in self.positions:
            return None

        pos = self.positions.pop(symbol)
        logger.info(
            f"Funding position closed — {symbol} | "
            f"Total earned: {pos.funding_earned:.4f} over {pos.payments} payments"
        )
        return pos.funding_earned

    def daily_projection(self, capital: float) -> dict:
        """Estimate daily yield from current funding positions."""
        allocation = capital * self.CAPITAL_ALLOCATION
        avg_rate   = self.STRONG_FUNDING_RATE * FUNDING_PAYMENTS_PER_DAY
        projected  = allocation * avg_rate

        return {
            "capital_deployed": round(allocation, 2),
            "avg_daily_rate":   round(avg_rate, 6),
            "projected_daily": round(projected, 4),
            "active_positions": len(self.positions),
            "total_earned": round(self.total_earned, 4)
        }
