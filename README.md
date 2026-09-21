# Quorum

An AI hedge fund research project, built on existing open-source tools
rather than from scratch. Named for the shape of its decision engine: a
quorum of analyst/researcher/risk/portfolio-manager agents that has to
agree before a trade happens. Equities-first, multi-asset architecture,
tuned for a shorter holding period (swing-trade horizon: days to a couple
weeks) rather than day-trading or buy-and-hold. Backtesting + Alpaca paper
trading are wired in; no live execution.

## Architecture

```
quorum/
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
    runner.py       Ties data + decision + portfolio + memory into one
                    backtest run, persisted to results/runs/<run_id>/
  risk/
    gate.py         Deterministic position sizing / exposure caps / kill
                    switch — sits between a Decision and an order; never
                    bends based on the LLM's confidence or rationale
  execution/
    alpaca.py       Paper-trading execution via Alpaca; refuses anything
                    but the paper endpoint, orders always risk-gated
  dashboard/
    app.py           Streamlit UI: launch runs, compare them, read the
                     memory log's reflections
    data.py           Run-loading/scoring logic (QuantStats metrics),
                     kept Streamlit-free so it's independently testable
```

Third-party pieces this depends on:

- **[OpenBB](https://github.com/OpenBB-finance/OpenBB)** — data layer. Unified
  API across equities/crypto/macro providers. `pip install openbb` (already
  in `pyproject.toml`).
- **[TradingAgents](https://github.com/TauricResearch/TradingAgents)**
  (Tauric Research) — the decision engine: analysts -> bull/bear researcher
  debate -> trader -> risk manager -> portfolio manager, as a LangGraph
  graph. Pulled in as a git dependency pinned to a specific commit (see
  `pyproject.toml`) since it isn't published on PyPI. Its own
  `TradingMemoryLog` + `Reflector` also give us learning-from-outcomes for
  free — see "Memory" below.
- **[Alpaca](https://alpaca.markets/) (`alpaca-py`)** — paper-trading
  execution. Chosen over building on Vibe-Trading's broker connectors: free
  paper accounts, an official maintained SDK, and a purpose-built paper
  sandbox rather than a live-money connector we'd have to run in
  paper-only mode ourselves.
- **[QuantStats](https://github.com/ranaroussi/quantstats)** — performance
  metrics (Sharpe, max drawdown, CAGR, win rate) for the dashboard, instead
  of hand-rolling them.
- **[Streamlit](https://github.com/streamlit/streamlit)** — the dashboard's
  app shell.

Not yet wired in, deliberately:

- **[investorskills](https://github.com/questflowai/investorskills)** —
  investor-persona prompt library. Would slot in as prompt modules for
  TradingAgents' analyst/researcher nodes. Optional flavor layer, not
  infrastructure.

## Memory: agents learning from past outcomes

Not something we built — TradingAgents already ships it
(`tradingagents/agents/utils/memory.py`'s `TradingMemoryLog` +
`tradingagents/graph/reflection.py`'s `Reflector`), fully wired into its own
`propagate()`/`backtest.py`. Every decision is logged as pending; once the
holding period has passed, an LLM writes a short reflection on what the
outcome showed and what to do differently, and that lesson gets re-injected
into future prompts for the same ticker and across tickers. It's already
point-in-time safe: a backtest only sees lessons whose outcome had actually
resolved by that date.

`DecisionEngine` (in `quorum/decision/engine.py`) turns this on by default
(`memory_log_path`) and exposes `.settle(ticker)`, which `quorum/backtest/
runner.py` calls once a ticker's date grid is done — same pattern
TradingAgents' own `run_backtest` uses. Read a run's
`results/runs/<run_id>/trading_memory.md` (or the dashboard's "Agent memory
log" expander) to see the actual reflections.

## Why there's a `backtest/portfolio.py` at all

TradingAgents ships its own `tradingagents/backtest.py`, but its docstring
is explicit: it scores a *rating* against realized/alpha return per
(ticker, date) cell, and is deliberately not a portfolio simulator — "must
not grow one," in its own words. That's the right scope for their project.
It means holding periods, position sizing, and P&L are a layer we have to
own, which is what `quorum/backtest/portfolio.py` and
`quorum/risk/gate.py` are.

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
policy allows the hosts OpenBB's providers, your LLM provider, and
`paper-api.alpaca.markets` need to reach — a restrictive default policy
will block these with a 403 at the proxy, not a Python error you can fix
in code. (All three were blocked in the environment this was originally
built in; the code is verified by inspection and against a real installed
SDK, but live connectivity has to be checked wherever this actually runs.)

### Running the dashboard

```bash
streamlit run quorum/dashboard/app.py
```

Configure tickers/date range/holding-period/risk parameters in the
sidebar and click **Run backtest** — each decision date calls the full
TradingAgents graph per ticker (several LLM calls each), so start with a
couple of tickers over a short date range before running anything wide.
Past runs are listed for comparison (equity curves, QuantStats metrics,
trade log, and the agent memory log's actual reflections) below.

### Paper trading (Alpaca)

`quorum/execution/alpaca.py`'s `AlpacaPaperExecutor` refuses to run
against anything but Alpaca's paper endpoint — this is a hard check in the
constructor, not a config flag you could accidentally flip. Every order
still goes through the same `RiskGate` the backtester uses. It does not
yet handle exits (closing a position per the holding-period/stop-loss/
take-profit rules against a live account) — only sizing and submitting a
buy from a fresh `Decision`. A live analogue of `PortfolioSimulator`'s
exit logic is the natural next piece, not yet built.

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
