"""
Descriptive performance metrics for the MV vs. passive equity comparison.

Computes annualised return, volatility, Sharpe ratio, Sortino ratio, and
maximum drawdown over four evaluation windows: full period, post-2015
subsample, and per-regime slices under both the main (-20%) and
sensitivity (-15%) regime classifications.

Jensen's alpha and factor regressions belong in stats.py, not here.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import DATA_PROCESSED, RESULTS_TABLES

logger = logging.getLogger(__name__)

_STRATEGIES  = ["mv_gross", "mv_net", "naive", "benchmark"]
_REGIMES     = ["bull", "bear", "recovery"]
_METRIC_COLS = [
    "n_months", "total_return", "ann_return", "ann_volatility",
    "sharpe", "sortino", "max_drawdown",
]


# ── individual metric functions ────────────────────────────────────────────────

def annualized_return(returns: pd.Series) -> float:
    """Geometric annualised return: ((1+r).prod())^(12/n) - 1."""
    returns = returns.dropna()
    return float(((1 + returns).prod()) ** (12 / len(returns)) - 1)


def annualized_volatility(returns: pd.Series) -> float:
    """Sample std scaled to annual: std(ddof=1) * sqrt(12)."""
    returns = returns.dropna()
    return float(returns.std(ddof=1) * math.sqrt(12))


def sharpe_ratio(returns: pd.Series, rf: pd.Series) -> float:
    """Annualised Sharpe ratio: (mean excess) / (std excess) * sqrt(12)."""
    aligned = pd.concat([returns, rf], axis=1, join="inner").dropna()
    excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    return float(excess.mean() / excess.std(ddof=1) * math.sqrt(12))


def sortino_ratio(
    returns: pd.Series,
    rf: pd.Series,
    threshold: float = 0.0,
) -> float:
    """
    Annualised Sortino ratio.

    Downside deviation = sqrt(mean(min(excess - threshold, 0)^2)).
    threshold=0 means months where the portfolio return falls below the
    risk-free rate count as downside.  Returns NaN (with a warning) if
    there are no downside observations.
    """
    aligned  = pd.concat([returns, rf], axis=1, join="inner").dropna()
    excess   = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    downside = np.minimum(excess - threshold, 0.0)
    if (downside < 0).sum() == 0:
        logger.warning(
            "sortino_ratio: no observations below threshold=%.4f for '%s'; returning NaN",
            threshold, returns.name,
        )
        return float("nan")
    downside_dev = math.sqrt(float((downside ** 2).mean()))
    return float(excess.mean() / downside_dev * math.sqrt(12))


def max_drawdown(returns: pd.Series) -> float:
    """
    Maximum peak-to-trough drawdown.  Returns a negative number.
    Computed on (1+r).cumprod() so month ordering matters.
    """
    returns = returns.dropna()
    prices  = (1 + returns).cumprod()
    dd      = prices / prices.cummax() - 1
    return float(dd.min())


def compute_all_metrics(returns: pd.Series, rf: pd.Series) -> dict:
    """
    Compute all seven metrics for a single return series.

    Parameters
    ----------
    returns : monthly simple returns
    rf      : monthly risk-free rate (same unit; aligned internally via inner join)

    Returns
    -------
    dict with keys matching _METRIC_COLS
    """
    returns = returns.dropna()
    return {
        "n_months":       int(len(returns)),
        "total_return":   float((1 + returns).prod() - 1),
        "ann_return":     annualized_return(returns),
        "ann_volatility": annualized_volatility(returns),
        "sharpe":         sharpe_ratio(returns, rf),
        "sortino":        sortino_ratio(returns, rf),
        "max_drawdown":   max_drawdown(returns),
    }


# ── orchestrator ───────────────────────────────────────────────────────────────

def build_metrics_table(
    returns_df: pd.DataFrame,
    rf: pd.Series,
    regimes_main: pd.Series,
    regimes_sensitivity: pd.Series,
    eval_start: str = "2001-02-28",
    subsample_start: str = "2015-01-01",
) -> dict[str, pd.DataFrame]:
    """
    Build four metrics DataFrames covering the full evaluation window.

    Parameters
    ----------
    returns_df           : DataFrame with columns mv_gross, mv_net, naive, benchmark
    rf                   : monthly risk-free rate Series (squeezed to 1-D)
    regimes_main         : month-level regime labels from the -20% rule
    regimes_sensitivity  : month-level regime labels from the -15% rule
    eval_start           : first month of the evaluation window (inclusive)
    subsample_start      : first month of the post-2015 subsample (inclusive)

    Returns
    -------
    dict with keys: full_period, post_2015, by_regime_main, by_regime_sensitivity
    """
    eval_lo    = pd.Timestamp(eval_start)
    post_lo    = pd.Timestamp(subsample_start)
    rf_s       = rf.squeeze()
    returns_df = returns_df[returns_df.index >= eval_lo].copy()

    def _table_for_index(idx: pd.DatetimeIndex) -> pd.DataFrame:
        rows = {}
        for col in _STRATEGIES:
            ret = returns_df.loc[idx, col]
            if int(ret.dropna().__len__()) < 12:
                logger.warning(
                    "Strategy '%s': only %d observation(s) in subset — metrics unreliable.",
                    col, int(ret.dropna().__len__()),
                )
            rows[col] = compute_all_metrics(ret, rf_s)
        df = pd.DataFrame(rows, index=_METRIC_COLS).T
        df.index.name = "strategy"
        return df

    full_period = _table_for_index(returns_df.index)
    post_2015   = _table_for_index(returns_df.index[returns_df.index >= post_lo])

    def _regime_table(regimes: pd.Series) -> pd.DataFrame:
        reg = regimes.squeeze().reindex(returns_df.index)
        index_tuples: list[tuple[str, str]] = []
        records: list[dict] = []
        for strategy in _STRATEGIES:
            for regime in _REGIMES:
                mask = reg == regime
                ret  = returns_df.loc[mask, strategy]
                n    = int(ret.dropna().__len__())
                if n < 12:
                    logger.warning(
                        "Regime '%s' / strategy '%s': only %d month(s) — metrics unreliable.",
                        regime, strategy, n,
                    )
                index_tuples.append((strategy, regime))
                records.append(compute_all_metrics(ret, rf_s))

        mi = pd.MultiIndex.from_tuples(index_tuples, names=["strategy", "regime"])
        return pd.DataFrame(records, index=mi, columns=_METRIC_COLS)

    by_regime_main        = _regime_table(regimes_main)
    by_regime_sensitivity = _regime_table(regimes_sensitivity)

    return {
        "full_period":           full_period,
        "post_2015":             post_2015,
        "by_regime_main":        by_regime_main,
        "by_regime_sensitivity": by_regime_sensitivity,
    }


# ── display helper ─────────────────────────────────────────────────────────────

def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    """Return a string-formatted copy for console display."""
    out = df.copy().astype(object)
    pct_cols   = ["total_return", "ann_return", "ann_volatility", "max_drawdown"]
    ratio_cols = ["sharpe", "sortino"]
    for col in pct_cols:
        if col in out.columns:
            out[col] = df[col].map(
                lambda x: f"{x * 100:+.2f}%" if pd.notna(x) else "NaN"
            )
    for col in ratio_cols:
        if col in out.columns:
            out[col] = df[col].map(
                lambda x: f"{x:.4f}" if pd.notna(x) else "NaN"
            )
    if "n_months" in out.columns:
        out["n_months"] = df["n_months"].astype(int)
    return out


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    returns_df = pd.read_parquet(DATA_PROCESSED / "backtest_returns.parquet")
    rf         = pd.read_parquet(DATA_PROCESSED / "risk_free.parquet").squeeze()
    reg_main   = pd.read_parquet(DATA_PROCESSED / "regimes_main.parquet")
    reg_sens   = pd.read_parquet(DATA_PROCESSED / "regimes_sensitivity.parquet")

    for obj in (returns_df, reg_main, reg_sens):
        obj.index = pd.to_datetime(obj.index)
    rf.index = pd.to_datetime(rf.index)

    logger.info(
        "Loaded %d months of backtest returns (%s to %s)",
        len(returns_df), returns_df.index[0].date(), returns_df.index[-1].date(),
    )

    tables = build_metrics_table(returns_df, rf, reg_main, reg_sens)

    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)

    _FILENAMES = {
        "full_period":           "metrics_full_period.csv",
        "post_2015":             "metrics_post_2015.csv",
        "by_regime_main":        "metrics_by_regime_main.csv",
        "by_regime_sensitivity": "metrics_by_regime_sensitivity.csv",
    }
    _TITLES = {
        "full_period":           "FULL PERIOD  (2001-02 to 2024-12)",
        "post_2015":             "POST-2015 SUBSAMPLE  (2015-01 onward)",
        "by_regime_main":        "BY REGIME  --  MAIN (-20% threshold)",
        "by_regime_sensitivity": "BY REGIME  --  SENSITIVITY (-15% threshold)",
    }

    for key, df in tables.items():
        df.to_csv(RESULTS_TABLES / _FILENAMES[key])
        logger.info("Saved %s", _FILENAMES[key])

        print()
        print("=" * 95)
        print(f"  {_TITLES[key]}")
        print("=" * 95)
        print(_fmt(df).to_string())

    # ── Headline summary ──────────────────────────────────────────────────────
    fp  = tables["full_period"]
    p15 = tables["post_2015"]

    sharpe_diff_full = fp.loc["mv_gross",  "sharpe"]        - fp.loc["benchmark",  "sharpe"]
    sharpe_diff_post = p15.loc["mv_gross", "sharpe"]        - p15.loc["benchmark", "sharpe"]
    mdd_mvg_full     = fp.loc["mv_gross",  "max_drawdown"]
    mdd_bm_full      = fp.loc["benchmark", "max_drawdown"]
    mdd_mvg_post     = p15.loc["mv_gross", "max_drawdown"]
    mdd_bm_post      = p15.loc["benchmark","max_drawdown"]

    print()
    print("=" * 62)
    print("  HEADLINE SUMMARY")
    print("=" * 62)
    print(f"  Sharpe  full-period  MV gross vs benchmark:  {sharpe_diff_full:+.4f}")
    print(f"  Sharpe  post-2015    MV gross vs benchmark:  {sharpe_diff_post:+.4f}")
    print(f"  Max DD  full-period  MV gross: {mdd_mvg_full * 100:+.2f}%   benchmark: {mdd_bm_full * 100:+.2f}%")
    print(f"  Max DD  post-2015    MV gross: {mdd_mvg_post * 100:+.2f}%   benchmark: {mdd_bm_post * 100:+.2f}%")
    print()
