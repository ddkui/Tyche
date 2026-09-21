"""Thin wrapper over OpenBB's equity endpoints.

Kept deliberately small: this module's only job is to hand back plain
pandas DataFrames with columns our backtest/validators code can rely on,
so the rest of the codebase never imports ``openbb`` directly. Swapping
a provider (e.g. yfinance -> fmp -> polygon) means changing the
``provider=`` argument here, nowhere else.

Network note: OpenBB's providers reach out to third-party hosts
(Yahoo Finance, SEC, FMP, etc.). Whatever environment this runs in must
allow that egress — see this project's README for the network policy
this was developed against.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from openbb import obb


def get_price_history(
    symbol: str,
    start_date: str | date,
    end_date: str | date,
    provider: str = "yfinance",
) -> pd.DataFrame:
    """Daily OHLCV bars for ``symbol`` between the given dates, inclusive.

    Returned frame is adjusted-close by the provider's own convention;
    callers doing PIT-sensitive work should check
    ``quorum.backtest.validators.check_adjustment_convention``.
    """
    result = obb.equity.price.historical(
        symbol=symbol,
        start_date=str(start_date),
        end_date=str(end_date),
        provider=provider,
    )
    return result.to_df()


def get_splits(symbol: str, provider: str = "yfinance") -> pd.DataFrame:
    """Historical stock splits, so signal code can be tested around them."""
    result = obb.equity.fundamental.historical_splits(symbol=symbol, provider=provider)
    return result.to_df()


def get_dividends(symbol: str, provider: str = "yfinance") -> pd.DataFrame:
    result = obb.equity.fundamental.dividends(symbol=symbol, provider=provider)
    return result.to_df()


def get_filings(symbol: str, provider: str = "sec", limit: int = 50) -> pd.DataFrame:
    """SEC filings with their actual public filing date.

    This is the timestamp that matters for PIT correctness — see
    ``check_no_filing_leakage`` in ``quorum.backtest.validators``.
    The fiscal period a filing covers is not the date it became public.
    """
    result = obb.equity.fundamental.filings(symbol=symbol, provider=provider, limit=limit)
    return result.to_df()


def get_earnings_calendar(start_date: str | date, end_date: str | date) -> pd.DataFrame:
    """Scheduled/reported earnings dates in the window, for leakage checks."""
    result = obb.equity.calendar.earnings(start_date=str(start_date), end_date=str(end_date))
    return result.to_df()
