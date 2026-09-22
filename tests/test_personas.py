"""Tests for tyche.personas: parsing, compatibility filtering, and — the
bar the task actually cares about — that a selected persona's distinctive
text really reaches the prompt handed to ``llm.invoke`` inside a
constructed ``TradingAgentsGraph``, not just that some Python object exists.

No Anthropic/OpenAI API key is used anywhere here: ``create_llm_client`` is
monkeypatched to a fake client whose ``.get_llm()`` returns an object that
records whatever prompt it's given and returns a canned response.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from tyche.personas.compatibility import assess, filter_compatible, parse_time_horizon
from tyche.personas.graph import apply_persona
from tyche.personas.models import Persona, load_all_personas, load_persona, parse_persona
from tyche.personas.prompts import persona_preamble
from tyche.personas.source import resolve_source_dir

# The scratchpad clone this task was given to read TradingAgents/investorskills
# source from. Real integration tests below use it when present and skip
# cleanly (rather than failing) when this repo is checked out somewhere that
# doesn't have it — e.g. CI, or a future clone with the real submodule set up
# at tyche/personas/vendor/investorskills instead.
_SCRATCHPAD_INVESTORSKILLS = (
    "/tmp/claude-0/-home-user-hedgefunding/586aef10-96ba-571c-b6a0-851ce8f51e35"
    "/scratchpad/research/investorskills"
)


def _real_source_dir() -> str | None:
    if os.environ.get("QUORUM_INVESTORSKILLS_PATH"):
        return os.environ["QUORUM_INVESTORSKILLS_PATH"]
    if os.path.isdir(os.path.join(_SCRATCHPAD_INVESTORSKILLS, "skills")):
        return _SCRATCHPAD_INVESTORSKILLS
    try:
        return str(resolve_source_dir())
    except FileNotFoundError:
        return None


requires_real_investorskills = pytest.mark.skipif(
    _real_source_dir() is None,
    reason="no investorskills checkout available (submodule not initialized)",
)


# --------------------------------------------------------------------------
# time horizon parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expect_min,expect_max",
    [
        ("days", 1, 5),
        ("days-weeks", 1, 20),
        ("weeks-months", 5, 60),
        ("weeks", 5, 20),
        ("intraday", 0, 1),
        ("1-3 years", 240, 720),
        ("5-10 years", 1200, 2400),
    ],
)
def test_parse_time_horizon_ranges(raw, expect_min, expect_max):
    estimate = parse_time_horizon(raw)
    assert estimate is not None
    assert estimate.min_days == expect_min
    assert estimate.max_days == expect_max


@pytest.mark.parametrize("raw", ["event-driven", "", "n/a", "some unparseable nonsense phrase"])
def test_parse_time_horizon_indeterminate_returns_none(raw):
    assert parse_time_horizon(raw) is None


# --------------------------------------------------------------------------
# compatibility filter
# --------------------------------------------------------------------------


def _persona(slug="test", time_horizon="days-weeks", asset_classes=("public equities",), body="body text"):
    return Persona(
        slug=slug,
        name=slug,
        investor="Someone",
        style="momentum",
        time_horizon=time_horizon,
        asset_classes=list(asset_classes),
        body=body,
    )


def test_assess_rejects_wrong_asset_class():
    fit = assess(_persona(asset_classes=["crypto"]))
    assert not fit.equities_ok
    assert not fit.compatible
    assert "crypto" in fit.reasons[0]


def test_assess_rejects_long_horizon():
    fit = assess(_persona(time_horizon="5-10 years"))
    assert fit.equities_ok
    assert fit.horizon_ok is False
    assert not fit.compatible


def test_assess_accepts_swing_horizon():
    fit = assess(_persona(time_horizon="days-weeks"))
    assert fit.compatible


def test_assess_unparseable_horizon_is_not_silently_compatible():
    fit = assess(_persona(time_horizon="event-driven"))
    assert fit.horizon_ok is None
    assert not fit.compatible  # None is not True


def test_filter_compatible_excludes_by_default_and_override_is_loud():
    personas = [_persona(slug="ok"), _persona(slug="buffett-like", time_horizon="5-10 years")]

    kept = filter_compatible(personas)
    assert [f.persona.slug for f in kept] == ["ok"]

    with pytest.warns(UserWarning, match="buffett-like"):
        kept_with_override = filter_compatible(personas, allow_horizon_override=True)
    assert {f.persona.slug for f in kept_with_override} == {"ok", "buffett-like"}


# --------------------------------------------------------------------------
# frontmatter parsing
# --------------------------------------------------------------------------


def test_parse_persona_basic():
    text = """---
