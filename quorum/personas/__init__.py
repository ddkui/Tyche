"""Optional investor personas layered onto TradingAgents' bull/bear debate.

A persona is one skill from ``questflowai/investorskills`` (a pinned
external checkout — see ``quorum.personas.source``) parsed into a
``Persona`` and, when compatible with our ~10 trading-day swing-trading
horizon (``quorum.personas.compatibility``), injectable into the actual
bull/bear researcher prompts TradingAgents sends to the LLM
(``quorum.personas.graph.apply_persona``).

Typical use, alongside ``quorum.decision.engine.DecisionEngine``::

    from quorum.personas import CURATED_SLUGS, apply_persona, load_persona
    from quorum.decision.engine import DecisionEngine

    persona = load_persona("darvas-box")
    with apply_persona(persona):
        engine = DecisionEngine()   # graph built here, wired with the persona
    decision = engine.decide("AAPL", "2024-06-03")
"""

from __future__ import annotations

from quorum.personas.compatibility import (
    HorizonEstimate,
    PersonaFit,
    assess,
    filter_compatible,
    parse_time_horizon,
)
from quorum.personas.curated import CURATED_SLUGS
from quorum.personas.graph import apply_persona
from quorum.personas.models import Persona, list_available_slugs, load_all_personas
from quorum.personas.models import load_persona as _load_persona_from_dir
from quorum.personas.prompts import persona_preamble
from quorum.personas.source import resolve_source_dir


def load_persona(slug: str, source_dir: str | None = None) -> Persona:
    """Load one persona by slug, resolving the investorskills checkout the
    same way :func:`quorum.personas.source.resolve_source_dir` does."""
    return _load_persona_from_dir(slug, resolve_source_dir(source_dir))


def load_curated(source_dir: str | None = None) -> dict[str, Persona]:
    """Load just the curated starting set (``CURATED_SLUGS``)."""
    base = resolve_source_dir(source_dir)
    return {slug: _load_persona_from_dir(slug, base) for slug in CURATED_SLUGS}


__all__ = [
    "CURATED_SLUGS",
    "HorizonEstimate",
    "Persona",
    "PersonaFit",
    "apply_persona",
    "assess",
    "filter_compatible",
    "list_available_slugs",
    "load_all_personas",
    "load_curated",
    "load_persona",
    "parse_time_horizon",
    "persona_preamble",
    "resolve_source_dir",
]
