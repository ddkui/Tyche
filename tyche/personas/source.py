"""Where persona data comes from: a pinned revision of investorskills, not
63 hand-copied markdown files.

TradingAgents is pinned as a git dependency in ``pyproject.toml`` — pip
clones the exact commit and installs it. ``questflowai/investorskills`` is
not a Python package (there is nothing to import, only Markdown with YAML
frontmatter), so pip has no role here, but the same principle applies: we
pin one upstream commit and load from a real checkout of it, instead of
forking 63 files into this repo where they'd silently drift from upstream.

The natural mechanism for a non-package data dependency pinned to a commit
is a **git submodule**. That is the recommended, permanent setup:

    git submodule add https://github.com/questflowai/investorskills \\
        tyche/personas/vendor/investorskills
    git -C tyche/personas/vendor/investorskills checkout {PINNED_COMMIT}
    git submodule update --init --recursive   # after cloning this repo

We do not run ``git submodule add`` from this module: it writes
``.gitmodules`` at the repository root, and this persona layer was built
under an instruction to touch nothing outside ``tyche/personas/``. So for
now this file documents the submodule as the intended end state and also
works standalone: :func:`fetch` clones the pinned commit into the same
vendor path with plain ``git`` (no submodule bookkeeping), and
:func:`resolve_source_dir` finds a checkout there, at an explicit path, or
at ``QUORUM_INVESTORSKILLS_PATH`` — so callers and tests can point at any
existing clone (e.g. one already checked out elsewhere) without requiring
network access.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SOURCE_URL = "https://github.com/questflowai/investorskills"

# HEAD of the upstream repo at the time this module was written. Bump this
# (and re-verify the curated personas in curated.py still parse the way this
# package expects) when the pin is intentionally updated.
PINNED_COMMIT = "2844d7809a73c01e769c8c1c7ae8189788db4d9e"

_ENV_VAR = "QUORUM_INVESTORSKILLS_PATH"

# Default on-disk location a submodule (or fetch()) would place the checkout.
DEFAULT_VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "investorskills"


def _looks_like_checkout(path: Path) -> bool:
    return (path / "skills").is_dir()


def resolve_source_dir(explicit: str | Path | None = None) -> Path:
    """Find a local investorskills checkout, in priority order:

    1. ``explicit``, if given.
    2. ``$QUORUM_INVESTORSKILLS_PATH``, for pointing at an existing clone
       (used by this project's own tests, and by anyone who doesn't want
       the vendor copy inside the repo).
    3. ``DEFAULT_VENDOR_DIR`` (where the submodule / :func:`fetch` puts it).

    Raises ``FileNotFoundError`` with actionable instructions if none of
    these exist — we never silently fall back to nothing and return an
    empty persona set.
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env_value = os.environ.get(_ENV_VAR)
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(DEFAULT_VENDOR_DIR)

    for candidate in candidates:
        if _looks_like_checkout(candidate):
            return candidate

    raise FileNotFoundError(
        "No investorskills checkout found (looked at: "
        f"{', '.join(str(c) for c in candidates)}). Fetch it with "
        f"tyche.personas.source.fetch(), set {_ENV_VAR} to an existing "
        f"clone, or run:\n"
        f"  git submodule add {SOURCE_URL} {DEFAULT_VENDOR_DIR}\n"
        f"  git -C {DEFAULT_VENDOR_DIR} checkout {PINNED_COMMIT}"
    )


def fetch(dest: str | Path | None = None, commit: str = PINNED_COMMIT) -> Path:
    """Clone (or update) investorskills into ``dest`` at ``commit``.

    A plain-git equivalent of ``git submodule update --init`` for anyone who
    hasn't wired the real submodule up yet. Idempotent: re-running it on an
    existing checkout just fetches and re-checks-out the pinned commit.
    Requires network access and a ``git`` binary; not called automatically
    by anything in this package.
    """
    dest_path = Path(dest) if dest is not None else DEFAULT_VENDOR_DIR
    if (dest_path / ".git").exists():
        subprocess.run(["git", "fetch", "--depth", "1", "origin", commit], cwd=dest_path, check=True)
        subprocess.run(["git", "checkout", "FETCH_HEAD"], cwd=dest_path, check=True)
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", SOURCE_URL, str(dest_path)], check=True)
        subprocess.run(["git", "checkout", commit], cwd=dest_path, check=True)
    return dest_path
