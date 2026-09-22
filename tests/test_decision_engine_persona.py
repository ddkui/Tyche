"""Verifies DecisionEngine's own persona wiring (tyche/decision/engine.py),
distinct from tyche/personas/graph.py's own tests: this checks that passing
``persona=`` into DecisionEngine's constructor actually reaches
apply_persona/TradingAgentsGraph, not just that apply_persona itself works.
"""

from __future__ import annotations

from tyche.decision.engine import DecisionEngine
from tyche.personas.models import Persona


def _darvas_persona() -> Persona:
    return Persona(
        slug="darvas-box",
        name="Darvas Box",
        investor="Nicolas Darvas",
        style="momentum+breakout+growth",
        time_horizon="days-weeks",
        asset_classes=["public equities"],
        body="Find strong stocks making new highs, define a consolidation box, buy a breakout above the box.",
    )


def _fake_state():
    return {
        "investment_debate_state": {
            "history": "", "bull_history": "", "bear_history": "",
            "current_response": "", "count": 0,
        },
        "market_report": "shares are trending up",
        "sentiment_report": "neutral chatter",
        "news_report": "no major news",
        "fundamentals_report": "solid balance sheet",
        "asset_type": "stock",
        "instrument_context": "AAPL — Apple Inc.",
        "company_of_interest": "AAPL",
    }


def test_decision_engine_with_persona_wires_prompt(monkeypatch, tmp_path):
    import tradingagents.graph.trading_graph as trading_graph_module

    captured: list[str] = []

    class _FakeMessage:
        def __init__(self, content: str):
            self.content = content

    class _FakeChatModel:
        def invoke(self, prompt, *args, **kwargs):
            captured.append(prompt if isinstance(prompt, str) else str(prompt))
            return _FakeMessage("Bull Analyst: mock response")

    class _FakeLLMClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_llm(self):
            return _FakeChatModel()

    monkeypatch.setattr(
        trading_graph_module, "create_llm_client",
        lambda provider, model, base_url=None, **kwargs: _FakeLLMClient(),
    )

    engine = DecisionEngine(
        memory_log_path=tmp_path / "memory.md",
        persona=_darvas_persona(),
    )

    assert engine.persona is not None and engine.persona.slug == "darvas-box"

    bull_runnable = engine._graph.workflow.nodes["Bull Researcher"].runnable
    bull_runnable.invoke(_fake_state())

    assert len(captured) == 1
    assert "consolidation box" in captured[0]
    assert "Darvas Box" in captured[0]
    # The underlying upstream prompt is still present alongside the persona.
    assert "Bull Analyst advocating for investing in the stock" in captured[0]


def test_decision_engine_without_persona_has_no_persona_text(monkeypatch, tmp_path):
    import tradingagents.graph.trading_graph as trading_graph_module

    captured: list[str] = []

    class _FakeMessage:
        def __init__(self, content: str):
            self.content = content

    class _FakeChatModel:
        def invoke(self, prompt, *args, **kwargs):
            captured.append(prompt if isinstance(prompt, str) else str(prompt))
            return _FakeMessage("Bull Analyst: mock response")

    class _FakeLLMClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_llm(self):
            return _FakeChatModel()

    monkeypatch.setattr(
        trading_graph_module, "create_llm_client",
        lambda provider, model, base_url=None, **kwargs: _FakeLLMClient(),
    )

    engine = DecisionEngine(memory_log_path=tmp_path / "memory.md")
    assert engine.persona is None

    bull_runnable = engine._graph.workflow.nodes["Bull Researcher"].runnable
    bull_runnable.invoke(_fake_state())

    assert len(captured) == 1
    assert "INVESTOR PERSONA" not in captured[0]
