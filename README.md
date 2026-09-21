# hedgefunding

An AI hedge fund research project, built on existing open-source tools
rather than from scratch. Equities-first, multi-asset architecture, tuned
for a shorter holding period (swing-trade horizon: days to a couple weeks)
rather than day-trading or buy-and-hold. Paper/backtest only right now —
no live execution is wired in yet.

## Architecture

```
hedgefund/
  config.py       Holding-period + risk-limit defaults (our own layer;
                   upstream has no opinion on either)
  data/
    equities.py    Thin wrapper over OpenBB's equity endpoints
  decision/
    engine.py       Wraps TradingAgentsGraph: one Decision per (ticker, date)
  backtest/
    portfolio.py    Turns Decisions into sized positions with holding-period
                    exits, a trade log and an equity curve
    validators.py   Point-in-time correctness checks for equities backtests
  risk/
    gate.py         Deterministic position sizing / exposure caps / kill
                    switch — sits between a Decision and an order; never
                    bends based on the LLM's confidence or rationale
```

Third-party pieces this depends on:

- **[OpenBB](https://github.com/OpenBB-finance/OpenBB)** — data layer. Unified
  API across equities/crypto/macro providers. `pip install openbb` (already
  in `pyproject.toml`).
- **[TradingAgents](https://github.com/TauricResearch/TradingAgents)**
  (Tauric Research) — the decision engine: analysts -> bull/bear researcher
  debate -> trader -> risk manager -> portfolio manager, as a LangGraph
  graph. Pulled in as a git dependency pinned to a specific commit (see
  `pyproject.toml`) since it isn't published on PyPI.

Not yet wired in, deliberately:

- **[investorskills](https://github.com/questflowai/investorskills)** —
  investor-persona prompt library. Would slot in as prompt modules for
  TradingAgents' analyst/researcher nodes. Optional flavor layer, not
  infrastructure.
- **[Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)** — broker
  execution (paper trading first). Only gets wired in once the backtest
  layer above is trusted; see "Known limitations" below for why we're not
  there yet.

## Why there's a `backtest/portfolio.py` at all

TradingAgents ships its own `tradingagents/backtest.py`, but its docstring
is explicit: it scores a *rating* against realized/alpha return per
(ticker, date) cell, and is deliberately not a portfolio simulator — "must
not grow one," in its own words. That's the right scope for their project.
It means holding periods, position sizing, and P&L are a layer we have to
own, which is what `hedgefund/backtest/portfolio.py` and
`hedgefund/risk/gate.py` are.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # fill in ANTHROPIC_API_KEY at minimum
```

TradingAgents needs at least one LLM provider key (Anthropic, OpenAI,
Google, or Bedrock). OpenBB's `yfinance` provider needs no key for a basic
equities backtest; add `FMP_API_KEY`/`POLYGON_API_KEY` etc. for better
fundamentals/filings coverage later.

**Network policy note**: if you're running this inside a sandboxed
environment (e.g. Claude Code's web/remote environments), check its egress
policy allows the hosts OpenBB's providers and your LLM provider need to
reach — a restrictive default policy will block Yahoo Finance/SEC/etc.
with a 403 at the proxy, not a Python error you can fix in code.

## Known limitations (read before trusting a backtest)

- **No portfolio-level execution yet.** `PortfolioSimulator` is a daily,
  single-fill-per-day simulator (no slippage model, no partial fills, no
  intraday price path). Fine for proving the pipeline; not enough on its
  own to size real capital.
- **Survivorship bias and estimate-vintage checks are stubbed, not solved.**
  `check_universe_survivorship` and `check_estimate_vintage` in
  `validators.py` raise `PITDataUnavailable` rather than a fake pass —
  both need point-in-time index membership / consensus-estimate history
  that free-tier data doesn't carry. Don't backtest a "current S&P 500"
  universe against history and assume it's honest.
- **Holding-day counts are calendar days, not trading days** (see the
  docstring on `PortfolioSimulator._holding_days`). Close enough at a
  10–20 day horizon; would need fixing before shortening toward
  day-trading.
- **Filing-timestamp leakage** (using a 10-Q before its actual public filing
  date, not its fiscal period end) is handled inside TradingAgents'
  `tradingagents.dataflows.sec_edgar` already — `check_filing_not_used_early`
  in our own `validators.py` is for our own pipeline code, not a re-check of
  theirs.
