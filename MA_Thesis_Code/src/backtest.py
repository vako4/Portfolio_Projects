"""
Rolling-window backtest engine.

At each month-end rebalance date t (2001-01-31 → 2024-11-30):
  1. Select the available universe: S&P 500 members on t with complete returns
     in the trailing 60-month window.
  2. Estimate the Ledoit-Wolf covariance and solve the constrained min-var QP.
  3. Record weights and apply them to the following month's (t+1) returns.

Three strategies are tracked in parallel:
  - Constrained MV  (the active strategy being tested)
  - 1/N equal-weight (naïve benchmark, same universe as MV)
  - S&P 500 index return (passive benchmark, from benchmark_returns.parquet)
"""

from __future__ import annotations

import logging
import warnings
from typing import Callable

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from tqdm import tqdm

from src.config import (
    DATA_PROCESSED,
    ESTIMATION_WINDOW,
    EVAL_END,
    EVAL_START,
    MAX_WEIGHT,
    RESULTS_FIGURES,
    RESULTS_TABLES,
    TRANSACTION_COST_BPS,
)
from src.constituents import members_on as _default_members_on
from src.optimize import compute_covariance, optimize_portfolio

logger = logging.getLogger(__name__)

# Suppress chatty solver log lines inside the tight loop.
logging.getLogger("cvxpy").setLevel(logging.ERROR)

_CACHE: dict[str, object] = {
    "weights_mv":    DATA_PROCESSED / "backtest_weights_mv.parquet",
    "weights_naive": DATA_PROCESSED / "backtest_weights_naive.parquet",
    "returns":       DATA_PROCESSED / "backtest_returns.parquet",
    "turnover":      DATA_PROCESSED / "backtest_turnover.parquet",
}
_LOG_PATH = RESULTS_TABLES / "rebalance_log.csv"


# ── helpers ────────────────────────────────────────────────────────────────────

def _series_from_pairs(pairs: list[tuple]) -> pd.Series:
    if not pairs:
        return pd.Series(dtype=float)
    dates, vals = zip(*pairs)
    return pd.Series(list(vals), index=pd.DatetimeIndex(list(dates)))


# ── public API ─────────────────────────────────────────────────────────────────

def generate_rebalance_dates(
    returns_index: pd.DatetimeIndex,
    eval_start: str = EVAL_START,
    eval_end: str   = EVAL_END,
    window: int     = ESTIMATION_WINDOW,
) -> list[pd.Timestamp]:
    """
    Return every month-end t such that:
      (a) t has ≥ *window* return observations ending at t, and
      (b) the immediately following return date falls within [eval_start, eval_end].
    """
    idx = pd.DatetimeIndex(sorted(returns_index))
    lo  = pd.Timestamp(eval_start) + pd.offsets.MonthEnd(0)
    hi  = pd.Timestamp(eval_end)   + pd.offsets.MonthEnd(0)

    return [
        idx[i]
        for i in range(window - 1, len(idx) - 1)
        if lo <= idx[i + 1] <= hi
    ]


def select_universe(
    date: pd.Timestamp,
    members_fn: Callable,
    returns_df: pd.DataFrame,
    window: int = ESTIMATION_WINDOW,
) -> list[str]:
    """
    Available universe at *date*: S&P 500 members with zero NaN values in the
    trailing *window*-month return window.
    """
    window_ret = returns_df.loc[returns_df.index <= date].tail(window)
    members    = members_fn(date)
    in_panel   = [t for t in members if t in returns_df.columns]
    sub        = window_ret[in_panel]
    return sorted(sub.columns[sub.notna().all(axis=0)].tolist())


