"""Correlation-regime detection: is the market currently "fused"?

Rolling pairwise correlation across a basket is reduced to a single
edge-density number per bar (the fraction of pairs whose |correlation|
clears a threshold), then run through a hysteresis state machine so the
regime label doesn't chatter every time the density wobbles across one
threshold. The output is descriptive context -- e.g. for the analyst step in
``tyche.decision.engine`` to note "the market has been broadly correlated
for the last two weeks" -- not a trading signal or a risk-gate input.

Adapted from HKUDS/Vibe-Trading's ``agent/backtest/regime.py`` (MIT
licensed): the edge-density + two-threshold hysteresis state machine is
ported here, restyled to this project's conventions. The original file's
multi-market symbol inference and live price-fetch plumbing (crypto/HK/A-share
loader fallback chains) is dropped entirely -- this module is a pure function
over a returns DataFrame the caller supplies, e.g. built from
``tyche.data.equities.get_price_history``. Not copied verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RegimeTimeline:
    density: pd.Series
    """Fraction of pairs with |correlation| >= edge_threshold, per bar (NaN
    during warmup)."""
    smoothed: pd.Series
    """``density`` after a trailing (causal) rolling mean."""
    fused: pd.Series
    """0/1 per bar: whether the hysteresis state machine currently reads
    the market as FUSED."""


def compute_edge_density(
    returns: pd.DataFrame,
    corr_window: int = 60,
    edge_threshold: float = 0.5,
) -> pd.Series:
    """Reduce rolling pairwise correlations to a single "how fused" scalar.

    Args:
        returns: Wide return matrix, index=date, one column per ticker.
        corr_window: Rolling window (bars) for each pairwise correlation.
        edge_threshold: |correlation| level at which a pair counts as an
            "edge" between two names.

    Returns:
        Edge-density series aligned to ``returns.index`` (NaN during the
        first ``corr_window`` bars).
    """
    n_assets = returns.shape[1]
    n_pairs = n_assets * (n_assets - 1) // 2
    if n_pairs == 0:
        return pd.Series(np.nan, index=returns.index)
    upper = np.triu(np.ones((n_assets, n_assets), dtype=bool), k=1)

    density = pd.Series(np.nan, index=returns.index)
    for i in range(corr_window, len(returns) + 1):
        corr = returns.iloc[i - corr_window : i].corr().abs().to_numpy()
        density.iloc[i - 1] = float((corr[upper] >= edge_threshold).sum()) / n_pairs
    return density


def detect_regime(
    density: pd.Series,
    smooth_window: int = 5,
    enter_threshold: float = 0.65,
    exit_threshold: float = 0.45,
) -> RegimeTimeline:
    """Hysteresis (Schmitt-trigger) state machine over smoothed edge density.

    The market is labeled FUSED once smoothed density reaches
    ``enter_threshold`` and stays FUSED until it falls back to
    ``exit_threshold``. The dead band between the two is what suppresses
    label chatter right at one threshold.

    Args:
        density: Output of :func:`compute_edge_density`.
        smooth_window: Trailing smoothing window (causal -- a centered
            window here would silently read the future).
        enter_threshold: Smoothed density that opens a FUSED regime.
        exit_threshold: Smoothed density that closes it; must be below
            ``enter_threshold``.

    Raises:
        ValueError: if ``exit_threshold >= enter_threshold``.
    """
    if exit_threshold >= enter_threshold:
        raise ValueError("exit_threshold must be below enter_threshold")

    smoothed = density.rolling(smooth_window, min_periods=1).mean()

    fused = False
    states = np.zeros(len(smoothed), dtype=int)
    for i, value in enumerate(smoothed.to_numpy()):
        if np.isnan(value):
            states[i] = int(fused)
            continue
        if not fused and value >= enter_threshold:
            fused = True
        elif fused and value <= exit_threshold:
            fused = False
        states[i] = int(fused)

    return RegimeTimeline(
        density=density,
        smoothed=smoothed,
        fused=pd.Series(states, index=density.index, name="fused"),
    )
