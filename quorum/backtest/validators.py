"""Point-in-time correctness checks for equities backtests.

These are the concrete equities failure modes from the project's design
discussion, turned into functions. Two honesty notes up front:

1. Some of these (survivorship, estimate vintage) genuinely cannot be
   validated against free data — Yahoo/yfinance-tier data does not carry
   point-in-time index membership or historical consensus-estimate
   snapshots. Those functions raise ``PITDataUnavailable`` rather than
   silently reporting a pass; a paid provider (e.g. a CRSP-style index
   history, or a fundamentals vendor with point-in-time estimates) is a
   real prerequisite for those specific checks, not a nice-to-have.
2. Filing-timestamp leakage is already handled inside TradingAgents'
   ``tradingagents.dataflows.sec_edgar`` (it fetches SEC EDGAR's actual
   accepted-date, not the fiscal period end). ``check_filing_not_used_early``
   below is for *our own* pipeline code, not a re-check of TradingAgents'
   internals — it exists in case our backtest runner ever joins filing data
   to a signal date itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


class PITDataUnavailable(Exception):
    """Raised when a check requires data our current providers don't have."""


@dataclass
class Violation:
    check: str
    detail: str
    date: str | None = None


@dataclass
class PITReport:
    violations: list[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def add(self, check: str, detail: str, date: str | None = None) -> None:
        self.violations.append(Violation(check=check, detail=detail, date=date))


def check_split_adjustment_consistency(
    prices: pd.DataFrame,
    splits: pd.DataFrame,
    price_col: str = "close",
    tolerance: float = 0.03,
) -> PITReport:
    """Flag price series that look unadjusted around a recorded split.

    If ``prices`` were properly split-adjusted, a split event should not
    produce a large one-day jump — the ratio was already smoothed into
    history. A day-over-day change that closely matches the split ratio (or
    its inverse) means raw and adjusted prices got mixed, which will corrupt
    any return or indicator computed across that date.
    """
    report = PITReport()
    if prices.empty or splits.empty:
        return report

    prices = prices.sort_index()
    returns = prices[price_col].pct_change()

    for split_date, row in splits.iterrows():
        ratio = row.get("split_ratio") or row.get("numerator", None)
        if ratio is None or ratio in (0, 1):
            continue
        positions = returns.index.get_indexer([split_date], method="nearest")
        if len(positions) == 0 or positions[0] == -1:
            continue
        change = returns.iloc[positions[0]]
        implied = (1 / ratio) - 1
        if abs(change - implied) < tolerance:
            report.add(
                "split_adjustment_consistency",
                f"price jump near split date matches raw split ratio {ratio}x "
                f"(observed {change:.2%}, expected ~{implied:.2%} if unadjusted)",
                date=str(split_date),
            )
    return report


def check_price_gaps(
    prices: pd.DataFrame,
    max_gap_trading_days: int = 5,
) -> PITReport:
    """Flag unexplained multi-day gaps in a price series.

    A gap this large is either a halt, a delisting, or a data outage — any
    of which needs a human to confirm before the backtest trusts the bars on
    either side of it as continuous.
    """
    report = PITReport()
    if prices.empty:
        return report

    index = prices.sort_index().index
    gaps = index.to_series().diff().dt.days
    for date, gap in gaps.items():
        if pd.notna(gap) and gap > max_gap_trading_days * 1.6:  # rough calendar-day allowance
            report.add(
                "price_gap",
                f"{int(gap)} calendar days since previous bar",
                date=str(date),
            )
    return report


def check_filing_not_used_early(
    signal_dates: pd.Series,
    filing_available_dates: pd.Series,
) -> PITReport:
    """Flag any signal computed before the filing it relied on was public.

    ``signal_dates`` and ``filing_available_dates`` are paired by position
    (same length, same order) — e.g. for each backtest cell, the date the
    signal was generated and the actual public availability date of the
    filing it cited.
    """
    report = PITReport()
    for signal_date, available_date in zip(signal_dates, filing_available_dates):
        if pd.Timestamp(signal_date) < pd.Timestamp(available_date):
            report.add(
                "filing_not_used_early",
                f"signal dated {signal_date} used a filing not public until {available_date}",
                date=str(signal_date),
            )
    return report


def check_universe_survivorship(*_args, **_kwargs) -> PITReport:
    raise PITDataUnavailable(
        "Survivorship-bias checking needs point-in-time index membership "
        "(who was actually in the universe on each historical date, including "
        "names since delisted/bankrupt/acquired). Free yfinance-tier data does "
        "not carry this. Options: a paid point-in-time index history provider, "
        "or building your own universe snapshot log going forward (which only "
        "helps for dates after you start recording it)."
    )


def check_estimate_vintage(*_args, **_kwargs) -> PITReport:
    raise PITDataUnavailable(
        "Consensus-estimate-vintage checking needs historical point-in-time "
        "analyst estimate snapshots (what consensus EPS was on a given past "
        "date, not what it is now). This requires a paid fundamentals vendor "
        "with estimate history (e.g. a provider that keeps as-of snapshots); "
        "free tiers only expose current consensus."
    )
