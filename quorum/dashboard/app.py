"""Streamlit dashboard: launch backtest runs, compare them, read what the
agents' memory log actually learned.

Run with: ``streamlit run quorum/dashboard/app.py``

Deliberately thin: all the actual logic (running a backtest, scoring a run)
lives in ``quorum.backtest.runner`` and ``quorum.dashboard.data``, which are
plain Python and unit-testable without Streamlit. This file is just the UI
wiring on top of proven libraries (Streamlit for the app shell, QuantStats
for the metrics) rather than a custom-built dashboard.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from quorum.backtest.runner import RunConfig, run_backtest
from quorum.config import DEFAULT_HOLDING_PERIOD, DEFAULT_RISK_LIMITS, HoldingPeriodConfig, RiskLimits
from quorum.dashboard.data import compare_runs, list_run_dirs, load_run

st.set_page_config(page_title="Quorum backtests", layout="wide")
st.title("Quorum — backtest dashboard")

with st.sidebar:
    st.header("New backtest run")
    st.caption(
        "Each decision date runs the full TradingAgents graph per ticker — "
        "several LLM calls each. A wide ticker list x date range is slow "
        "and not free; start small."
    )
    tickers_input = st.text_input("Tickers (comma-separated)", value="AAPL,MSFT")
    start_date = st.text_input("Start date (YYYY-MM-DD)")
    end_date = st.text_input("End date (YYYY-MM-DD)")
    decision_every_n_days = st.number_input(
        "Re-run decision graph every N trading days", min_value=1, value=5
    )
    starting_cash = st.number_input("Starting cash", min_value=1000.0, value=100_000.0, step=1000.0)

    st.subheader("Holding period")
    target_holding_days = st.number_input(
        "Target holding days", min_value=1, value=DEFAULT_HOLDING_PERIOD.target_holding_days
    )
    max_holding_days = st.number_input(
        "Max holding days", min_value=1, value=DEFAULT_HOLDING_PERIOD.max_holding_days
    )
    stop_loss_pct = st.number_input(
        "Stop-loss %", min_value=0.0, max_value=1.0, value=DEFAULT_HOLDING_PERIOD.stop_loss_pct
    )
    take_profit_pct = st.number_input(
        "Take-profit %", min_value=0.0, max_value=5.0, value=DEFAULT_HOLDING_PERIOD.take_profit_pct
    )

    st.subheader("Risk limits")
    max_position_pct = st.number_input(
        "Max position % of equity", min_value=0.0, max_value=1.0,
        value=DEFAULT_RISK_LIMITS.max_position_pct_of_equity,
    )
    max_open_positions = st.number_input(
        "Max open positions", min_value=1, value=DEFAULT_RISK_LIMITS.max_open_positions
    )
    daily_kill_switch_pct = st.number_input(
        "Daily loss kill-switch %", min_value=0.0, max_value=1.0,
        value=DEFAULT_RISK_LIMITS.daily_loss_kill_switch_pct,
    )

    run_clicked = st.button("Run backtest", type="primary")

if run_clicked:
    tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
    if not tickers or not start_date or not end_date:
        st.error("Tickers, start date, and end date are all required.")
    else:
        config = RunConfig(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            decision_every_n_days=int(decision_every_n_days),
            starting_cash=starting_cash,
            holding_period=HoldingPeriodConfig(
                min_holding_days=DEFAULT_HOLDING_PERIOD.min_holding_days,
                target_holding_days=int(target_holding_days),
                max_holding_days=int(max_holding_days),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            ),
            risk_limits=RiskLimits(
                max_position_pct_of_equity=max_position_pct,
                max_gross_exposure=DEFAULT_RISK_LIMITS.max_gross_exposure,
                max_open_positions=int(max_open_positions),
                max_sector_exposure_pct=DEFAULT_RISK_LIMITS.max_sector_exposure_pct,
                daily_loss_kill_switch_pct=daily_kill_switch_pct,
            ),
        )
        with st.spinner(f"Running backtest over {len(tickers)} ticker(s)... this calls an LLM per decision."):
            try:
                run_dir = run_backtest(config)
                st.success(f"Run complete: {run_dir.name}")
            except Exception as exc:
                st.error(f"Backtest failed: {exc}")

st.header("Past runs")
run_dirs = list_run_dirs()

if not run_dirs:
    st.info("No runs yet — configure one in the sidebar and click **Run backtest**.")
else:
    labels = [p.name for p in run_dirs]
    selected_labels = st.multiselect("Select runs to compare", labels, default=labels[:3])
    selected_dirs = [p for p in run_dirs if p.name in selected_labels]

    if selected_dirs:
        st.subheader("Comparison")
        st.dataframe(compare_runs(selected_dirs), use_container_width=True)

        st.subheader("Equity curves (normalized to 100 at start)")
        curves = {}
        for run_dir in selected_dirs:
            run = load_run(run_dir)
            if len(run.equity) > 0:
                curves[run.run_id] = 100 * run.equity / run.equity.iloc[0]
        if curves:
            st.line_chart(pd.DataFrame(curves))

        st.subheader("Run detail")
        detail_label = st.selectbox("Inspect one run", selected_labels)
        detail_dir = next(p for p in selected_dirs if p.name == detail_label)
        detail = load_run(detail_dir)

        st.write("**Trade log**")
        st.dataframe(detail.trades, use_container_width=True)

        memory_path = detail_dir / "trading_memory.md"
        if memory_path.exists():
            with st.expander("Agent memory log (decisions + reflections on what happened)"):
                st.markdown(memory_path.read_text())
        else:
            st.caption("No memory log found for this run.")
