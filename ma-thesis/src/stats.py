"""
Statistical inference for the MV vs. passive equity comparison.

Three test suites:
  1. Jobson-Korkie-Memmel Sharpe difference test (Memmel 2003 correction).
  2. Nested factor regressions (CAPM, FF3, FF5+MOM) with Newey-West HAC SEs.
  3. IID bootstrap confidence intervals for regime-conditional Sharpe differences.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
import scipy.stats
import statsmodels.api as sm

from src.config import DATA_PROCESSED, RESULTS_TABLES

logger = logging.getLogger(__name__)

_STRATEGIES = ["mv_gross", "mv_net", "naive", "benchmark"]
_MODELS     = ["capm", "ff3", "ff5mom"]
_REGIMES    = ["bull", "bear", "recovery"]
_PAIRS      = [
    ("mv_gross", "benchmark"),
    ("mv_gross", "naive"),
    ("mv_net",   "benchmark"),
    ("mv_net",   "naive"),
    ("naive",    "benchmark"),
]
_FACTOR_COLS: dict[str, list[str]] = {
    "capm":   ["Mkt-RF"],
    "ff3":    ["Mkt-RF", "SMB", "HML"],
    "ff5mom": ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM"],
}
_ALL_BETAS   = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM"]
_BETA_COL    = {
    "Mkt-RF": "mkt_beta", "SMB": "smb_beta", "HML": "hml_beta",
    "RMW":    "rmw_beta", "CMA": "cma_beta", "MOM": "mom_beta",
}
_NW_MAXLAGS  = 6   # floor(4*(287/100)^(2/9)) ≈ 5, rounded up to 6


# ── Test 1: Jobson-Korkie-Memmel ───────────────────────────────────────────────

def jobson_korkie_memmel(
    returns_a: pd.Series,
    returns_b: pd.Series,
    rf: pd.Series,
) -> dict:
    """
    Memmel (2003) correction to the Jobson-Korkie (1981) Sharpe ratio test.

    Uses monthly (unannualized) Sharpe ratios in the variance formula.
    Returns annualized Sharpe ratios in the output dict for interpretability.

    Returns
    -------
    dict: statistic, p_value, sharpe_a, sharpe_b, sharpe_diff (all annualized),
          n_obs, correlation
    """
    aligned = pd.concat([returns_a, returns_b, rf], axis=1, join="inner").dropna()
    aligned.columns = ["a", "b", "rf"]
    T = len(aligned)

    e_a = aligned["a"] - aligned["rf"]
    e_b = aligned["b"] - aligned["rf"]

    sr_a = float(e_a.mean() / e_a.std(ddof=1))
    sr_b = float(e_b.mean() / e_b.std(ddof=1))
    rho  = float(np.corrcoef(e_a.values, e_b.values)[0, 1])

    theta = (1 / T) * (
        2 * (1 - rho)
        + 0.5 * (sr_a**2 + sr_b**2 - 2 * sr_a * sr_b * rho**2)
    )

    if theta <= 0:
        logger.warning(
            "JKM: theta=%.4e <= 0 (degenerate case — series may be identical); returning NaN",
            theta,
        )
        z, p = float("nan"), float("nan")
    else:
        z = (sr_a - sr_b) / math.sqrt(theta)
        p = 2.0 * (1.0 - scipy.stats.norm.cdf(abs(z)))

    scale = math.sqrt(12)
    return {
        "statistic":    z,
        "p_value":      p,
        "sharpe_a":     sr_a * scale,
        "sharpe_b":     sr_b * scale,
        "sharpe_diff":  (sr_a - sr_b) * scale,
        "n_obs":        T,
        "correlation":  rho,
    }


# ── Test 2: Nested factor regressions ─────────────────────────────────────────

def factor_regression(
    excess_returns: pd.Series,
    factors: pd.DataFrame,
    model: str,
) -> dict:
    """
    OLS factor regression with Newey-West HAC standard errors (maxlags=6).

    Parameters
    ----------
    excess_returns : monthly excess returns (returns already net of rf)
    factors        : DataFrame with columns Mkt-RF, SMB, HML, RMW, CMA, MOM
    model          : 'capm', 'ff3', or 'ff5mom'

    Returns
    -------
    dict: alpha_monthly, alpha_annualized (= 12 * alpha_monthly), alpha_t_stat,
          alpha_p_value, betas, betas_t_stats, r_squared, n_obs, model_name
    """
    if model not in _FACTOR_COLS:
        raise ValueError(f"Unknown model '{model}'. Choose from {list(_FACTOR_COLS)}")

    cols    = _FACTOR_COLS[model]
    aligned = pd.concat(
        [excess_returns, factors[cols]], axis=1, join="inner"
    ).dropna()
    y = aligned.iloc[:, 0]
    X = aligned.iloc[:, 1:]

    res = sm.OLS(y, sm.add_constant(X)).fit(
        cov_type="HAC", cov_kwds={"maxlags": _NW_MAXLAGS}
    )

    alpha_monthly = float(res.params["const"])
    betas         = {col: float(res.params[col])  for col in cols}
    betas_t       = {col: float(res.tvalues[col]) for col in cols}

    return {
        "alpha_monthly":    alpha_monthly,
        "alpha_annualized": alpha_monthly * 12,
        "alpha_t_stat":     float(res.tvalues["const"]),
        "alpha_p_value":    float(res.pvalues["const"]),
        "betas":            betas,
        "betas_t_stats":    betas_t,
        "r_squared":        float(res.rsquared),
        "n_obs":            int(res.nobs),
        "model_name":       model,
    }


# ── Test 3: Bootstrap Sharpe difference CIs ───────────────────────────────────

def bootstrap_sharpe_diff(
    returns_a: pd.Series,
    returns_b: pd.Series,
    rf: pd.Series,
    n_boot: int = 10_000,
    ci_level: float = 0.95,
    random_state: int = 42,
) -> dict:
    """
    IID bootstrap confidence interval for the annualized Sharpe ratio difference.

    Parameters
    ----------
    returns_a, returns_b : monthly simple returns
    rf                   : monthly risk-free rate
    n_boot               : bootstrap replications (default 10 000)
    ci_level             : confidence level (default 0.95)
    random_state         : RNG seed for reproducibility

    Returns
    -------
    dict: point_estimate, ci_low, ci_high, n_obs, n_boot,
          significant (True if 0 is not in [ci_low, ci_high])
    """
    aligned = pd.concat([returns_a, returns_b, rf], axis=1, join="inner").dropna()
    aligned.columns = ["a", "b", "rf"]
    T = len(aligned)

    if T < 6:
        raise ValueError(
            f"bootstrap_sharpe_diff: only {T} observations — refusing to run (minimum 6)."
        )
    if T < 12:
        logger.warning(
            "bootstrap_sharpe_diff: only %d observations — results unreliable.", T
        )

    def _ann_sr_diff(df: pd.DataFrame) -> float:
        e_a = df["a"] - df["rf"]
        e_b = df["b"] - df["rf"]
        return float(
            (e_a.mean() / e_a.std(ddof=1) - e_b.mean() / e_b.std(ddof=1))
            * math.sqrt(12)
        )

    point_estimate = _ann_sr_diff(aligned)

    rng        = np.random.default_rng(random_state)
    boot_diffs = np.empty(n_boot)
    vals       = aligned.values
    for i in range(n_boot):
        idx            = rng.integers(0, T, size=T)
        boot_diffs[i]  = _ann_sr_diff(
            pd.DataFrame(vals[idx], columns=["a", "b", "rf"])
        )

    alpha   = 1.0 - ci_level
    ci_low  = float(np.percentile(boot_diffs, 100 * alpha / 2))
    ci_high = float(np.percentile(boot_diffs, 100 * (1 - alpha / 2)))

    return {
        "point_estimate": point_estimate,
        "ci_low":         ci_low,
        "ci_high":        ci_high,
        "n_obs":          T,
        "n_boot":         n_boot,
        "significant":    bool(ci_low > 0 or ci_high < 0),
    }


# ── Orchestrators ──────────────────────────────────────────────────────────────

def run_sharpe_tests(
    returns_df: pd.DataFrame,
    rf: pd.Series,
    eval_start: str = "2001-02-28",
    subsample_start: str = "2015-01-01",
) -> dict[str, pd.DataFrame]:
    """
    JKM Sharpe difference tests for all strategy pairs.

    Returns dict with keys 'full_period' and 'post_2015', each a DataFrame
    indexed by pair label with columns:
        sharpe_a_ann, sharpe_b_ann, sharpe_diff_ann, correlation,
        jkm_statistic, p_value, n_obs
    """
    eval_lo = pd.Timestamp(eval_start)
    post_lo = pd.Timestamp(subsample_start)
    rf_s    = rf.squeeze()
    ret     = returns_df[returns_df.index >= eval_lo]

    def _table(idx: pd.DatetimeIndex) -> pd.DataFrame:
        rows: dict[str, dict] = {}
        for a, b in _PAIRS:
            r = jobson_korkie_memmel(ret.loc[idx, a], ret.loc[idx, b], rf_s)
            rows[f"{a} vs {b}"] = {
                "sharpe_a_ann":    r["sharpe_a"],
                "sharpe_b_ann":    r["sharpe_b"],
                "sharpe_diff_ann": r["sharpe_diff"],
                "correlation":     r["correlation"],
                "jkm_statistic":   r["statistic"],
                "p_value":         r["p_value"],
                "n_obs":           r["n_obs"],
            }
        df = pd.DataFrame(rows).T
        df.index.name = "pair"
        return df

    return {
        "full_period": _table(ret.index),
        "post_2015":   _table(ret.index[ret.index >= post_lo]),
    }


def run_factor_regressions(
    returns_df: pd.DataFrame,
    rf: pd.Series,
    factors: pd.DataFrame,
    eval_start: str = "2001-02-28",
    subsample_start: str = "2015-01-01",
) -> dict[str, pd.DataFrame]:
    """
    Nested factor regressions for each strategy x model combination.

    Returns dict with keys 'full_period' and 'post_2015', each a DataFrame
    with MultiIndex rows (strategy, model) and columns:
        alpha_annualized, alpha_t_stat, alpha_p_value,
        mkt_beta, smb_beta, hml_beta, rmw_beta, cma_beta, mom_beta,
        r_squared, n_obs
    """
    eval_lo = pd.Timestamp(eval_start)
    post_lo = pd.Timestamp(subsample_start)
    rf_s    = rf.squeeze()
    ret     = returns_df[returns_df.index >= eval_lo]

    def _table(idx: pd.DatetimeIndex) -> pd.DataFrame:
        rows: dict[tuple, dict] = {}
        for strategy in _STRATEGIES:
            excess      = (ret.loc[idx, strategy] - rf_s.reindex(idx)).dropna()
            excess.name = strategy
            for model in _MODELS:
                res  = factor_regression(excess, factors, model)
                row  = {
                    "alpha_annualized": res["alpha_annualized"],
                    "alpha_t_stat":     res["alpha_t_stat"],
                    "alpha_p_value":    res["alpha_p_value"],
                    "r_squared":        res["r_squared"],
                    "n_obs":            res["n_obs"],
                }
                for fac, col in _BETA_COL.items():
                    row[col] = res["betas"].get(fac, float("nan"))
                rows[(strategy, model)] = row

        mi = pd.MultiIndex.from_tuples(rows.keys(), names=["strategy", "model"])
        df = pd.DataFrame(list(rows.values()), index=mi)
        col_order = [
            "alpha_annualized", "alpha_t_stat", "alpha_p_value",
            "mkt_beta", "smb_beta", "hml_beta", "rmw_beta", "cma_beta", "mom_beta",
            "r_squared", "n_obs",
        ]
        return df[col_order]

    return {
        "full_period": _table(ret.index),
        "post_2015":   _table(ret.index[ret.index >= post_lo]),
    }


def run_regime_bootstrap(
    returns_df: pd.DataFrame,
    rf: pd.Series,
    regimes: pd.Series,
    regime_name: str,
    eval_start: str = "2001-02-28",
    n_boot: int = 10_000,
) -> pd.DataFrame:
    """
    Bootstrap Sharpe difference CIs for each strategy pair x regime.

    Returns a DataFrame with MultiIndex rows (pair, regime) and columns:
        point_estimate, ci_low, ci_high, significant, n_obs, n_boot
    """
    eval_lo = pd.Timestamp(eval_start)
    rf_s    = rf.squeeze()
    ret     = returns_df[returns_df.index >= eval_lo]
    reg     = regimes.squeeze().reindex(ret.index)

    rows: dict[tuple, dict] = {}
    for a, b in _PAIRS:
        pair_key = f"{a} vs {b}"
        for regime in _REGIMES:
            mask = reg == regime
            idx  = ret.index[mask]
            n    = int(mask.sum())
            key  = (pair_key, regime)
            if n < 6:
                logger.warning(
                    "regime_bootstrap [%s]: '%s' / '%s' has only %d obs — skipping.",
                    regime_name, pair_key, regime, n,
                )
                rows[key] = dict(
                    point_estimate=float("nan"), ci_low=float("nan"),
                    ci_high=float("nan"), significant=False, n_obs=n, n_boot=n_boot,
                )
                continue
            try:
                res = bootstrap_sharpe_diff(ret.loc[idx, a], ret.loc[idx, b], rf_s, n_boot=n_boot)
            except Exception as exc:
                logger.warning(
                    "regime_bootstrap [%s]: '%s' / '%s' error: %s",
                    regime_name, pair_key, regime, exc,
                )
                rows[key] = dict(
                    point_estimate=float("nan"), ci_low=float("nan"),
                    ci_high=float("nan"), significant=False, n_obs=n, n_boot=n_boot,
                )
                continue
            rows[key] = dict(
                point_estimate=res["point_estimate"],
                ci_low=res["ci_low"],
                ci_high=res["ci_high"],
                significant=res["significant"],
                n_obs=n,
                n_boot=n_boot,
            )

    mi = pd.MultiIndex.from_tuples(rows.keys(), names=["pair", "regime"])
    return pd.DataFrame(list(rows.values()), index=mi)


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    # ── Load inputs ───────────────────────────────────────────────────────────
    returns_df = pd.read_parquet(DATA_PROCESSED / "backtest_returns.parquet")
    rf         = pd.read_parquet(DATA_PROCESSED / "risk_free.parquet").squeeze()
    factors    = pd.read_parquet(DATA_PROCESSED / "factors.parquet")
    reg_main   = pd.read_parquet(DATA_PROCESSED / "regimes_main.parquet")
    reg_sens   = pd.read_parquet(DATA_PROCESSED / "regimes_sensitivity.parquet")

    for obj in (returns_df, factors, reg_main, reg_sens):
        obj.index = pd.to_datetime(obj.index)
    rf.index = pd.to_datetime(rf.index)

    logger.info(
        "Loaded %d months (%s to %s)",
        len(returns_df), returns_df.index[0].date(), returns_df.index[-1].date(),
    )

    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)

    # ── Test 1: JKM Sharpe tests ──────────────────────────────────────────────
    logger.info("Running Jobson-Korkie-Memmel tests ...")
    sharpe_tests = run_sharpe_tests(returns_df, rf)
    sharpe_tests["full_period"].to_csv(RESULTS_TABLES / "sharpe_tests_full_period.csv")
    sharpe_tests["post_2015"].to_csv(RESULTS_TABLES   / "sharpe_tests_post_2015.csv")
    logger.info("Saved sharpe_tests_full_period.csv, sharpe_tests_post_2015.csv")

    # ── Test 2: Factor regressions ────────────────────────────────────────────
    logger.info("Running factor regressions (CAPM / FF3 / FF5+MOM, NW lags=%d) ...", _NW_MAXLAGS)
    regressions = run_factor_regressions(returns_df, rf, factors)
    regressions["full_period"].to_csv(RESULTS_TABLES / "factor_regressions_full_period.csv")
    regressions["post_2015"].to_csv(RESULTS_TABLES   / "factor_regressions_post_2015.csv")
    logger.info("Saved factor_regressions_full_period.csv, factor_regressions_post_2015.csv")

    # ── Test 3: Regime bootstrap CIs ──────────────────────────────────────────
    logger.info("Running regime-conditional bootstrap CIs (n_boot=10 000) ...")
    boot_main = run_regime_bootstrap(returns_df, rf, reg_main, "main")
    boot_sens = run_regime_bootstrap(returns_df, rf, reg_sens, "sensitivity")
    boot_main.to_csv(RESULTS_TABLES / "regime_bootstrap_main.csv")
    boot_sens.to_csv(RESULTS_TABLES / "regime_bootstrap_sensitivity.csv")
    logger.info("Saved regime_bootstrap_main.csv, regime_bootstrap_sensitivity.csv")

    # ── Headline summary table ────────────────────────────────────────────────
    fp  = sharpe_tests["full_period"]
    p15 = sharpe_tests["post_2015"]
    rfp = regressions["full_period"]
    rp15= regressions["post_2015"]

    mvb_fp  = fp.loc["mv_gross vs benchmark"]
    mvb_p15 = p15.loc["mv_gross vs benchmark"]

    headline = pd.DataFrame({
        "Full period": {
            "MV gross Sharpe (ann.)":           mvb_fp["sharpe_a_ann"],
            "Benchmark Sharpe (ann.)":          mvb_fp["sharpe_b_ann"],
            "JKM p-value (MV vs benchmark)":    mvb_fp["p_value"],
            "MV gross CAPM alpha (ann., %)":    rfp.loc[("mv_gross", "capm"),   "alpha_annualized"] * 100,
            "CAPM alpha t-stat":                rfp.loc[("mv_gross", "capm"),   "alpha_t_stat"],
            "MV gross FF3 alpha (ann., %)":     rfp.loc[("mv_gross", "ff3"),    "alpha_annualized"] * 100,
            "FF3 alpha t-stat":                 rfp.loc[("mv_gross", "ff3"),    "alpha_t_stat"],
            "MV gross FF5+MOM alpha (ann., %)": rfp.loc[("mv_gross", "ff5mom"), "alpha_annualized"] * 100,
            "FF5+MOM alpha t-stat":             rfp.loc[("mv_gross", "ff5mom"), "alpha_t_stat"],
        },
        "Post-2015": {
            "MV gross Sharpe (ann.)":           mvb_p15["sharpe_a_ann"],
            "Benchmark Sharpe (ann.)":          mvb_p15["sharpe_b_ann"],
            "JKM p-value (MV vs benchmark)":    mvb_p15["p_value"],
            "MV gross CAPM alpha (ann., %)":    rp15.loc[("mv_gross", "capm"),   "alpha_annualized"] * 100,
            "CAPM alpha t-stat":                rp15.loc[("mv_gross", "capm"),   "alpha_t_stat"],
            "MV gross FF3 alpha (ann., %)":     rp15.loc[("mv_gross", "ff3"),    "alpha_annualized"] * 100,
            "FF3 alpha t-stat":                 rp15.loc[("mv_gross", "ff3"),    "alpha_t_stat"],
            "MV gross FF5+MOM alpha (ann., %)": rp15.loc[("mv_gross", "ff5mom"), "alpha_annualized"] * 100,
            "FF5+MOM alpha t-stat":             rp15.loc[("mv_gross", "ff5mom"), "alpha_t_stat"],
        },
    })
    headline.index.name = "metric"
    headline.to_csv(RESULTS_TABLES / "headline_results.csv")
    logger.info("Saved headline_results.csv")

    # Print headline table
    print()
    print("=" * 72)
    print("  HEADLINE RESULTS")
    print("=" * 72)
    print(headline.round(4).to_string())

    # ── Narrative summary ─────────────────────────────────────────────────────
    def _sig(p: float) -> str:
        return "significant" if p < 0.05 else "not significant"

    jkm_fp_diff = float(mvb_fp["sharpe_diff_ann"])
    jkm_fp_p    = float(mvb_fp["p_value"])
    jkm_p15_diff= float(mvb_p15["sharpe_diff_ann"])
    jkm_p15_p   = float(mvb_p15["p_value"])

    capm_a  = float(rfp.loc[("mv_gross", "capm"),   "alpha_annualized"]) * 100
    capm_t  = float(rfp.loc[("mv_gross", "capm"),   "alpha_t_stat"])
    ff5_a   = float(rfp.loc[("mv_gross", "ff5mom"), "alpha_annualized"]) * 100
    ff5_t   = float(rfp.loc[("mv_gross", "ff5mom"), "alpha_t_stat"])

    shrink_pp  = capm_a - ff5_a
    shrink_pct = (shrink_pp / capm_a * 100) if abs(capm_a) > 1e-10 else float("nan")

    print()
    print("=" * 72)
    print("  NARRATIVE SUMMARY")
    print("=" * 72)
    print(
        f"  Full-period  MV gross vs benchmark Sharpe diff: {jkm_fp_diff:+.4f}, "
        f"p = {jkm_fp_p:.3f} ({_sig(jkm_fp_p)})"
    )
    print(
        f"  Post-2015    MV gross vs benchmark Sharpe diff: {jkm_p15_diff:+.4f}, "
        f"p = {jkm_p15_p:.3f} ({_sig(jkm_p15_p)})"
    )
    print(f"  Full-period  MV gross CAPM alpha:    {capm_a:+.2f}%,  t = {capm_t:.2f}")
    print(f"  Full-period  MV gross FF5+MOM alpha: {ff5_a:+.2f}%,  t = {ff5_t:.2f}")
    print(
        f"  Alpha shrinkage CAPM -> FF5+MOM: {shrink_pp:.2f} pp "
        f"({shrink_pct:.1f}% reduction)"
    )
    print()
