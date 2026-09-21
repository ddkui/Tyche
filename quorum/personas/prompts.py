"""Turns a Persona's markdown body into a block of prompt text.

Kept separate from ``graph.py`` so the actual wording injected into agent
prompts can be unit-tested (and tuned) without touching the TradingAgents
monkeypatch machinery.
"""

from __future__ import annotations

from quorum.personas.models import Persona

# investorskills bodies run a few KB of markdown (philosophy, signals,
# filters, analysis steps). We cap what we inject so one persona's prose
# can't dominate the token budget of a bull/bear debate turn; the cap is
# generous enough to keep every curated persona's body whole (see
# curated.py) and only bites if a much longer skill is used later.
MAX_BODY_CHARS = 6000


def persona_preamble(persona: Persona) -> str:
    """A labelled block of persona framework text to prepend to a prompt.

    Distinctive persona language (e.g. Darvas Box's "consolidation box",
    Buffett's "owner earnings") lives in ``persona.body`` and ends up
    verbatim in here — that's the point: it's what a test asserts actually
    reached the LLM message content (see tests/test_personas.py).
    """
    body = persona.body.strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS].rstrip() + "\n...(truncated)"

    return (
        f"=== INVESTOR PERSONA: {persona.name} ({persona.investor}) ===\n"
        f"Style: {persona.style or 'unspecified'} | "
        f"Typical holding period: {persona.time_horizon or 'unspecified'}\n"
        "Apply this investor's judgment framework as your lens on the case "
        "below, in addition to (not instead of) the analyst reports and "
        "data provided.\n"
        f"{body}\n"
        "=== END INVESTOR PERSONA ==="
    )
