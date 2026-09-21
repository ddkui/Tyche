"""Portfolio-level risk diagnostics: concentration, correlation, and tail risk
for a weighted equities basket.

``quorum.risk.gate`` caps exposure per name and per declared sector, but a
sector label can't see co-movement: a regional bank and a rate-sensitive REIT
sit in different sectors yet can move together, and the sector cap alone
won't catch that. This module is a read-only lens for a researcher or
dashboard to look at -- how correlated/concentrated the current book actually
is, regardless of how its names are labeled -- not a gate on an order. It has
no opinion on what to do about what it finds.

Adapted from HKUDS/Vibe-Trading's ``agent/backtest/risk_xray.py`` (MIT
licensed): the concentration/drawdown/historical-VaR/diversification-ratio/
correlation statistics are ported here, restyled to this project's
conventions and trimmed to what quorum needs (no JSON-artifact writer, no
runner-specific annualization plumbing). Not copied verbatim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

MIN_HISTORY_DAYS = 30
VAR_LEVELS = (0.95, 0.99)


class InsufficientData(Exception):
    """Raised when the price panel/weights don't leave enough to compute on."""


@dataclass(frozen=True)
class ConcentrationStats:
    hhi: float
    """Herfindahl-Hirschman index of the weights (sum of squared weights)."""
    effective_n: float
    """1 / hhi -- how many equally-weighted names this concentration is
    equivalent to. A 10-name book with effective_n near 2 is far more
    concentrated than its position count suggests."""
    top1_weight: float
    top3_weight: float


@dataclass(frozen=True)
class TailRiskStats:
    var_95: float | None
    var_99: float | None
    es_95: float | None
    es_99: float | None
    """Historical (non-parametric) VaR/expected-shortfall of daily portfolio
    returns, as a positive loss fraction."""


@dataclass(frozen=True)
class CorrelationStats:
    avg_pairwise_abs: float | None
    """Mean |correlation| across all distinct pairs in the book."""
    max_pair: tuple[str, str, float] | None
    """The single most correlated pair and its signed correlation."""
    beta_to_equal_weight: float | None
    """Beta of the actual (weighted) book to an equal-weight book of the same
    names -- how much the sizing itself, not just the name selection, is
    driving co-movement."""


@dataclass(frozen=True)
class PortfolioRiskReport:
    symbols: list[str]
    weights: dict[str, float]
    warnings: list[str]
    concentration: ConcentrationStats
    annualized_vol: float | None
    max_drawdown: float | None
    tail_risk: TailRiskStats
    diversification_ratio: float | None
    """Weighted-average single-name vol / portfolio vol. Below 1.0 is not
    reachable; higher means the book is diversifying away more single-name
    volatility than a naive sum would suggest."""
    correlation: CorrelationStats


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _validate_weights(
    closes: pd.DataFrame, weights: Mapping[str, float]
) -> tuple[dict[str, float], list[str]]:
    if not weights:
        raise ValueError("weights must name at least one symbol")

    unknown = [sym for sym in weights if sym not in closes.columns]
    if unknown:
        raise ValueError(f"weights reference symbols with no price data: {sorted(unknown)}")

    cleaned: dict[str, float] = {}
    for sym, raw in weights.items():
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"weight for {sym!r} is not finite: {raw!r}")
        if value < 0:
            # This project is long-only (quorum.backtest.portfolio never
            # opens a short); a negative weight here means a caller error,
            # not a short leg to size correctly.
            raise ValueError(f"weight for {sym!r} is negative ({value}); long-only basket")
        cleaned[sym] = value

    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive value")

    warnings: list[str] = []
    if abs(total - 1.0) > 1e-6:
        warnings.append(f"weights summed to {total:.6f}; renormalized to 1.0")
        cleaned = {sym: value / total for sym, value in cleaned.items()}
    return cleaned, warnings