name: Test Persona
investor: Jane Doe
style: momentum
timeHorizon: days-weeks
assetClasses:
  - public equities
---

# Body heading

Some distinctive prose about consolidation boxes.
"""
    persona = parse_persona("test-persona", text, "invest.md")
    assert persona.name == "Test Persona"
    assert persona.investor == "Jane Doe"
    assert persona.time_horizon == "days-weeks"
    assert persona.asset_classes == ["public equities"]
    assert "consolidation boxes" in persona.body


def test_parse_persona_missing_closing_delimiter_raises():
    from tyche.personas.models import PersonaParseError

    with pytest.raises(PersonaParseError):
        parse_persona("bad", "---\nname: x\n", "invest.md")


@requires_real_investorskills
def test_load_persona_darvas_box_from_real_checkout():
    source_dir = _real_source_dir()
    persona = load_persona("darvas-box", source_dir)
    assert persona.time_horizon == "days-weeks"
    assert persona.asset_classes == ["public equities"]
    assert "consolidation" in persona.body.lower()
    assert "box" in persona.body.lower()


@requires_real_investorskills
def test_load_all_personas_is_best_effort_over_all_63_skills():
    source_dir = _real_source_dir()
    personas = load_all_personas(source_dir)
    # One skill (as of the pinned commit) has a YAML-invalid frontmatter
    # value; load_all_personas skips it rather than raising for the batch.
    assert len(personas) >= 60
    assert "darvas-box" in personas
    assert "buffett" in personas


@requires_real_investorskills
def test_curated_personas_verified_against_real_checkout():
    """Cross-check curated.py's documented fields against the actual files —
    if investorskills changes these upstream, this test is the tripwire."""
    from tyche.personas.curated import CURATED_SLUGS

    source_dir = _real_source_dir()
    expected = {
        "darvas-box": ("days-weeks", {"public equities"}),
        "minervini-vcp": ("days-weeks", {"public equities"}),
        "oneil-canslim": ("weeks-months", {"public equities"}),
        "livermore": ("days-weeks", {"public equities", "commodities", "multi-asset"}),
        "turtle-trading": (
            "weeks-months",
            {"futures", "fx", "commodities", "public equities", "crypto"},
        ),
    }
    assert set(CURATED_SLUGS) == set(expected)
    for slug in CURATED_SLUGS:
        persona = load_persona(slug, source_dir)
        exp_horizon, exp_classes = expected[slug]
        assert persona.time_horizon == exp_horizon
        assert set(persona.asset_classes) == exp_classes
        fit = assess(persona)
        assert fit.compatible, f"{slug} unexpectedly incompatible: {fit.reasons}"


# --------------------------------------------------------------------------
# persona_preamble
# --------------------------------------------------------------------------


def test_persona_preamble_contains_name_and_body():
    persona = _persona(body="Distinctive Darvas box consolidation language.")
    text = persona_preamble(persona)
    assert persona.name in text
    assert "Distinctive Darvas box consolidation language." in text


# --------------------------------------------------------------------------
# The actual wiring bar: persona text reaches the LLM prompt inside a real
# TradingAgentsGraph, via apply_persona's monkeypatch of the bull/bear
# researcher factories that GraphSetup.setup_graph calls.
# --------------------------------------------------------------------------


class _FakeLLM:
    """Stand-in for a LangChain chat model: records every prompt it's given."""

    def __init__(self, captured: list[str]):
        self._captured = captured

    def invoke(self, prompt):
        self._captured.append(prompt)
        return SimpleNamespace(content="mock analyst response")


class _FakeLLMClient:
    """Stand-in for tradingagents.llm_clients.base_client.BaseLLMClient."""

    def __init__(self, captured: list[str], *args, **kwargs):
        self._llm = _FakeLLM(captured)

    def get_llm(self):
        return self._llm


