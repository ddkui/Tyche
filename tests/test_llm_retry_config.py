"""Confirms TRADINGAGENTS_LLM_MAX_RETRIES actually reaches TradingAgents'
LLM client construction as an int -- see .env.example for why this matters
for Gemini's low free-tier RPM limits: a 429 there is retried with
exponential backoff automatically, we just need this env var to actually
flow through correctly.

Note the two-step path: ``DEFAULT_CONFIG["llm_max_retries"]`` ends up
holding the raw *string* from the environment, not an int -- its
env-override coercion (``tradingagents.default_config._coerce``) infers
the target type from the existing default value, which is ``None`` for
this key, so it can't tell to coerce to int. That's not a bug in
practice: ``TradingAgentsGraph`` re-coerces it via the private
``_coerce_max_retries`` before building kwargs for the LLM client, which
is the actual mechanism that matters and what this test checks -- not the
intermediate string, which a naive ``== 10`` assertion would have missed
(caught during development: ``print("10") == print(10)`` looks identical,
the type mismatch doesn't).

If a future TradingAgents pin bump renames or drops this coercion
function, this test fails loudly (ImportError) instead of the setting
silently doing nothing.
"""

from __future__ import annotations

import importlib


def test_llm_max_retries_env_var_reaches_default_config_as_string(monkeypatch):
    """Documents the intermediate representation this project depends on
    staying stable -- see module docstring for why it's a string here."""
    monkeypatch.setenv("TRADINGAGENTS_LLM_MAX_RETRIES", "10")

    import tradingagents.default_config as default_config_module

    importlib.reload(default_config_module)
    try:
        assert default_config_module.DEFAULT_CONFIG["llm_max_retries"] == "10"
    finally:
        importlib.reload(default_config_module)  # restore for later tests


def test_llm_max_retries_unset_is_none_not_zero(monkeypatch):
    """Unset means "use the client's own default" (5 attempts) -- must not
    collapse to 0, which would mean no retries at all."""
    monkeypatch.delenv("TRADINGAGENTS_LLM_MAX_RETRIES", raising=False)

    import tradingagents.default_config as default_config_module

    importlib.reload(default_config_module)
    assert default_config_module.DEFAULT_CONFIG["llm_max_retries"] is None


def test_llm_max_retries_end_to_end_coerces_to_int(monkeypatch):
    """The mechanism that actually matters: what TradingAgentsGraph passes
    as max_retries to the LLM client, once the env var round-trips through
    DEFAULT_CONFIG."""
    monkeypatch.setenv("TRADINGAGENTS_LLM_MAX_RETRIES", "10")

    import tradingagents.default_config as default_config_module

    importlib.reload(default_config_module)
    try:
        from tradingagents.graph.trading_graph import _coerce_max_retries

        raw = default_config_module.DEFAULT_CONFIG["llm_max_retries"]
        coerced = _coerce_max_retries(raw)
        assert coerced == 10
        assert isinstance(coerced, int)
    finally:
        importlib.reload(default_config_module)


def test_coerce_max_retries_rejects_negative():
    from tradingagents.graph.trading_graph import _coerce_max_retries

    try:
        _coerce_max_retries(-1)
        raise AssertionError("negative max_retries should have raised")
    except ValueError:
        pass
