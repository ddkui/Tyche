"""Wires a Persona into TradingAgents' actual bull/bear researcher prompts.

We read TradingAgents' source before writing this (pinned commit
2d17df8da1536c121e4d7395ac5a5dcec9e96d6f — see pyproject.toml) and there is
no supported extension point for this: ``DEFAULT_CONFIG`` has no
custom-prompt key, ``TradingAgentsGraph.__init__`` builds ``GraphSetup``
itself, and ``GraphSetup.setup_graph`` calls
``tradingagents.agents.researchers.{bull,bear}_researcher.create_{bull,
bear}_researcher`` directly — both imported by name into
``tradingagents/graph/setup.py`` at that module's import time. There is no
config field, subclass hook, or constructor argument that reaches those two
functions.

So this module does what the task allows for that situation: it reimplements
``create_bull_researcher``/``create_bear_researcher`` (copying the upstream
prompt text verbatim, since we want everything upstream did, plus the
persona) and monkeypatches ``tradingagents.graph.setup.create_bull_researcher``
/ ``create_bear_researcher`` — the names ``GraphSetup.setup_graph`` actually
calls — for the duration of building a ``TradingAgentsGraph``. Patching
``tradingagents.agents.create_bull_researcher`` instead would do nothing,
since ``setup.py`` already bound its own reference to the original function
at import time.

This is coupled to the pinned commit: if the pin in pyproject.toml moves and
upstream changes the bull/bear prompt text, the docstrings/copy below (in
``_bull_prompt``/``_bear_prompt``) need re-diffing against the new
``tradingagents/agents/researchers/{bull,bear}_researcher.py``, or the
persona framework silently stops reflecting whatever changed there.
"""

from __future__ import annotations

import contextlib
from typing import Any, Callable

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    opponent_argument_or_opening,
    report_or_absent,
)

from tyche.personas.models import Persona
from tyche.personas.prompts import persona_preamble


def _asset_labels(state: dict) -> tuple[str, str]:
    asset_type = state.get("asset_type", "stock")
    target_label = "stock" if asset_type == "stock" else "asset"
    fundamentals_label = (
        "Company fundamentals report"
        if asset_type == "stock"
        else "Asset fundamentals report (may be unavailable for crypto)"
    )
    return target_label, fundamentals_label


def create_persona_bull_researcher(llm: Any, persona: Persona) -> Callable[[dict], dict]:
    """Same node as ``tradingagents.agents.researchers.bull_researcher.
    create_bull_researcher``, with the persona's framework prepended to the
    prompt actually sent to ``llm.invoke``."""

    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = opponent_argument_or_opening(
            investment_debate_state.get("current_response", ""), "bear analyst"
        )
        market_research_report = report_or_absent(state["market_report"], "market")
        sentiment_report = report_or_absent(state["sentiment_report"], "sentiment")
        news_report = report_or_absent(state["news_report"], "news")
        fundamentals_report = report_or_absent(state["fundamentals_report"], "fundamentals")
        instrument_context = get_instrument_context_from_state(state)
        target_label, fundamentals_label = _asset_labels(state)

        prompt = persona_preamble(persona) + f"""

You are a Bull Analyst advocating for investing in the {target_label}. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the company's market opportunities, revenue projections, and scalability.
- Competitive Advantages: Emphasize factors like unique products, strong branding, or dominant market positioning.
- Positive Indicators: Use financial health, industry trends, and recent positive news as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.

Resources available:
{instrument_context}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bear argument: {current_response}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate that demonstrates the strengths of the bull position.
""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node


def create_persona_bear_researcher(llm: Any, persona: Persona) -> Callable[[dict], dict]:
    """Same node as ``tradingagents.agents.researchers.bear_researcher.
    create_bear_researcher``, with the persona's framework prepended to the
    prompt actually sent to ``llm.invoke``."""

    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = opponent_argument_or_opening(
            investment_debate_state.get("current_response", ""), "bull analyst"
        )
        market_research_report = report_or_absent(state["market_report"], "market")
        sentiment_report = report_or_absent(state["sentiment_report"], "sentiment")
        news_report = report_or_absent(state["news_report"], "news")
        fundamentals_report = report_or_absent(state["fundamentals_report"], "fundamentals")
        instrument_context = get_instrument_context_from_state(state)
        target_label, fundamentals_label = _asset_labels(state)

        prompt = persona_preamble(persona) + f"""

You are a Bear Analyst making the case against investing in the {target_label}. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:

- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

Resources available:

{instrument_context}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bull argument: {current_response}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the {target_label}.
""" + get_language_instruction()

        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node


@contextlib.contextmanager
def apply_persona(persona: Persona):
    """Monkeypatch TradingAgents' bull/bear researcher factories for the
    duration of the ``with`` block, so any ``TradingAgentsGraph(...)``
    constructed inside it wires the persona's framework into both
    researcher prompts.

    Must wrap the ``TradingAgentsGraph(...)`` call itself (or, indirectly,
    a ``DecisionEngine(...)`` construction) — ``GraphSetup.setup_graph``
    binds the node closures once, at graph-construction time, in
    ``__init__``. Patching after a graph already exists has no effect on it.

        with apply_persona(persona):
            graph = TradingAgentsGraph(config=...)   # or DecisionEngine(...)
        graph.propagate(ticker, date)                # patch no longer needed here

    Only one persona is applied at a time per process; nested/concurrent use
    is not supported since the patch target is a shared module attribute.
    """
    import tradingagents.graph.setup as setup_module

    original_bull = setup_module.create_bull_researcher
    original_bear = setup_module.create_bear_researcher
    try:
        setup_module.create_bull_researcher = lambda llm: create_persona_bull_researcher(llm, persona)
        setup_module.create_bear_researcher = lambda llm: create_persona_bear_researcher(llm, persona)
        yield
    finally:
        setup_module.create_bull_researcher = original_bull
        setup_module.create_bear_researcher = original_bear
