# MA Thesis — Constrained Mean-Variance vs. Passive Equity

**A Risk-Adjusted Comparison of Constrained Mean-Variance and Passive Equity
Portfolio Strategies across Market Cycles**
Valerian Meipariani · ISET, Tbilisi State University · 2026

## Research question

Does a constrained minimum-variance portfolio strategy produce superior
risk-adjusted returns compared to a passive cap-weighted equity strategy
over a full market cycle, after accounting for transaction costs?

## Method

Point-in-time S&P 500 constituents, Feb 2001–Dec 2024 (287 months). At each
month-end, a long-only, fully-invested minimum-variance portfolio is solved
over a trailing 60-month window (Ledoit-Wolf covariance shrinkage, 5%
per-stock cap) and held for one month. Performance is compared against the
S&P 500 Total Return index and a 1/N equal-weight portfolio from the same
universe, net of 20bps round-trip transaction costs. Risk-adjusted
outperformance is tested with the Jobson-Korkie-Memmel Sharpe test;
regime-conditional advantage (bull/bear/recovery, drawdown-defined) with a
block bootstrap; factor exposure via CAPM, FF3, and FF5+MOM regressions
with Newey-West standard errors.

## Headline finding

The strategy cuts annualized volatility to 0.76–0.81× the benchmark and
produces consistently shallower drawdowns, but its Sharpe ratio advantage
(+0.16, full period) is not statistically significant (JKM p = 0.16), and
its CAPM alpha (+2.72%/yr) shrinks 80% to insignificance under a five-factor
model — the apparent outperformance reflects exposure to known risk premia,
not skill. Constrained minimum-variance investing functions as a
risk-control tool, not a source of alpha.

## `src/`

- `config.py` — evaluation window, optimization/data-quality parameters, paths
- `data_pull.py` — pulls prices (yfinance), benchmark, and Fama-French RF series
- `constituents.py` — point-in-time S&P 500 membership, no look-ahead
- `optimize.py` — Ledoit-Wolf covariance estimation + constrained min-variance QP
- `backtest.py` — rolling-window backtest engine (MV, 1/N, benchmark)
- `regimes.py` — bull/bear/recovery classification from drawdown
- `metrics.py` — annualized return, volatility, Sharpe, Sortino, max drawdown
- `stats.py` — JKM Sharpe test, factor regressions, bootstrap regime tests
- `diagnostics.py` — data coverage and missing-ticker diagnostics
