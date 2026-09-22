"""Alpaca paper-trading execution connector.

Paper trading only, by construction: the constructor refuses to run
against anything but Alpaca's paper endpoint. There has been no live-order
review, safety soak period, or slippage/latency validation done for this
project — turning this into a live connector is a deliberate future step,
not a config flag.

Every order still passes through ``tyche.risk.gate.RiskGate`` before
submission — a ``Decision`` never reaches the broker directly. Exits are
not handled here: this project's holding-period/stop-loss/take-profit
logic lives in ``tyche.backtest.portfolio.PortfolioSimulator`` for
backtesting; a live analogue of that (checking open Alpaca positions
against the same exit rules once a day) is the natural next module, not
yet built.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from tyche.config import DEFAULT_RISK_LIMITS, RiskLimits
from tyche.decision.engine import Decision
from tyche.risk.gate import RiskGate


class NotPaperTradingError(Exception):
    """Raised if this connector is ever pointed at a live account."""


@dataclass(frozen=True)
class ExecutionResult:
    submitted: bool
    reason: str
    order_id: str | None = None
    shares: int = 0


class AlpacaPaperExecutor:
    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        risk_limits: RiskLimits = DEFAULT_RISK_LIMITS,
    ):
        api_key = api_key or os.environ.get("ALPACA_API_KEY")
        secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            raise ValueError("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")

        # Hard requirement, not a config toggle we read and trust: this
        # project has no live-order review yet, so refuse anything else.
        paper_flag = os.environ.get("ALPACA_PAPER", "true").strip().lower()
        if paper_flag not in ("true", "1", "yes"):
            raise NotPaperTradingError(
                "ALPACA_PAPER must be true. This connector only ever talks to "
                "Alpaca's paper-trading endpoint — live execution needs a "
                "deliberate, separate connector after a real soak period."
            )

        self._client = TradingClient(api_key, secret_key, paper=True)
        self.risk_gate = RiskGate(risk_limits)

    def open_positions(self) -> list:
        return self._client.get_all_positions()

    def gross_exposure_value(self) -> float:
        return sum(float(p.market_value) for p in self.open_positions())

    def sector_exposure_value(self, sector_by_ticker: dict[str, str], sector: str) -> float:
        return sum(
            float(p.market_value)
            for p in self.open_positions()
            if sector_by_ticker.get(p.symbol) == sector
        )

    def execute(
        self,
        decision: Decision,
        price: float,
        sector: str | None = None,
        sector_exposure_value: float = 0.0,
    ) -> ExecutionResult:
        """Turn a "buy" Decision into a sized, risk-gated market order.

        Sell/hold/needs_review decisions never reach the broker here: exits
        belong to a live version of the holding-period logic (not yet
        built), and REVIEW is not a tradeable direction — see module and
        ``DecisionEngine`` docstrings.
        """
        if decision.action != "buy" or decision.needs_review:
            return ExecutionResult(
                submitted=False,
                reason=f"not a fresh buy (action={decision.action}, needs_review={decision.needs_review})",
            )

        account = self._client.get_account()
        sizing = self.risk_gate.size_new_position(
            portfolio_equity=float(account.equity),
            cash_available=float(account.cash),
            price=price,
            open_position_count=len(self.open_positions()),
            gross_exposure_value=self.gross_exposure_value(),
            sector=sector,
            sector_exposure_value=sector_exposure_value,
        )
        if not sizing.approved:
            return ExecutionResult(submitted=False, reason=sizing.reason)

        order = self._client.submit_order(
            MarketOrderRequest(
                symbol=decision.ticker,
                qty=sizing.shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        )
        return ExecutionResult(
            submitted=True, reason="approved", order_id=str(order.id), shares=sizing.shares
        )

    def close(self, ticker: str) -> ExecutionResult:
        order = self._client.close_position(ticker)
        return ExecutionResult(submitted=True, reason="closed", order_id=str(getattr(order, "id", None)))
