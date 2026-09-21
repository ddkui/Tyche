"""Turns a stream of per-day Decisions into sized positions with exits.

TradingAgents' own ``tradingagents/backtest.py`` deliberately stops at
scoring a rating against realized/alpha return per (ticker, date) cell — its
own docstring says explicitly it is not a portfolio simulator and "must not
grow one." This module is the layer upstream intentionally left out: entry
sizing (via ``hedgefund.risk.gate``), a holding-period exit rule (via
``hedgefund.config.HoldingPeriodConfig``), and a resulting trade log/equity
curve.

Driven one trading day at a time via ``run_day`` — the caller (a backtest
runner) owns the calendar and decides which (ticker, date) cells to ask the
decision engine for.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from hedgefund.config import DEFAULT_HOLDING_PERIOD, DEFAULT_RISK_LIMITS, HoldingPeriodConfig, RiskLimits
from hedgefund.decision.engine import Decision
from hedgefund.risk.gate import RiskGate


@dataclass
class OpenPosition:
    ticker: str
    entry_date: str
    entry_price: float
    shares: int
    sector: str | None = None


@dataclass
class ClosedTrade:
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    shares: int
    exit_reason: str
    pnl: float
    pnl_pct: float
    holding_days: int


class PortfolioSimulator:
    def __init__(
        self,
        starting_cash: float = 100_000.0,
        holding_period: HoldingPeriodConfig = DEFAULT_HOLDING_PERIOD,
        risk_limits: RiskLimits = DEFAULT_RISK_LIMITS,
        sector_by_ticker: dict[str, str] | None = None,
    ):
        self.cash = starting_cash
        self.holding_period = holding_period
        self.risk_gate = RiskGate(risk_limits)
        self.sector_by_ticker = sector_by_ticker or {}

        self.open_positions: dict[str, OpenPosition] = {}
        self.closed_trades: list[ClosedTrade] = []
        self.equity_curve: list[tuple[str, float]] = []
        self.halted_dates: set[str] = set()
        self._last_close_equity: float | None = None

    def _market_value(self, prices_by_ticker: dict[str, float]) -> float:
        return sum(
            pos.shares * prices_by_ticker.get(pos.ticker, pos.entry_price)
            for pos in self.open_positions.values()
        )

    def _sector_exposure_value(self, sector: str, prices_by_ticker: dict[str, float]) -> float:
        return sum(
            pos.shares * prices_by_ticker.get(pos.ticker, pos.entry_price)
            for pos in self.open_positions.values()
            if self.sector_by_ticker.get(pos.ticker) == sector
        )

    def equity(self, prices_by_ticker: dict[str, float]) -> float:
        return self.cash + self._market_value(prices_by_ticker)

    def run_day(
        self,
        current_date: str,
        prices_by_ticker: dict[str, float],
        decisions_today: list[Decision],
    ) -> None:
        """Advance the simulation by one trading day.

        The kill switch compares today's mark-to-market equity (today's
        prices applied to yesterday's positions, before any of today's
        trading) against yesterday's closing equity — that is the actual
        daily loss a kill switch is supposed to catch. Comparing equity
        before/after today's own exits would almost always show ~no
        change, since a stop-loss exit just realizes the same mark-to-market
        loss the check is trying to detect, not a further one.

        Exits are evaluated before new entries, so a position closing today
        never counts against today's exposure caps for a different entry
        opened the same day.
        """
        equity_mark_to_market_today = self.equity(prices_by_ticker)
        equity_start_of_day = (
            self._last_close_equity if self._last_close_equity is not None else equity_mark_to_market_today
        )
        kill_switch = self.risk_gate.daily_kill_switch_triggered(
            equity_start_of_day, equity_mark_to_market_today
        )

        self._process_exits(current_date, prices_by_ticker)

        if kill_switch:
            self.halted_dates.add(current_date)
        else:
            self._process_entries(current_date, prices_by_ticker, decisions_today)

        closing_equity = self.equity(prices_by_ticker)
        self.equity_curve.append((current_date, closing_equity))
        self._last_close_equity = closing_equity

    def _holding_days(self, entry_date: str, current_date: str) -> int:
        """Calendar days between entry and now, used as a proxy for trading
        days elapsed. Exact for same-week holds; can overcount slightly across
        multi-day weekends/holidays. Good enough at the swing-trade horizons
        this project targets (target: 10 days, max: 20) — revisit with an
        actual trading calendar if the horizon ever shortens toward
        day-trading."""
        return (pd.Timestamp(current_date) - pd.Timestamp(entry_date)).days

    def _process_exits(self, current_date: str, prices_by_ticker: dict[str, float]) -> None:
        for ticker in list(self.open_positions):
            pos = self.open_positions[ticker]
            price = prices_by_ticker.get(ticker)
            if price is None:
                continue  # no bar today for this instrument

            days_held = self._holding_days(pos.entry_date, current_date)
            change = (price - pos.entry_price) / pos.entry_price

            reason = None
            if days_held >= self.holding_period.max_holding_days:
                reason = "max_holding_days"
            elif change <= -self.holding_period.stop_loss_pct:
                reason = "stop_loss"
            elif change >= self.holding_period.take_profit_pct:
                reason = "take_profit"
            elif (
                days_held >= self.holding_period.target_holding_days
                and days_held >= self.holding_period.min_holding_days
            ):
                reason = "target_holding_days"

            if reason is not None:
                self._close(pos, current_date, price, reason)

    def _close(self, pos: OpenPosition, exit_date: str, exit_price: float, reason: str) -> None:
        pnl = (exit_price - pos.entry_price) * pos.shares
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
        self.cash += pos.shares * exit_price
        self.closed_trades.append(
            ClosedTrade(
                ticker=pos.ticker,
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                exit_date=exit_date,
                exit_price=exit_price,
                shares=pos.shares,
                exit_reason=reason,
                pnl=pnl,
                pnl_pct=pnl_pct,
                holding_days=self._holding_days(pos.entry_date, exit_date),
            )
        )
        del self.open_positions[pos.ticker]

    def _process_entries(
        self,
        current_date: str,
        prices_by_ticker: dict[str, float],
        decisions_today: list[Decision],
    ) -> None:
        for decision in decisions_today:
            if decision.action != "buy" or decision.needs_review:
                continue
            if decision.ticker in self.open_positions:
                continue  # already holding it; sizing up is out of scope for now

            price = prices_by_ticker.get(decision.ticker)
            if price is None:
                continue

            sector = self.sector_by_ticker.get(decision.ticker)
            sizing = self.risk_gate.size_new_position(
                portfolio_equity=self.equity(prices_by_ticker),
                cash_available=self.cash,
                price=price,
                open_position_count=len(self.open_positions),
                gross_exposure_value=self._market_value(prices_by_ticker),
                sector=sector,
                sector_exposure_value=(
                    self._sector_exposure_value(sector, prices_by_ticker) if sector else 0.0
                ),
            )
            if not sizing.approved:
                continue

            self.cash -= sizing.shares * price
            self.open_positions[decision.ticker] = OpenPosition(
                ticker=decision.ticker,
                entry_date=current_date,
                entry_price=price,
                shares=sizing.shares,
                sector=sector,
            )

    def equity_series(self) -> pd.Series:
        if not self.equity_curve:
            return pd.Series(dtype=float)
        dates, values = zip(*self.equity_curve)
        return pd.Series(values, index=pd.to_datetime(dates), name="equity")

    def trade_log(self) -> pd.DataFrame:
        columns = [
            "ticker", "entry_date", "entry_price", "exit_date", "exit_price",
            "shares", "exit_reason", "pnl", "pnl_pct", "holding_days",
        ]
        if not self.closed_trades:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([vars(t) for t in self.closed_trades])[columns]
