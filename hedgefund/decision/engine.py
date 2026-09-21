"""Wraps TradingAgentsGraph to produce one decision per (ticker, date).

TradingAgents' own ``propagate()`` returns a 5-tier rating (Buy / Overweight /
Hold / Underweight / Sell) plus, sometimes, an unparseable ``"REVIEW"`` when
the Portfolio Manager's output had no recognizable rating. We never let
REVIEW silently become a Hold — a decision nobody could read is not a
decision to do nothing, it's a run that needs a human or a re-run. See
``tradingagents.agents.utils.rating`` for why upstream is strict about this.

The trader agent also proposes an entry price / stop-loss / position size,
but those are advisory LLM output, not enforced limits. Our own
``hedgefund.risk.gate`` and ``hedgefund.config`` are the actual authority on
position size and exit rules — the LLM proposes, the deterministic gate
disposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tradingagents.agents.utils.rating import RATING_REVIEW
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

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

    def __init__(self, config: dict | None = None, debug: bool = False):
        self._graph = TradingAgentsGraph(debug=debug, config=config or DEFAULT_CONFIG.copy())

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
