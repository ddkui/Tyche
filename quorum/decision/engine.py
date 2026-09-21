"""Wraps TradingAgentsGraph to produce one decision per (ticker, date).

TradingAgents' own ``propagate()`` returns a 5-tier rating (Buy / Overweight /
Hold / Underweight / Sell) plus, sometimes, an unparseable ``"REVIEW"`` when
the Portfolio Manager's output had no recognizable rating. We never let
REVIEW silently become a Hold — a decision nobody could read is not a
decision to do nothing, it's a run that needs a human or a re-run. See
``tradingagents.agents.utils.rating`` for why upstream is strict about this.

The trader agent also proposes an entry price / stop-loss / position size,
but those are advisory LLM output, not enforced limits. Our own
``quorum.risk.gate`` and ``quorum.config`` are the actual authority on
position size and exit rules — the LLM proposes, the deterministic gate
disposes.

Memory/learning-from-outcomes is not something we build: TradingAgents
already ships ``TradingMemoryLog`` + ``Reflector`` (see
``tradingagents.agents.utils.memory`` / ``tradingagents.graph.reflection``),
which logs every decision, resolves it against realized/alpha return once
the holding period has passed, writes a short LLM reflection, and re-injects
past lessons (same-ticker and cross-ticker) into future prompts — already
point-in-time safe (a backtest only sees lessons whose outcome had actually
resolved by that date). We only need to turn it on (``memory_log_path`` in
config) and call ``settle`` once a ticker's date grid is done, exactly the
way TradingAgents' own ``tradingagents/backtest.py`` does.

An optional ``persona`` (see ``quorum.personas``) wires an investorskills
investor framework into the bull/bear researcher debate via
``quorum.personas.graph.apply_persona`` — a monkeypatch of TradingAgents'
researcher-node factories, since there's no supported extension point for
this (see that module's docstring for why). The patch only affects graph
construction, so it must wrap this constructor, not calls to ``decide``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tradingagents.agents.utils.rating import RATING_REVIEW
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

from quorum.config import DEFAULT_HOLDING_PERIOD, HoldingPeriodConfig
from quorum.personas.graph import apply_persona
from quorum.personas.models import Persona

Action = Literal["buy", "hold", "sell"]

# Buy/Overweight both express a bullish call for a fresh entry; Underweight/
# Sell both express "don't hold this" for our purposes. We collapse the
# 5-tier scale to buy/hold/sell here because our portfolio layer only ever
# opens, holds, or exits a position — it doesn't do partial-size adjustments
# a full Overweight-vs-Buy distinction would imply.
_RATING_TO_ACTION: dict[str, Action] = {
    "Buy": "buy",
    "Overweight": "buy",
    "Hold": "hold",
    "Underweight": "sell",
    "Sell": "sell",
}


@dataclass(frozen=True)
class Decision:
    ticker: str
    trade_date: str
    rating: str
    action: Action
    needs_review: bool
    """True when TradingAgents could not parse a rating. ``action`` is forced
    to "hold" in this case, but callers should surface this rather than treat
    it as a real Hold decision — see module docstring."""


class DecisionEngine:
    """One TradingAgentsGraph instance, reused across calls for a backtest run."""

    def __init__(
        self,
        config: dict | None = None,
        debug: bool = False,
        memory_log_path: str | Path | None = "results/quorum_trading_memory.md",
        holding_period: HoldingPeriodConfig = DEFAULT_HOLDING_PERIOD,
        persona: Persona | None = None,
    ):
        resolved_config = config.copy() if config else DEFAULT_CONFIG.copy()
        if memory_log_path is not None:
            Path(memory_log_path).parent.mkdir(parents=True, exist_ok=True)
            resolved_config["memory_log_path"] = str(memory_log_path)
        # Reflections judge the outcome over our actual holding horizon, not
        # TradingAgents' own 5-day default — a lesson is only meaningful if it
        # was judged over the window we actually trade on.
        resolved_config.setdefault("holding_period_days", holding_period.target_holding_days)

        if persona is not None:
            with apply_persona(persona):
                self._graph = TradingAgentsGraph(debug=debug, config=resolved_config)
        else:
            self._graph = TradingAgentsGraph(debug=debug, config=resolved_config)
        self.persona = persona

    def settle(self, ticker: str) -> None:
        """Resolve any pending past decisions for ``ticker`` against realized
        outcomes and write their reflections, before deciding on it again.

        Call this once per ticker after its date grid is done in a backtest
        (mirrors ``tradingagents.backtest.run_backtest``'s own settlement
        pass) — otherwise that ticker's last few decisions never get a
        lesson written and the memory log undersells what actually happened.
        """
        self._graph.settle_pending(ticker)

    def decide(self, ticker: str, trade_date: str) -> Decision:
        """Run the full analyst -> debate -> trader -> risk -> PM graph once."""
        _final_state, rating = self._graph.propagate(ticker, trade_date, asset_type="stock")

        if rating == RATING_REVIEW:
            return Decision(
                ticker=ticker,
                trade_date=trade_date,
                rating=rating,
                action="hold",
                needs_review=True,
            )

        return Decision(
            ticker=ticker,
            trade_date=trade_date,
            rating=rating,
            action=_RATING_TO_ACTION[rating],
            needs_review=False,
        )
