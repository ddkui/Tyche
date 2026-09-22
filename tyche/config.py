"""Our own layer of config: holding-period strategy and risk limits.

TradingAgents supplies the LLM decision graph and its own config
(``tradingagents.default_config``). This module is everything upstream
of that has no opinion on: how long we hold a position, how big a
position is allowed to be, and when the whole book stops trading.
These are equities-only defaults tuned for a swing-trading horizon
(days to a couple weeks) rather than day-trading or buy-and-hold.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HoldingPeriodConfig:
    """Exit rules for a position opened from a TradingAgents decision."""

    min_holding_days: int = 2
    """Don't exit purely on noise before this many trading days have passed."""

    target_holding_days: int = 10
    """Default exit horizon absent a stop-loss/take-profit trigger."""

    max_holding_days: int = 20
    """Hard exit regardless of signal — a decision this stale is re-evaluated,
    not held on indefinitely."""

    stop_loss_pct: float = 0.08
    """Exit if the position is down this fraction from entry, any day."""

    take_profit_pct: float = 0.15
    """Exit if the position is up this fraction from entry, any day."""


@dataclass(frozen=True)
class RiskLimits:
    """Hard caps enforced in code between a decision and an order.

    These never bend based on an agent's confidence or rationale — that's
    the point. An LLM convinced of its own thesis is exactly the failure
    mode these caps exist to catch.
    """

    max_position_pct_of_equity: float = 0.05
    """No single name larger than this fraction of total portfolio equity."""

    max_gross_exposure: float = 1.0
    """No leverage: total position value never exceeds portfolio equity."""

    max_open_positions: int = 15

    max_sector_exposure_pct: float = 0.25
    """No single sector larger than this fraction of portfolio equity."""

    daily_loss_kill_switch_pct: float = 0.03
    """If realized + unrealized P&L drops this much in a single day, halt new
    entries until a human reviews the book. Existing exits still fire."""


DEFAULT_HOLDING_PERIOD = HoldingPeriodConfig()
DEFAULT_RISK_LIMITS = RiskLimits()
