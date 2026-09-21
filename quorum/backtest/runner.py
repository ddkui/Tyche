"""Ties data + decision + portfolio + memory together into one backtest run.

Persists everything a dashboard needs (equity curve, trade log, config) to
``results/runs/<run_id>/`` rather than returning an in-memory object only —
so multiple runs can be listed and compared later without re-running them.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from quorum.backtest.portfolio import PortfolioSimulator
from quorum.config import DEFAULT_HOLDING_PERIOD, DEFAULT_RISK_LIMITS, HoldingPeriodConfig, RiskLimits
from quorum.data.equities import get_price_history
from quorum.decision.engine import DecisionEngine
from quorum.personas.models import load_persona
from quorum.personas.source import resolve_source_dir

RESULTS_DIR = Path("results/runs")


@dataclass
class RunConfig:
    tickers: list[str]
    start_date: str
    end_date: str
    # TradingAgents makes several LLM calls per (ticker, date) — running the
    # full graph every single trading day is neither affordable nor how a
    # swing-trading system (target ~10-day holds) would actually operate.
    # Re-evaluate every N trading days instead; existing positions still get
    # checked for stop-loss/take-profit/max-holding exits every day via
    # PortfolioSimulator regardless of this setting.
    decision_every_n_days: int = 5
    starting_cash: float = 100_000.0
    holding_period: HoldingPeriodConfig = field(default_factory=lambda: DEFAULT_HOLDING_PERIOD)
    risk_limits: RiskLimits = field(default_factory=lambda: DEFAULT_RISK_LIMITS)
    sector_by_ticker: dict[str, str] = field(default_factory=dict)
    persona_slug: str | None = None
    """Investorskills slug (see quorum.personas.curated.CURATED_SLUGS) to
    apply to the bull/bear researcher debate, or None for upstream's
    unmodified prompts. Not validated for horizon/asset-class fit here —
    that's quorum.personas.compatibility's job, run it yourself first."""


def run_backtest(config: RunConfig, run_id: str | None = None, debug: bool = False) -> Path:
    """Run a full backtest and persist it under ``results/runs/<run_id>/``.

    Returns the run directory path.
    """
    run_id = run_id or (datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6])
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    persona = None
    if config.persona_slug is not None:
        persona = load_persona(config.persona_slug, resolve_source_dir())

    engine = DecisionEngine(
        memory_log_path=run_dir / "trading_memory.md",
        holding_period=config.holding_period,
        debug=debug,
        persona=persona,
    )
    sim = PortfolioSimulator(
        starting_cash=config.starting_cash,
        holding_period=config.holding_period,
        risk_limits=config.risk_limits,
        sector_by_ticker=config.sector_by_ticker,
    )

    price_history = {
        ticker: get_price_history(ticker, config.start_date, config.end_date)
        for ticker in config.tickers
    }

    all_dates = sorted({idx for df in price_history.values() for idx in df.index})
    decision_dates = set(all_dates[:: config.decision_every_n_days])

    for current_date in all_dates:
        current_date_str = _date_str(current_date)

        prices_today = {
            ticker: float(df.loc[current_date, "close"])
            for ticker, df in price_history.items()
            if current_date in df.index
        }

        decisions_today = []
        if current_date in decision_dates:
            for ticker in config.tickers:
                if ticker not in prices_today:
                    continue
                decisions_today.append(engine.decide(ticker, current_date_str))

        sim.run_day(current_date_str, prices_today, decisions_today)

    # Settlement pass, mirroring TradingAgents' own run_backtest: without
    # this, the last few decisions for each ticker never get a reflection
    # written, since an outcome needs time to resolve after it's logged.
    for ticker in config.tickers:
        engine.settle(ticker)

    _persist(run_dir, config, sim)
    return run_dir


def _date_str(index_value) -> str:
    return index_value.strftime("%Y-%m-%d") if hasattr(index_value, "strftime") else str(index_value)


def _persist(run_dir: Path, config: RunConfig, sim: PortfolioSimulator) -> None:
    sim.equity_series().to_csv(run_dir / "equity_curve.csv", header=True)
    sim.trade_log().to_csv(run_dir / "trade_log.csv", index=False)
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "tickers": config.tickers,
                "start_date": config.start_date,
                "end_date": config.end_date,
                "decision_every_n_days": config.decision_every_n_days,
                "starting_cash": config.starting_cash,
                "holding_period": asdict(config.holding_period),
                "risk_limits": asdict(config.risk_limits),
                "persona_slug": config.persona_slug,
            },
            indent=2,
        )
    )


def list_runs() -> list[Path]:
    if not RESULTS_DIR.exists():
        return []
    return sorted((p for p in RESULTS_DIR.iterdir() if p.is_dir()), reverse=True)
