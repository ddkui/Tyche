"""Deterministic risk gate: sits between a Decision and an order.

Every check here is a plain arithmetic comparison against
``quorum.config.RiskLimits``. Nothing here reads the LLM's rationale or
confidence — a decision that argued its way past a limit is still rejected
the same as one with no argument at all. That's the point: conviction is not
a risk parameter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from quorum.config import DEFAULT_RISK_LIMITS, RiskLimits


@dataclass(frozen=True)
class SizingDecision:
    approved: bool
    shares: int
    reason: str


class RiskGate:
    def __init__(self, limits: RiskLimits = DEFAULT_RISK_LIMITS):
        self.limits = limits

    def size_new_position(
        self,
        *,
        portfolio_equity: float,
        cash_available: float,
        price: float,
        open_position_count: int,
        gross_exposure_value: float,
        sector: str | None = None,
        sector_exposure_value: float = 0.0,
    ) -> SizingDecision:
        """How many shares (if any) a new position may open at ``price``.

        Applies, in order: max open positions, per-name cap, sector cap (if a
        sector is given), gross exposure cap, and available cash. The binding
        constraint is whichever leaves the least room — a decision doesn't get
        to pick the most generous limit.
        """
        if open_position_count >= self.limits.max_open_positions:
            return SizingDecision(False, 0, "max_open_positions reached")

        if price <= 0:
            return SizingDecision(False, 0, "invalid price")

        room = portfolio_equity * self.limits.max_position_pct_of_equity

        if sector is not None:
            sector_room = portfolio_equity * self.limits.max_sector_exposure_pct - sector_exposure_value
            room = min(room, max(sector_room, 0.0))

        gross_room = portfolio_equity * self.limits.max_gross_exposure - gross_exposure_value
        room = min(room, max(gross_room, 0.0), max(cash_available, 0.0))

        shares = math.floor(room / price)
        if shares <= 0:
            return SizingDecision(False, 0, "no room under current risk limits")

        return SizingDecision(True, shares, "approved")

    def daily_kill_switch_triggered(self, equity_start_of_day: float, equity_now: float) -> bool:
        """True once today's drawdown breaches the kill-switch threshold.

        Existing positions still exit normally when this trips — this only
        blocks new entries until a human reviews the book (see
        ``RiskLimits.daily_loss_kill_switch_pct``).
        """
        if equity_start_of_day <= 0:
            return False
        drawdown = (equity_start_of_day - equity_now) / equity_start_of_day
        return drawdown >= self.limits.daily_loss_kill_switch_pct
