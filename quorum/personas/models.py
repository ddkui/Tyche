"""Parses an investorskills persona (``invest.md``, falling back to
``SKILL.md``) into a ``Persona`` we can reason about and inject into prompts.

Both files are YAML frontmatter (delimited by ``---`` lines) followed by a
markdown body. ``invest.md`` (see investorskills' ``docs/spec.md``) carries
the richer, more structured frontmatter — ``timeHorizon``, ``assetClasses``,
``style``, etc. — that ``quorum.personas.compatibility`` filters on, so we
prefer it; a skill with only ``SKILL.md`` still has *a* frontmatter (name/
description) we can build a persona from, just with fewer machine-readable
fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_FRONTMATTER_DELIM = "---"


class PersonaParseError(ValueError):
    """A skill's frontmatter could not be parsed into a Persona."""


@dataclass(frozen=True)
class Persona:
    slug: str
    name: str
    investor: str
    style: str
    time_horizon: str
    """Raw free-text horizon (e.g. "days-weeks", "5-10 years") — see
    ``quorum.personas.compatibility`` for parsing this into a day range."""
    asset_classes: list[str] = field(default_factory=list)
    body: str = ""
    """Markdown body (philosophy/signals/filters/analysis prose) — the part
    injected into agent prompts. See ``quorum.personas.prompts``."""
    source_file: str = ""
    """"invest.md" or "SKILL.md" — which file supplied the frontmatter."""


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``text`` into (parsed YAML frontmatter, remaining body)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        raise PersonaParseError("file does not start with a '---' frontmatter delimiter")
    try:
        end = next(
            i for i in range(1, len(lines)) if lines[i].strip() == _FRONTMATTER_DELIM
        )
    except StopIteration as exc:
        raise PersonaParseError("frontmatter opened with '---' but never closed") from exc

    raw_yaml = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).strip()
    try:
        parsed = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError as exc:
        # A few of the 63 skills have prose containing an unescaped ':' in
        # an unquoted YAML scalar (upstream authoring slip, not something we
        # control) — surfaced as our own parse error so callers that treat
        # PersonaParseError as "skip this one" work here too.
        raise PersonaParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PersonaParseError("frontmatter did not parse to a YAML mapping")
    return parsed, body


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise PersonaParseError(f"expected a string or list, got {type(value).__name__}")


def parse_persona(slug: str, text: str, source_file: str) -> Persona:
    """Parse one already-read frontmatter file into a Persona.

    ``SKILL.md`` doesn't have investorskills' richer INVEST.md schema
    (``docs/spec.md``), so ``investor``/``style``/``timeHorizon``/
    ``assetClasses`` may simply be absent there; we fall back to empty
    string / empty list rather than raising, since the compatibility filter
    already treats "unknown" as "cannot confirm this is a fit" and excludes
    it by default.
    """
    frontmatter, body = _split_frontmatter(text)
    name = frontmatter.get("name") or slug
    return Persona(
        slug=slug,
        name=str(name),
        investor=str(frontmatter.get("investor", "")),
        style=str(frontmatter.get("style", "")),
        time_horizon=str(frontmatter.get("timeHorizon", "")),
        asset_classes=_as_str_list(frontmatter.get("assetClasses")),
        body=body,
        source_file=source_file,
    )


def load_persona(slug: str, source_dir: str | Path) -> Persona:
    """Load one persona by slug from a ``skills/<slug>/`` directory tree.

    Prefers ``invest.md``; falls back to ``SKILL.md`` when no invest.md
    exists for that skill (most of the 63 skills don't have one).
    """
    skill_dir = Path(source_dir) / "skills" / slug
    invest_path = skill_dir / "invest.md"
    skill_path = skill_dir / "SKILL.md"

    if invest_path.is_file():
        path, source_file = invest_path, "invest.md"
    elif skill_path.is_file():
        path, source_file = skill_path, "SKILL.md"
    else:
        raise FileNotFoundError(f"no invest.md or SKILL.md under {skill_dir}")

    return parse_persona(slug, path.read_text(encoding="utf-8"), source_file)


def list_available_slugs(source_dir: str | Path) -> list[str]:
    """Every skill slug present in the checkout (each a subdirectory of ``skills/``)."""
    skills_dir = Path(source_dir) / "skills"
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def load_all_personas(source_dir: str | Path) -> dict[str, Persona]:
    """Load every skill in the checkout. Best-effort: a skill whose frontmatter
    fails to parse is skipped rather than failing the whole load — see
    ``errors`` behavior note below if you need to know which ones."""
    out: dict[str, Persona] = {}
    for slug in list_available_slugs(source_dir):
        try:
            out[slug] = load_persona(slug, source_dir)
        except (PersonaParseError, FileNotFoundError):
            continue
    return out