def compute_portfolio_risk(
    closes: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    periods_per_year: int = 252,
    var_levels: tuple[float, ...] = VAR_LEVELS,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> PortfolioRiskReport:
    """Concentration/vol/drawdown/tail-risk/correlation snapshot of a basket.

    Args:
        closes: Wide close-price panel, index=date, one column per ticker
            (e.g. built by joining ``quorum.data.equities.get_price_history``
            outputs on their ``close`` columns).
        weights: Ticker -> weight, renormalized to sum 1.0 if it doesn't
            already (a warning is added when that happens). Must be
            non-negative -- see ``_validate_weights``.
        periods_per_year: Annualization factor for volatility (252 trading
            days for daily equities bars).
        var_levels: Tail levels for historical VaR / expected shortfall.
        min_history_days: Tickers with fewer valid closes than this are
            dropped (with a warning) rather than allowed to skew the whole
            report off a handful of bars.

    Raises:
        ValueError: on bad weights or an empty/unusable price panel.
        InsufficientData: when nothing survives the history filter or the
            calendars of the surviving tickers don't overlap enough to
            compute a return series.
    """
    if closes is None or closes.empty:
        raise ValueError("price panel is empty")
    frame = closes.dropna(axis=1, how="all")
    if frame.empty:
        raise ValueError("price panel has no non-NaN closes")

    weights, warnings = _validate_weights(frame, weights)

    kept = [sym for sym in weights if int(frame[sym].count()) >= min_history_days]
    dropped = sorted(set(weights) - set(kept))
    if not kept:
        raise InsufficientData(f"no symbol has at least {min_history_days} valid bars")
    if dropped:
        kept_weights = {sym: weights[sym] for sym in kept}
        total = sum(kept_weights.values())
        if total <= 0:
            raise InsufficientData("surviving symbols have zero total weight")
        weights = {sym: value / total for sym, value in kept_weights.items()}
        warnings.append(f"dropped for thin history (<{min_history_days} bars): {dropped}")

    aligned = frame[kept].dropna(axis=0, how="any")
    if len(aligned) < 2:
        raise InsufficientData("fewer than 2 shared trading days across the surviving symbols")

    returns = aligned.pct_change(fill_method=None).dropna(how="any")
    if returns.empty:
        raise InsufficientData("no overlapping return observations across symbols")

    w = np.array([weights[sym] for sym in kept], dtype=float)
    port_returns = pd.Series(returns.to_numpy(dtype=float) @ w, index=returns.index)

    return PortfolioRiskReport(
        symbols=kept,
        weights={sym: round(weights[sym], 8) for sym in kept},
        warnings=warnings,
        concentration=_concentration(w),
        annualized_vol=_annualized_vol(port_returns, periods_per_year),
        max_drawdown=_max_drawdown(port_returns),
        tail_risk=_tail_risk(port_returns, var_levels),
        diversification_ratio=_diversification_ratio(returns, w, port_returns),
        correlation=_correlation(returns, port_returns, kept),
    )


def _concentration(w: np.ndarray) -> ConcentrationStats:
    hhi = float(np.sum(w**2))
    order = np.argsort(w)[::-1]
    return ConcentrationStats(
        hhi=hhi,
        effective_n=1.0 / hhi if hhi > 0 else float("nan"),
        top1_weight=float(w[order[0]]),
        top3_weight=float(w[order[:3]].sum()),
    )


def _annualized_vol(port: pd.Series, periods_per_year: int) -> float | None:
    if len(port) < 2:
        return None
    return _finite(float(port.std(ddof=1)) * math.sqrt(periods_per_year))


def _max_drawdown(port: pd.Series) -> float | None:
    if port.empty:
        return None
    equity = (1.0 + port).cumprod()
    # Wealth starts at 1 before the first observed return; clipping the
    # high-water mark to 1.0 keeps that as the floor and preserves the
    # drawdown's sign even if a return below -100% ever sent equity through
    # zero.
    peak = equity.cummax().clip(lower=1.0)
    dd = (equity - peak) / peak
    return _finite(float(dd.min()))


def _tail_risk(port: pd.Series, levels: tuple[float, ...]) -> TailRiskStats:
    losses = -port.to_numpy(dtype=float)
    out: dict[str, float | None] = {}
    for level in levels:
        if len(losses) < 2:
            var = es = None
        else:
            var = float(np.quantile(losses, level))
            tail = losses[losses >= var]
            es = float(tail.mean()) if len(tail) else None
        key = f"{int(round(level * 100))}"
        out[f"var_{key}"] = _finite(var)
        out[f"es_{key}"] = _finite(es)
    return TailRiskStats(
        var_95=out.get("var_95"), var_99=out.get("var_99"),
        es_95=out.get("es_95"), es_99=out.get("es_99"),
    )


def _diversification_ratio(returns: pd.DataFrame, w: np.ndarray, port: pd.Series) -> float | None:
    if returns.shape[1] < 2 or len(port) < 2:
        return None
    port_vol = float(port.std(ddof=1))
    if port_vol <= 0 or not math.isfinite(port_vol):
        return None
    asset_vols = returns.std(ddof=1).to_numpy(dtype=float)
    return _finite(float(np.dot(w, asset_vols) / port_vol))


def _correlation(returns: pd.DataFrame, port: pd.Series, symbols: list[str]) -> CorrelationStats:
    if returns.shape[1] < 2:
        return CorrelationStats(avg_pairwise_abs=None, max_pair=None, beta_to_equal_weight=None)

    corr = returns.corr().to_numpy(dtype=float)
    n = corr.shape[0]
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    off_diag = [abs(corr[i, j]) for i, j in pairs]
    avg_pairwise = float(np.mean(off_diag)) if off_diag else None

    max_pair = None
    if off_diag:
        i, j = max(pairs, key=lambda p: abs(corr[p[0], p[1]]))
        max_pair = (symbols[i], symbols[j], _finite(float(corr[i, j])))

    equal_weight = returns.mean(axis=1)
    ew_var = float(equal_weight.var(ddof=1)) if len(equal_weight) > 1 else 0.0
    beta = _finite(float(port.cov(equal_weight) / ew_var)) if ew_var > 0 else None

    return CorrelationStats(
        avg_pairwise_abs=_finite(avg_pairwise),
        max_pair=max_pair,
        beta_to_equal_weight=beta,
    )
