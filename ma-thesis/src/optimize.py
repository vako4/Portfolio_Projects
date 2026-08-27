"""
Constrained minimum-variance portfolio optimisation.

Solves:
    min  w' Σ w
    s.t. sum(w) = 1
         0 ≤ w_i ≤ max_weight  for all i

where Σ is estimated via Ledoit-Wolf shrinkage.  Because expected returns are
treated as equal across all stocks, the mean-variance problem collapses to pure
variance minimisation — consistent with Clarke, De Silva & Thorley (2006).
"""

from __future__ import annotations

import logging
import math

import cvxpy as cp
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from src.config import MAX_WEIGHT

logger = logging.getLogger(__name__)


# ── public API ─────────────────────────────────────────────────────────────────

def compute_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """
    Estimate the covariance matrix of *returns* using Ledoit-Wolf shrinkage.

    Parameters
    ----------
    returns : shape (T, N).  Rows = monthly observations, columns = tickers.

    Returns
    -------
    pd.DataFrame of shape (N', N') where N' = tickers that have no NaN in the
    window.  Index and columns are both ticker symbols.
    """
    # Drop any ticker that has at least one NaN in this window (insufficient history).
    clean = returns.dropna(axis=1)
    if clean.shape[1] == 0:
        raise ValueError("No tickers have complete data in the supplied window.")

    lw = LedoitWolf(assume_centered=False)
    lw.fit(clean.values)

    return pd.DataFrame(lw.covariance_, index=clean.columns, columns=clean.columns)


def solve_min_variance(
    cov: pd.DataFrame,
    max_weight: float = MAX_WEIGHT,
) -> pd.Series:
    """
    Solve the constrained minimum-variance QP given *cov*.

    Parameters
    ----------
    cov        : symmetric positive semi-definite covariance matrix (tickers × tickers).
    max_weight : upper bound on each individual weight.

    Returns
    -------
    pd.Series of optimal weights indexed by ticker.  Weights are clipped to [0, 1]
    and renormalised so they sum exactly to 1.

    Raises
    ------
    ValueError  if the universe is smaller than ceil(1/max_weight) stocks.
    RuntimeError if the solver fails after the fallback attempt.
    """
    n = len(cov)
    min_n = math.ceil(1.0 / max_weight)
    if n < min_n:
        raise ValueError(
            f"Universe has only {n} stocks but min-variance with max_weight="
            f"{max_weight} requires at least {min_n}."
        )

    w    = cp.Variable(n)
    cov_np = cov.values.astype(float)

    objective   = cp.Minimize(cp.quad_form(w, cov_np))
    constraints = [cp.sum(w) == 1, w >= 0, w <= max_weight]
    prob        = cp.Problem(objective, constraints)

    # Try CLARABEL first (fast modern QP solver bundled with cvxpy).
    try:
        prob.solve(solver=cp.CLARABEL, verbose=False)
        if prob.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
            raise RuntimeError(f"CLARABEL status: {prob.status}")
    except Exception as primary_exc:
        logger.warning("CLARABEL failed (%s) — falling back to SCS", primary_exc)
        prob.solve(solver=cp.SCS, verbose=False)
        if prob.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
            raise RuntimeError(
                f"SCS also failed (status={prob.status}) after CLARABEL error: {primary_exc}"
            )

    raw = np.asarray(w.value, dtype=float).flatten()

    # Numerical hygiene: clip tiny negatives, renormalise.
    assert np.all(raw >= -1e-6), f"Large negative weight found: {raw.min():.6f}"
    raw = np.clip(raw, 0.0, None)
    total = raw.sum()
    assert abs(total - 1.0) < 1e-4, f"Weights sum to {total:.8f} before renorm"
    weights = raw / total

    assert weights.max() <= max_weight + 1e-6, (
        f"Max weight {weights.max():.6f} exceeds cap {max_weight}"
    )

    return pd.Series(weights, index=cov.index)


def optimize_portfolio(
    returns: pd.DataFrame,
    max_weight: float = MAX_WEIGHT,
) -> pd.Series:
    """
    End-to-end optimisation: estimate covariance, solve QP, return weight vector.

    Tickers dropped during NaN-filtering receive weight 0 in the output so the
    result can be aligned with the full universe by the caller.

    Parameters
    ----------
    returns    : shape (T, N).  The estimation window for one rebalancing date.
    max_weight : per-stock weight cap.

    Returns
    -------
    pd.Series indexed by *all* tickers in *returns* (NaN-dropped ones get 0).
    """
    cov = compute_covariance(returns)
    used_tickers = cov.columns.tolist()

    weights_used = solve_min_variance(cov, max_weight=max_weight)

    # Broadcast back to full universe: stocks dropped for NaN history get 0.
    all_tickers = returns.columns.tolist()
    weights_full = pd.Series(0.0, index=all_tickers)
    weights_full[used_tickers] = weights_used.values

    # Diagnostics
    cond = float(np.linalg.cond(cov.values))
    n_effective = int((weights_full > 1e-4).sum())
    logger.debug(
        "optimize_portfolio: window=%d×%d  used=%d  effective=%d  "
        "max_w=%.4f  sum_w=%.6f  cond=%.2e",
        *returns.shape,
        len(used_tickers),
        n_effective,
        float(weights_full.max()),
        float(weights_full.sum()),
        cond,
    )

    return weights_full


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    import pandas as pd

    from src.config import DATA_PROCESSED, ESTIMATION_WINDOW
    from src.constituents import members_on

    TEST_DATE = "2015-12-31"

    # Load full returns panel and slice trailing 60-month window.
    sr = pd.read_parquet(DATA_PROCESSED / "stock_returns.parquet")
    cutoff = pd.Timestamp(TEST_DATE) + pd.offsets.MonthEnd(0)
    window = sr.loc[sr.index <= cutoff].tail(ESTIMATION_WINDOW)

    # Restrict columns to S&P 500 members on the test date.
    members = members_on(TEST_DATE)
    members_in_panel = [t for t in members if t in sr.columns]
    window = window[members_in_panel]

    # Run optimisation.
    weights = optimize_portfolio(window, max_weight=MAX_WEIGHT)

    used       = window.dropna(axis=1).shape[1]
    n_eff      = int((weights > 1e-4).sum())
    cov        = compute_covariance(window)
    cond       = float(np.linalg.cond(cov.values))

    print(f"\n{'='*55}")
    print(f"  OPTIMISATION TEST — {TEST_DATE}")
    print(f"{'='*55}")
    print(f"  Window shape       : {window.shape[0]} months x {window.shape[1]} tickers")
    print(f"  Stocks used (no NaN): {used}")
    print(f"  Effective holdings : {n_eff}  (weight > 1e-4)")
    print(f"  Max weight         : {weights.max():.6f}")
    print(f"  Sum of weights     : {weights.sum():.8f}")
    print(f"  Cov condition no.  : {cond:.3e}")
    print(f"\n  Top 10 holdings:")
    top10 = weights[weights > 0].sort_values(ascending=False).head(10)
    for ticker, w in top10.items():
        print(f"    {ticker:<10s}  {w:.4f}  ({w*100:.2f}%)")
    print()
