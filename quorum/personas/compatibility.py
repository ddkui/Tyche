"""Filters investorskills personas for fit with our equities swing-trading
system (target ~10 trading-day hold, max 20 — see
``quorum.config.HoldingPeriodConfig``).

``timeHorizon`` across the 63 skills is inconsistent free text: "days",
"days-weeks", "weeks-months", "5-10 years", "months-years", "event-driven",
"intraday", and more. There is no reliable way to turn that into an exact
day count — this is a heuristic over prose written for humans, not a
parser for a controlled vocabulary, and it is wrong at the margins by
design (a "weeks-months" persona might mean 3 weeks or 4 months to whoever
wrote it). Treat ``parse_time_horizon`` as "in the right ballpark", not as
ground truth, and treat every persona at least once with human judgement
before trusting it in a live run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from quorum.config import DEFAULT_HOLDING_PERIOD, HoldingPeriodConfig
from quorum.personas.models import Persona

EQUITY_ASSET_CLASS = "public equities"

# Approximate trading-day span for each bare unit word, used both for
# single-word horizons ("weeks") and as the low/high anchor of a two-word
# compound ("days-weeks" -> low end of "days" to high end of "weeks").
# Trading days, not calendar days, to match HoldingPeriodConfig's own units.
_UNIT_RANGE_DAYS: dict[str, tuple[int, int]] = {
    "intraday": (0, 1),
    "day": (1, 5),
    "days": (1, 5),
    "week": (5, 20),
    "weeks": (5, 20),
    "month": (20, 60),
    "months": (20, 60),
    "year": (240, 2400),
    "years": (240, 2400),
    "forever": (2400, 100_000),
}

# Words that mean "this horizon is conditional/event-timed, not a fixed
# span" — we can't map these to a day range at all, so they're flagged as
# indeterminate rather than guessed at.
_INDETERMINATE = {"event-driven", "event driven", "variable", "n/a", "unknown", ""}

_NUMERIC_RANGE_RE = re.compile(
    r"(\d+)\s*(?:-\s*(\d+))?\s*\+?\s*(day|week|month|year)s?", re.IGNORECASE
)


@dataclass(frozen=True)
class HorizonEstimate:
    min_days: int
    max_days: int
    """Approximate trading-day range implied by the raw horizon string."""


def parse_time_horizon(raw: str) -> HorizonEstimate | None:
    """Best-effort parse of a free-text ``timeHorizon`` into a day range.

    Returns ``None`` when the text is empty, or clearly not a fixed span
    (e.g. "event-driven") — callers should treat ``None`` as "cannot be
    assessed", not as "compatible" or "incompatible".
    """
    text = raw.strip().lower()
    if text in _INDETERMINATE:
        return None

    numeric = _NUMERIC_RANGE_RE.search(text)
    if numeric:
        lo_n, hi_n, unit = numeric.groups()
        flat_days = {"day": 1, "week": 5, "month": 20, "year": 240}[unit.rstrip("s").lower()]
        lo = int(lo_n) * flat_days
        hi = (int(hi_n) if hi_n else int(lo_n)) * flat_days
        if "+" in text and not hi_n:
            hi = max(hi * 3, hi + flat_days * 10)  # open-ended upper bound
        return HorizonEstimate(min_days=min(lo, hi), max_days=max(lo, hi))

    # Compound word-word horizon, e.g. "days-weeks", "weeks-months",
    # "months-years" (no digits at all).
    parts = [p.strip() for p in re.split(r"[-/]", text) if p.strip()]
    if len(parts) == 2 and all(p in _UNIT_RANGE_DAYS for p in parts):
        lo = _UNIT_RANGE_DAYS[parts[0]][0]
        hi = _UNIT_RANGE_DAYS[parts[1]][1]
        return HorizonEstimate(min_days=lo, max_days=hi)

    # Single bare word ("days", "weeks", "intraday", "forever", ...).
    if text in _UNIT_RANGE_DAYS:
        lo, hi = _UNIT_RANGE_DAYS[text]
        return HorizonEstimate(min_days=lo, max_days=hi)

    return None  # unrecognized free text — cannot be assessed


@dataclass(frozen=True)
class PersonaFit:
    persona: Persona
    equities_ok: bool
    horizon: HorizonEstimate | None
    horizon_ok: bool | None
    """True/False when assessable, None when the horizon text couldn't be
    parsed at all (see ``parse_time_horizon``)."""
    reasons: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        """Compatible without needing an override: equities-eligible and a
        horizon that could be parsed and overlaps our trading window."""
        return self.equities_ok and self.horizon_ok is True


def assess(
    persona: Persona,
    holding_period: HoldingPeriodConfig = DEFAULT_HOLDING_PERIOD,
) -> PersonaFit:
    """Evaluate one persona's fit against ``holding_period``, without
    filtering anything out — see :func:`filter_compatible` for that."""
    reasons: list[str] = []

    equities_ok = any(
        ac.strip().lower() == EQUITY_ASSET_CLASS for ac in persona.asset_classes
    )
    if not equities_ok:
        reasons.append(
            f"assetClasses {persona.asset_classes!r} does not include "
            f"{EQUITY_ASSET_CLASS!r}"
        )

    horizon = parse_time_horizon(persona.time_horizon)
    horizon_ok: bool | None
    if horizon is None:
        horizon_ok = None
        reasons.append(f"timeHorizon {persona.time_horizon!r} could not be parsed")
    else:
        overlaps = (
            horizon.min_days <= holding_period.max_holding_days
            and horizon.max_days >= holding_period.min_holding_days
        )
        horizon_ok = overlaps
        if not overlaps:
            reasons.append(
                f"timeHorizon {persona.time_horizon!r} (~{horizon.min_days}-"
                f"{horizon.max_days} trading days) does not overlap our "
                f"{holding_period.min_holding_days}-{holding_period.max_holding_days} "
                "trading-day window"
            )

    return PersonaFit(
        persona=persona,
        equities_ok=equities_ok,
        horizon=horizon,
        horizon_ok=horizon_ok,
        reasons=tuple(reasons),
    )


def filter_compatible(
    personas: dict[str, Persona] | list[Persona],
    holding_period: HoldingPeriodConfig = DEFAULT_HOLDING_PERIOD,
    *,
    allow_horizon_override: bool = False,
) -> list[PersonaFit]:
    """Personas that are safe to use as-is (equities + horizon overlap our
    holding window), in the order given.

    ``allow_horizon_override=True`` keeps a persona whose horizon doesn't
    overlap (e.g. Buffett's "5-10 years") or couldn't be parsed at all, but
    only once the caller explicitly asked for that — this is meant to be
    opt-in and loud, never a default, since running a multi-year buy-and-hold
    framework through a 10-day holding-period backtest produces decisions
    that were never designed to be judged on that horizon.
    """
    values = personas.values() if isinstance(personas, dict) else personas
    kept: list[PersonaFit] = []
    for persona in values:
        fit = assess(persona, holding_period)
        if not fit.equities_ok:
            continue
        if fit.horizon_ok is True:
            kept.append(fit)
        elif allow_horizon_override:
            import warnings

            warnings.warn(
                f"persona {persona.slug!r} kept despite horizon mismatch "
                f"({'; '.join(fit.reasons)}) because allow_horizon_override=True",
                stacklevel=2,
            )
            kept.append(fit)
    return kept
