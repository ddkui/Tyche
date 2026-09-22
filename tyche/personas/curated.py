"""The initial supported persona set: investorskills slugs whose actual
``invest.md`` frontmatter (verified by reading the files, not guessed from
the slug name) fits equities swing-trading on our ~10 trading-day target /
20-day max holding window.

Verified fields (investorskills @ 2844d7809a73c01e769c8c1c7ae8189788db4d9e):

    slug                       timeHorizon     assetClasses
    darvas-box                 days-weeks      [public equities]
    minervini-vcp               days-weeks      [public equities]
    oneil-canslim              weeks-months    [public equities]
    livermore                  days-weeks      [public equities, commodities, multi-asset]
    turtle-trading              weeks-months    [futures, fx, commodities, public equities, crypto]

Names considered and rejected (also read, not assumed):

    buffett                    5-10 years      [public equities]              -> horizon
    cathie-wood-innovation     5-10 years      [public equities]              -> horizon
    watsa-insurance-float      5-10 years      [public equities, ...]         -> horizon
    cobie-cycle-filter         weeks-months    [crypto]                       -> asset class
    seykota-systematic-trend   weeks-months    [futures, fx, commodities,
                                                 crypto, multi-asset]         -> asset class
                                                 (no "public equities" at all)

``chenhao-limit-up`` (timeHorizon "days", public equities) also passes the
filter and is a reasonable sixth candidate, but its SKILL.md/invest.md are
written for A-share limit-up mechanics specific to Chinese markets and
weren't reviewed carefully enough here to curate with confidence — left out
rather than included on a guess.

This module is a starting point, not the only allowed set:
``tyche.personas.compatibility.filter_compatible`` works over the full
63-skill checkout too.
"""

from __future__ import annotations

CURATED_SLUGS: tuple[str, ...] = (
    "darvas-box",
    "minervini-vcp",
    "oneil-canslim",
    "livermore",
    "turtle-trading",
)