def run_backtest(
    returns_df: pd.DataFrame,
    benchmark_returns: pd.Series,
    members_fn: Callable   = _default_members_on,
    eval_start: str        = EVAL_START,
    eval_end: str          = EVAL_END,
    window: int            = ESTIMATION_WINDOW,
    max_weight: float      = MAX_WEIGHT,
    transaction_cost_bps: int = TRANSACTION_COST_BPS,
    force_refresh: bool    = False,
) -> dict:
    """
    Execute the full rolling backtest.

    Parameters
    ----------
    returns_df           : monthly simple returns, shape (T, N).
    benchmark_returns    : monthly SPX returns aligned to the same index.
    members_fn           : callable(date) → list[str] of S&P 500 members.
    eval_start / eval_end: evaluation window.  Active returns fall in this range.
    window               : estimation window in months.
    max_weight           : per-stock weight cap passed to the optimiser.
    transaction_cost_bps : round-trip cost in basis points.
    force_refresh        : if False and cached results exist, load them.

    Returns
    -------
    dict with keys: weights_mv, weights_naive, active_returns_gross,
    active_returns_net, naive_returns, benchmark_returns, turnover, rebalance_log.
    """
    # ── Cache ──────────────────────────────────────────────────────────────────
    if (
        not force_refresh
        and all(p.exists() for p in _CACHE.values())  # type: ignore[union-attr]
        and _LOG_PATH.exists()
    ):
        logger.info("Loading backtest results from cache")
        ret_df = pd.read_parquet(_CACHE["returns"])  # type: ignore[arg-type]
        return {
            "weights_mv":           pd.read_parquet(_CACHE["weights_mv"]),  # type: ignore[arg-type]
            "weights_naive":        pd.read_parquet(_CACHE["weights_naive"]),  # type: ignore[arg-type]
            "active_returns_gross": ret_df["mv_gross"],
            "active_returns_net":   ret_df["mv_net"],
            "naive_returns":        ret_df["naive"],
            "benchmark_returns":    ret_df["benchmark"],
            "turnover":             pd.read_parquet(_CACHE["turnover"]).squeeze(),  # type: ignore[arg-type]
            "rebalance_log":        pd.read_csv(_LOG_PATH, index_col=0, parse_dates=True),
        }

    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)

    rebal_dates = generate_rebalance_dates(returns_df.index, eval_start, eval_end, window)
    all_tickers = returns_df.columns.tolist()
    logger.info("%d rebalance dates  (%s → %s)",
                len(rebal_dates),
                rebal_dates[0].date() if rebal_dates else "?",
                rebal_dates[-1].date() if rebal_dates else "?")

    wt_mv_rows:    list[pd.Series] = []
    wt_naive_rows: list[pd.Series] = []
    mv_gross_pairs:  list[tuple] = []
    mv_net_pairs:    list[tuple] = []
    naive_pairs:     list[tuple] = []
    bm_pairs:        list[tuple] = []
    turnover_pairs:  list[tuple] = []
    log_rows:        list[dict]  = []

    prev_w_mv = pd.Series(0.0, index=all_tickers)

    for t in tqdm(rebal_dates, desc="Backtest", unit="mo", ncols=80):
        t_pos     = returns_df.index.get_loc(t)
        next_date = returns_df.index[t_pos + 1]

        universe  = select_universe(t, members_fn, returns_df, window)
        n_members = len(members_fn(t))
        n_univ    = len(universe)

        # Next-month returns; fill NaN so zero-weight positions don't poison sum.
        next_ret  = returns_df.loc[next_date].fillna(0.0)
        bm_ret    = float(benchmark_returns.get(next_date, np.nan))
        bm_pairs.append((next_date, bm_ret))

        if n_univ < 20:
            logger.warning("Skipping %s — only %d stocks available", t.date(), n_univ)
            mv_gross_pairs.append((next_date, np.nan))
            mv_net_pairs.append((next_date, np.nan))
            naive_pairs.append((next_date, np.nan))
            continue

        window_ret = returns_df.loc[returns_df.index <= t].tail(window)[universe]

        # ── MV optimisation ───────────────────────────────────────────────────
        solver_status = "ok"
        w_mv = pd.Series(0.0, index=all_tickers)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                w_used = optimize_portfolio(window_ret, max_weight=max_weight)
            w_mv[universe] = w_used[universe].values
        except Exception as exc:
            solver_status = f"fallback:{str(exc)[:60]}"
            logger.warning("Solver failed at %s: %s", t.date(), exc)
            w_mv[universe] = 1.0 / n_univ

        # ── Naïve 1/N ─────────────────────────────────────────────────────────
        w_naive = pd.Series(0.0, index=all_tickers)
        w_naive[universe] = 1.0 / n_univ

        # ── Turnover ──────────────────────────────────────────────────────────
        # First period: deploying from cash = 100 % turnover by convention.
        if not log_rows:
            turnover = 1.0
        else:
            turnover = 0.5 * float((w_mv - prev_w_mv).abs().sum())

        tc = (transaction_cost_bps / 10_000) * turnover

        # ── Portfolio returns ─────────────────────────────────────────────────
        r_mv_gross = float((next_ret * w_mv).sum())
        r_naive    = float((next_ret * w_naive).sum())

        mv_gross_pairs.append((next_date, r_mv_gross))
        mv_net_pairs.append((next_date, r_mv_gross - tc))
        naive_pairs.append((next_date, r_naive))
        turnover_pairs.append((t, turnover))

        wt_mv_rows.append(w_mv.rename(t))
        wt_naive_rows.append(w_naive.rename(t))
        prev_w_mv = w_mv

        # ── Condition number ──────────────────────────────────────────────────
        try:
            cov  = compute_covariance(window_ret)
            cond = float(np.linalg.cond(cov.values))
        except Exception:
            cond = np.nan

        log_rows.append({
            "date":          t,
            "n_members":     n_members,
            "n_universe":    n_univ,
            "n_holdings_mv": int((w_mv > 1e-4).sum()),
            "max_weight_mv": float(w_mv.max()),
            "sum_weights_mv": float(w_mv.sum()),
            "turnover_mv":   turnover,
            "cond_number":   cond,
            "solver_status": solver_status,
        })

    # ── Assemble ───────────────────────────────────────────────────────────────
    weights_mv    = pd.DataFrame(wt_mv_rows)     # (n_rebal, n_tickers)
    weights_naive = pd.DataFrame(wt_naive_rows)

    r_gross  = _series_from_pairs(mv_gross_pairs)
    r_net    = _series_from_pairs(mv_net_pairs)
    r_naive  = _series_from_pairs(naive_pairs)
    r_bm     = _series_from_pairs(bm_pairs)
    turnover = _series_from_pairs(turnover_pairs)
    log_df   = pd.DataFrame(log_rows).set_index("date")

    ret_df = pd.DataFrame({"mv_gross": r_gross, "mv_net": r_net,
                           "naive": r_naive, "benchmark": r_bm})

    # ── Persist ───────────────────────────────────────────────────────────────
    weights_mv.to_parquet(_CACHE["weights_mv"])     # type: ignore[arg-type]
    weights_naive.to_parquet(_CACHE["weights_naive"]) # type: ignore[arg-type]
    ret_df.to_parquet(_CACHE["returns"])             # type: ignore[arg-type]
    turnover.to_frame(name="turnover").to_parquet(_CACHE["turnover"])  # type: ignore[arg-type]
    log_df.to_csv(_LOG_PATH)
    logger.info("Backtest saved to %s", DATA_PROCESSED)

    return {
        "weights_mv":           weights_mv,
        "weights_naive":        weights_naive,
        "active_returns_gross": r_gross,
        "active_returns_net":   r_net,
        "naive_returns":        r_naive,
        "benchmark_returns":    r_bm,
        "turnover":             turnover,
        "rebalance_log":        log_df,
    }


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    sr = pd.read_parquet(DATA_PROCESSED / "stock_returns.parquet")
    bm = pd.read_parquet(DATA_PROCESSED / "benchmark_returns.parquet").squeeze()

    results = run_backtest(returns_df=sr, benchmark_returns=bm, force_refresh=True)

    rlog    = results["rebalance_log"]
    r_gross = results["active_returns_gross"].dropna()
    r_net   = results["active_returns_net"].dropna()
    r_naive = results["naive_returns"].dropna()
    r_bm    = results["benchmark_returns"].dropna()
    turnov  = results["turnover"]

    # Align all return series to the same dates for cumulative calcs.
    common  = r_gross.index.intersection(r_naive.index).intersection(r_bm.index)
    r_gross, r_net, r_naive, r_bm = (
        r_gross[common], r_net[common], r_naive[common], r_bm[common]
    )

    def _cret(r):
        return float((1 + r).prod() - 1)

    n_fail   = int((rlog["solver_status"] != "ok").sum())
    mean_cov = float((rlog["n_universe"] / rlog["n_members"]).mean())

    print(f"\n{'='*60}")
    print("  BACKTEST SUMMARY  (2001-02 to 2024-12)")
    print(f"{'='*60}")
    print(f"  Rebalance dates       : {len(rlog)}")
    print(f"  Solver failures       : {n_fail}")
    print(f"  Active return range   : {r_gross.index[0].date()} — {r_gross.index[-1].date()}")
    print()
    print(f"  Turnover (MV, round-trip half-turnover):")
    print(f"    Mean    : {turnov.mean():.1%}")
    print(f"    Median  : {turnov.median():.1%}")
    print(f"    Max     : {turnov.max():.1%}")
    print()
    print(f"  Mean effective holdings (MV) : {rlog['n_holdings_mv'].mean():.1f}")
    print(f"  Mean coverage (univ/members) : {mean_cov:.1%}")
    print()
    print("  Total return (2001-02-28 to 2024-12-31):")
    print(f"    MV gross   :  {_cret(r_gross):+.1%}")
    print(f"    MV net     :  {_cret(r_net):+.1%}")
    print(f"    1/N        :  {_cret(r_naive):+.1%}")
    print(f"    S&P 500    :  {_cret(r_bm):+.1%}")
    print()

    # ── Cumulative return plot ─────────────────────────────────────────────────
    RESULTS_FIGURES.mkdir(parents=True, exist_ok=True)

    cum = {
        "MV gross":         (1 + r_gross).cumprod(),
        "MV net of costs":  (1 + r_net).cumprod(),
        "1/N equal-weight": (1 + r_naive).cumprod(),
        "S&P 500":          (1 + r_bm).cumprod(),
    }
    colors     = ["#1a3a5c", "#2e6da4", "#e07b39", "#888888"]
    linestyles = ["-",        "--",       "-",        ":"]
    linewidths = [1.9,        1.4,        1.4,        1.2]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, color="#e0e0e0", linewidth=0.6)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)

    for (label, series), c, ls, lw in zip(cum.items(), colors, linestyles, linewidths):
        ax.plot(series.index, series.values, color=c, linestyle=ls,
                linewidth=lw, label=label)

    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda y, _: f"{y:.0f}×")
    )
    ax.set_xlabel("Date", fontsize=10)
    ax.set_ylabel("Growth of $1  (log scale)", fontsize=10)
    ax.set_title(
        "Cumulative Returns: Constrained MV vs. 1/N vs. S&P 500  (2001–2024)",
        fontsize=11, fontweight="bold", pad=10,
    )
    ax.legend(fontsize=9, framealpha=0.8, loc="upper left")

    fig.tight_layout()
    out = RESULTS_FIGURES / "backtest_cumulative_returns.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot saved to {out}")
    print()