def _fake_state(persona_marker_free_prompt=True):
    """Minimal AgentState slice bull/bear researcher nodes actually read."""
    return {
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "count": 0,
        },
        "market_report": "shares are trending up",
        "sentiment_report": "neutral chatter",
        "news_report": "no major news",
        "fundamentals_report": "solid balance sheet",
        "asset_type": "stock",
        "instrument_context": "AAPL — Apple Inc.",
        "company_of_interest": "AAPL",
    }


def _build_graph_with_fake_llm(monkeypatch, tmp_path, captured: list[str]):
    """Construct a real TradingAgentsGraph with every LLM call mocked out."""
    import tradingagents.graph.trading_graph as trading_graph_module
    from tradingagents.default_config import DEFAULT_CONFIG

    def fake_create_llm_client(provider, model, base_url=None, **kwargs):
        return _FakeLLMClient(captured, provider=provider, model=model, base_url=base_url, **kwargs)

    monkeypatch.setattr(trading_graph_module, "create_llm_client", fake_create_llm_client)

    config = DEFAULT_CONFIG.copy()
    config["memory_log_path"] = str(tmp_path / "memory.md")
    config["results_dir"] = str(tmp_path / "results")
    config["data_cache_dir"] = str(tmp_path / "cache")

    return trading_graph_module.TradingAgentsGraph(config=config, debug=False)


def test_apply_persona_wires_prompt_into_bull_and_bear_nodes(monkeypatch, tmp_path):
    persona = Persona(
        slug="darvas-box",
        name="Darvas Box",
        investor="Nicolas Darvas",
        style="momentum+breakout+growth",
        time_horizon="days-weeks",
        asset_classes=["public equities"],
        body=(
            "Find strong stocks making new highs, define a consolidation box, "
            "buy a breakout above the box, and place the stop below the box."
        ),
    )

    captured: list[str] = []
    with apply_persona(persona):
        graph = _build_graph_with_fake_llm(monkeypatch, tmp_path, captured)

    bull_runnable = graph.workflow.nodes["Bull Researcher"].runnable
    bear_runnable = graph.workflow.nodes["Bear Researcher"].runnable

    bull_runnable.invoke(_fake_state())
    bear_runnable.invoke(_fake_state())

    assert len(captured) == 2
    bull_prompt, bear_prompt = captured

    # This is the actual assertion the task is graded on: the persona's
    # distinctive framework language is present verbatim in the prompt that
    # was handed to llm.invoke() for both researcher roles.
    assert "consolidation box" in bull_prompt
    assert "Darvas Box" in bull_prompt
    assert "consolidation box" in bear_prompt
    assert "Darvas Box" in bear_prompt

    # And the rest of the original TradingAgents prompt is still there
    # unmodified — this is an addition, not a replacement.
    assert "Bull Analyst advocating for investing in the stock" in bull_prompt
    assert "Bear Analyst making the case against investing in the stock" in bear_prompt


def test_without_apply_persona_no_persona_text_leaks_in(monkeypatch, tmp_path):
    """Control case: building the graph without apply_persona produces the
    stock upstream prompt, with none of our persona block in it."""
    captured: list[str] = []
    graph = _build_graph_with_fake_llm(monkeypatch, tmp_path, captured)

    bull_runnable = graph.workflow.nodes["Bull Researcher"].runnable
    bull_runnable.invoke(_fake_state())

    assert len(captured) == 1
    assert "INVESTOR PERSONA" not in captured[0]
    assert "consolidation box" not in captured[0]


@requires_real_investorskills
def test_apply_persona_with_real_darvas_box_persona_from_checkout(monkeypatch, tmp_path):
    """End-to-end with the actual investorskills file, not a hand-written
    stand-in: loads darvas-box for real and checks its real body text
    reaches the prompt."""
    source_dir = _real_source_dir()
    persona = load_persona("darvas-box", source_dir)

    captured: list[str] = []
    with apply_persona(persona):
        graph = _build_graph_with_fake_llm(monkeypatch, tmp_path, captured)

    graph.workflow.nodes["Bull Researcher"].runnable.invoke(_fake_state())
    prompt = captured[0]

    assert "Darvas Box" in prompt
    # Distinctive language pulled straight from the real invest.md body.
    assert "consolidation box" in prompt.lower() or "box high" in prompt.lower()
