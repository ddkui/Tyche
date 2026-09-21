"""Loading and scoring persisted backtest runs — no Streamlit import here.

Kept separate from ``app.py`` so this logic can be unit-tested directly
(``streamlit run`` can't be exercised in a plain Python test) and so a
future non-Streamlit consumer (a CLI summary, a notebook) can reuse it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import quantstats as qs

from quorum.backtest.runner import list_runs


@dataclass
class RunData:
    run_id: str
    equity: pd.Series
    trades: pd.DataFrame
    config: dict


def load_run(run_dir: Path) -> RunData:
    equity = pd.read_csv(run_dir / "equity_curve.csv", index_col=0, parse_dates=True)["equity"]
    trades = pd.read_csv(run_dir / "trade_log.csv")
    config = _read_json(run_dir / "config.json")
    return RunData(run_id=run_dir.name, equity=equity, trades=trades, config=config)


def _read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text()) if path.exists() else {}


def compute_metrics(equity: pd.Series) -> dict:
    """QuantStats-derived summary metrics for one run's equity curve.

    Returns an empty-ish dict of NaNs for a curve too short to derive
    meaningful stats from (QuantStats' own functions error or return
    nonsense below a handful of points) rather than letting that reach the
    dashboard as a stack trace.
    """
    if equity is None or len(equity) < 3:
        return {"total_return_pct": float("nan"), "sharpe": float("nan"),
                "max_drawdown_pct": float("nan"), "cagr_pct": float("nan"),
                "win_rate_pct": float("nan")}

    returns = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    return {
        "total_return_pct": total_return * 100,
        "sharpe": qs.stats.sharpe(returns) if len(returns) > 1 else float("nan"),
        "max_drawdown_pct": qs.stats.max_drawdown(equity) * 100,
        "cagr_pct": qs.stats.cagr(returns) * 100,
        "win_rate_pct": qs.stats.win_rate(returns) * 100,
    }


def trade_summary(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"num_trades": 0, "win_rate_pct": float("nan"), "avg_pnl_pct": float("nan")}
    wins = (trades["pnl"] > 0).sum()
    return {
        "num_trades": len(trades),
        "win_rate_pct": 100 * wins / len(trades),
        "avg_pnl_pct": 100 * trades["pnl_pct"].mean(),
    }


def compare_runs(run_dirs: list[Path]) -> pd.DataFrame:
    """One row per run: config summary + equity metrics + trade metrics."""
    rows = []
    for run_dir in run_dirs:
        run = load_run(run_dir)
        metrics = compute_metrics(run.equity)
        trade_stats = trade_summary(run.trades)
        rows.append(
            {
                "run_id": run.run_id,
                "tickers": ", ".join(run.config.get("tickers", [])),
                "start_date": run.config.get("start_date"),
                "end_date": run.config.get("end_date"),
                **metrics,
                **trade_stats,
            }
        )
    return pd.DataFrame(rows)


def list_run_dirs() -> list[Path]:
    return list_runs()
