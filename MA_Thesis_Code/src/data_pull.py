"""
Data acquisition layer.

Responsibilities:
  - Pull monthly Adj Close for the full S&P 500 ticker universe via yfinance,
    in batches of 50 with retry logic and a per-ticker pull log.
  - Pull the ^GSPC benchmark price series via yfinance.
  - Fetch the Kenneth French monthly RF series from the FF Data Library zip.
  - Orchestrate the full pipeline: prices -> returns -> alignment -> coverage report,
    saving everything to data/raw/ and data/processed/.
"""

from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from typing import Any

import pandas as pd
import requests
import yfinance as yf

from src.config import (
    BENCHMARK_TICKER,
    DATA_PROCESSED,
    DATA_RAW,
    DATA_START,
    EVAL_END,
    EVAL_START,
    MAX_PLAUSIBLE_MONTHLY_RETURN,
)
from src.constituents import get_universe, members_on

logger = logging.getLogger(__name__)

_BATCH_SIZE  = 50
_BATCH_SLEEP = 1.0   # seconds between successful batches
_RETRY_SLEEP = 5.0   # seconds before single retry on failure

_FF_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_Factors_CSV.zip"
)
_FF5_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_5_Factors_2x3_CSV.zip"
)
_MOM_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Momentum_Factor_CSV.zip"
)
# Pull two extra months beyond EVAL_END so the final month is never clipped.
# Must use .date() — str(Timestamp) includes " 00:00:00" which breaks yfinance's parser.
_YF_END = str((pd.Timestamp(EVAL_END) + pd.DateOffset(months=2)).date())


# ── internal helpers ───────────────────────────────────────────────────────────

def _to_month_end(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx + pd.offsets.MonthEnd(0)


def _yf_download_batch(batch: list[str]) -> pd.DataFrame | None:
    """Single yfinance call for a batch of tickers; returns None on any error."""
    try:
        raw = yf.download(
            tickers=batch,
            start=DATA_START,
            end=_YF_END,
            interval="1mo",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        return None if raw.empty else raw
    except Exception as exc:
        logger.warning("yfinance error: %s", exc)
        return None


def _extract_adj_close(raw: pd.DataFrame, batch: list[str]) -> pd.DataFrame:
    """
    Extract the adjusted price column from a yfinance result.
    With auto_adjust=True (yfinance 1.x), 'Close' is already the split+dividend-
    adjusted close (equivalent to 'Adj Close' in older versions).
    Guarantees a DataFrame is returned (never a Series).
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = raw.columns.get_level_values(0).unique()
        if "Close" in lvl0:
            result = raw["Close"]
        elif "Adj Close" in lvl0:
            result = raw["Adj Close"]
        else:
            logger.error("Unexpected yfinance column structure: %s", lvl0.tolist())
            return pd.DataFrame(index=raw.index)
    else:
        col = "Close" if "Close" in raw.columns else "Adj Close"
        result = raw[[col]].copy()
        result.columns = batch[:1]
        return result

    # MultiIndex slicing can produce a Series if there's only one ticker column.
    if isinstance(result, pd.Series):
        result = result.to_frame(name=batch[0] if batch else "price")

    return result.copy()


# ── public API ─────────────────────────────────────────────────────────────────

def pull_stock_prices(
    tickers: list[str], force_refresh: bool = False
) -> pd.DataFrame:
    """
    Pull monthly Adj Close for every ticker in *tickers*.

    Returns a wide DataFrame indexed by month-end date, one column per ticker.
    Tickers that yfinance cannot find get an all-NaN column so callers always
    receive the full requested shape.
    Caches to data/raw/stock_prices_monthly.parquet.
    """
    cache = DATA_RAW / "stock_prices_monthly.parquet"
    if cache.exists() and not force_refresh:
        logger.info("Loading stock prices from cache")
        return pd.read_parquet(cache)

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    batches = [tickers[i : i + _BATCH_SIZE] for i in range(0, len(tickers), _BATCH_SIZE)]
    logger.info(
        "Pulling %d tickers in %d batches of up to %d",
        len(tickers), len(batches), _BATCH_SIZE,
    )

    all_prices: list[pd.DataFrame] = []
    pull_log:   list[dict]         = []

    for i, batch in enumerate(batches):
        logger.info("Batch %d/%d  (%s ... %s)", i + 1, len(batches), batch[0], batch[-1])

        raw = _yf_download_batch(batch)
        if raw is None:
            logger.warning("Batch %d failed — retrying in %.0fs", i + 1, _RETRY_SLEEP)
            time.sleep(_RETRY_SLEEP)
            raw = _yf_download_batch(batch)

        if raw is None:
            logger.error("Batch %d still failing — skipping. Tickers: %s", i + 1, batch)
            for t in batch:
                pull_log.append(
                    {"ticker": t, "pulled": "N", "first_date": None, "last_date": None, "n_obs": 0}
                )
        else:
            prices = _extract_adj_close(raw, batch)
            prices.index = _to_month_end(pd.DatetimeIndex(prices.index))

            # yfinance silently drops unrecognised tickers — ensure full shape.
            for t in batch:
                if t not in prices.columns:
                    prices[t] = float("nan")

            all_prices.append(prices[batch])

            for t in batch:
                series = prices[t].dropna() if t in prices.columns else pd.Series(dtype=float)
                pull_log.append(
                    {
                        "ticker":     t,
                        "pulled":     "Y" if not series.empty else "N",
                        "first_date": str(series.index.min().date()) if not series.empty else None,
                        "last_date":  str(series.index.max().date()) if not series.empty else None,
                        "n_obs":      len(series),
                    }
                )

        if i < len(batches) - 1:
            time.sleep(_BATCH_SLEEP)

    if not all_prices:
        raise RuntimeError("No price data retrieved — check network and yfinance")

    combined = pd.concat(all_prices, axis=1)
    combined = combined.loc[:, ~combined.columns.duplicated()]
    combined.sort_index(inplace=True)

    combined.to_parquet(cache)
    logger.info("Saved %d x %d price matrix to %s", *combined.shape, cache)

    pd.DataFrame(pull_log).to_csv(DATA_RAW / "stock_pull_log.csv", index=False)

    return combined


def pull_benchmark(force_refresh: bool = False) -> pd.Series:
    """
    Pull monthly closing levels for the S&P 500 Total Return index (^SP500TR).

    Returns a Series indexed by month-end date.
    Caches to data/raw/benchmark_monthly.parquet.
    """
    cache = DATA_RAW / "benchmark_monthly.parquet"
    if cache.exists() and not force_refresh:
        return pd.read_parquet(cache).squeeze()

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    logger.info("Pulling benchmark (%s)", BENCHMARK_TICKER)

    raw = yf.download(
        tickers=BENCHMARK_TICKER,
        start=DATA_START,
        end=_YF_END,
        interval="1mo",
        auto_adjust=False,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError(f"No benchmark data returned for {BENCHMARK_TICKER}")

    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = raw.columns.get_level_values(0).unique()
        col = "Close" if "Close" in lvl0 else "Adj Close"
        prices = raw[col].squeeze()
    else:
        col = "Close" if "Close" in raw.columns else "Adj Close"
        prices = raw[col]

    prices.index = _to_month_end(pd.DatetimeIndex(prices.index))
    prices = prices.sort_index()
    prices.name = BENCHMARK_TICKER

    prices.to_frame().to_parquet(cache)
    logger.info(
        "Benchmark: %d observations (%s to %s)",
        len(prices), prices.index.min().date(), prices.index.max().date(),
    )
    return prices


def pull_risk_free(force_refresh: bool = False) -> pd.Series:
    """
    Pull Kenneth French monthly RF series.

    Parses the monthly section of the F-F_Research_Data_Factors CSV (downloaded
    as a zip). Returns a Series indexed by month-end date, in decimal monthly rate
    (the source gives percentages; we divide by 100).
    Caches to data/raw/risk_free_monthly.parquet.
    """
    cache = DATA_RAW / "risk_free_monthly.parquet"
    if cache.exists() and not force_refresh:
        return pd.read_parquet(cache).squeeze()

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    logger.info("Fetching Fama-French factors from French Data Library")

    try:
        resp = requests.get(_FF_URL, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Network error fetching French factors: {exc}") from exc
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code} fetching French factors: {_FF_URL}")

    z = zipfile.ZipFile(io.BytesIO(resp.content))
    content = z.read(z.namelist()[0]).decode("utf-8", errors="replace")

    # Monthly rows have a 6-digit YYYYMM date; annual rows have 4-digit YYYY — stop there.
    monthly_rows: list[list[str]] = []
    for line in content.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        if re.match(r"^\d{6}$", parts[0]):
            monthly_rows.append(parts)
        elif monthly_rows:
            break  # first non-monthly row after data has started = annual section

    if not monthly_rows:
        raise RuntimeError("Could not find monthly data in Fama-French CSV")

    df = pd.DataFrame(monthly_rows, columns=["yyyymm", "Mkt-RF", "SMB", "HML", "RF"])
    df["date"] = pd.to_datetime(df["yyyymm"], format="%Y%m") + pd.offsets.MonthEnd(0)
    df["RF"]   = pd.to_numeric(df["RF"], errors="coerce") / 100.0

    rf = df.set_index("date")["RF"].sort_index()
    rf.name = "RF"

    rf.to_frame().to_parquet(cache)
    logger.info(
        "Parsed %d monthly RF observations (%s to %s)",
        len(rf), rf.index.min().date(), rf.index.max().date(),
    )
    return rf


def pull_ff5_factors(force_refresh: bool = False) -> pd.DataFrame:
    """
    Pull Fama-French 5-factor monthly data from the French Data Library.

    Returns a DataFrame indexed by month-end date with columns:
        Mkt-RF, SMB, HML, RMW, CMA, RF  (all decimal monthly rates).
    Caches to data/raw/ff5_factors_monthly.parquet.
    """
    cache = DATA_RAW / "ff5_factors_monthly.parquet"
    if cache.exists() and not force_refresh:
        logger.info("Loading FF5 factors from cache")
        return pd.read_parquet(cache)

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    logger.info("Fetching Fama-French 5-factor data from French Data Library")

    try:
        resp = requests.get(_FF5_URL, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Network error fetching FF5 factors: {exc}") from exc
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code} fetching FF5 factors: {_FF5_URL}")

    z = zipfile.ZipFile(io.BytesIO(resp.content))
    content = z.read(z.namelist()[0]).decode("utf-8", errors="replace")

    monthly_rows: list[list[str]] = []
    for line in content.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        if re.match(r"^\d{6}$", parts[0]):
            monthly_rows.append(parts)
        elif monthly_rows:
            break

    if not monthly_rows:
        raise RuntimeError("Could not find monthly data in FF5 CSV")

    _FF5_COLS = ["yyyymm", "Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    df = pd.DataFrame(monthly_rows, columns=_FF5_COLS)
    df["date"] = pd.to_datetime(df["yyyymm"], format="%Y%m") + pd.offsets.MonthEnd(0)
    for col in ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0

    result = df.set_index("date")[["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]].sort_index()

    # Sanity check: FF5 RF must match the FF3-based RF already on disk.
    rf_cache = DATA_RAW / "risk_free_monthly.parquet"
    if rf_cache.exists():
        rf_existing = pd.read_parquet(rf_cache).squeeze()
        aligned = pd.concat([result["RF"], rf_existing], axis=1, join="inner")
        aligned.columns = ["ff5_rf", "ff3_rf"]
        max_diff = float((aligned["ff5_rf"] - aligned["ff3_rf"]).abs().max())
        if max_diff >= 1e-8:
            raise AssertionError(
                f"FF5 RF deviates from FF3 RF by {max_diff:.2e} — data mismatch!"
            )
        logger.info("RF sanity check passed (max |diff| = %.2e over %d months)", max_diff, len(aligned))

    result.to_parquet(cache)
    logger.info(
        "Saved FF5 factors: %d months (%s to %s)",
        len(result), result.index.min().date(), result.index.max().date(),
    )
    return result


def pull_momentum_factor(force_refresh: bool = False) -> pd.Series:
    """
    Pull Carhart momentum factor monthly data from the French Data Library.

    Returns a Series indexed by month-end date, in decimal monthly form.
    Caches to data/raw/mom_factor_monthly.parquet.
    """
    cache = DATA_RAW / "mom_factor_monthly.parquet"
    if cache.exists() and not force_refresh:
        logger.info("Loading momentum factor from cache")
        return pd.read_parquet(cache).squeeze()

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    logger.info("Fetching Carhart momentum factor from French Data Library")

    try:
        resp = requests.get(_MOM_URL, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Network error fetching momentum factor: {exc}") from exc
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code} fetching momentum factor: {_MOM_URL}")

    z = zipfile.ZipFile(io.BytesIO(resp.content))
    content = z.read(z.namelist()[0]).decode("utf-8", errors="replace")

    monthly_rows: list[list[str]] = []
    for line in content.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        if re.match(r"^\d{6}$", parts[0]):
            # Take only the first two non-empty fields: date + momentum value.
            non_empty = [p for p in parts if p]
            monthly_rows.append(non_empty[:2])
        elif monthly_rows:
            break

    if not monthly_rows:
        raise RuntimeError("Could not find monthly data in momentum CSV")

    df = pd.DataFrame(monthly_rows, columns=["yyyymm", "Mom"])
    df["date"] = pd.to_datetime(df["yyyymm"], format="%Y%m") + pd.offsets.MonthEnd(0)
    df["Mom"]  = pd.to_numeric(df["Mom"], errors="coerce") / 100.0

    mom = df.set_index("date")["Mom"].sort_index()
    mom.name = "MOM"

    mom.to_frame().to_parquet(cache)
    logger.info(
        "Saved momentum factor: %d months (%s to %s)",
        len(mom), mom.index.min().date(), mom.index.max().date(),
    )
    return mom


def build_factor_panel(force_refresh: bool = False) -> pd.DataFrame:
    """
    Build the unified factor panel consumed by stats.py.

    Joins FF5 factors (Mkt-RF, SMB, HML, RMW, CMA, RF) with the Carhart
    momentum factor (MOM) on the inner date intersection.  Saves to
    data/processed/factors.parquet and prints a summary to stdout.

    Returns
    -------
    pd.DataFrame with columns: Mkt-RF, SMB, HML, RMW, CMA, MOM, RF
    """
    cache = DATA_PROCESSED / "factors.parquet"
    if cache.exists() and not force_refresh:
        logger.info("Loading factor panel from cache")
        panel = pd.read_parquet(cache)
    else:
        DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

        ff5 = pull_ff5_factors(force_refresh=force_refresh)
        mom = pull_momentum_factor(force_refresh=force_refresh)

        panel = pd.concat([ff5, mom.rename("MOM")], axis=1, join="inner")
        panel = panel[["Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM", "RF"]]

        panel.to_parquet(cache)
        logger.info(
            "Factor panel saved: %d months (%s to %s), %d columns",
            len(panel), panel.index.min().date(), panel.index.max().date(), panel.shape[1],
        )

    print()
    print("=" * 62)
    print("  FACTOR PANEL SUMMARY")
    print("=" * 62)
    print(f"  Shape      : {panel.shape[0]} months x {panel.shape[1]} factors")
    print(f"  Date range : {panel.index.min().date()} to {panel.index.max().date()}")
    print()
    print(f"  {'Factor':<10}  {'Mean (%/mo)':>12}  {'Std (%/mo)':>12}")
    print("  " + "-" * 38)
    for col in panel.columns:
        print(f"  {col:<10}  {panel[col].mean() * 100:>12.4f}  {panel[col].std() * 100:>12.4f}")
    print()

    return panel


def build_returns_panel(force_refresh: bool = False) -> dict[str, Any]:
    """
    Orchestrate the full data pipeline.

    Steps: pull prices -> pct_change -> align all series on common month-end index
    -> build coverage report -> save processed files.

    Returns a dict with keys: stock_returns, benchmark_returns, risk_free, coverage.
    """
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

    stock_ret_path = DATA_PROCESSED / "stock_returns.parquet"
    bench_ret_path = DATA_PROCESSED / "benchmark_returns.parquet"
    rf_path        = DATA_PROCESSED / "risk_free.parquet"
    cov_path       = DATA_PROCESSED / "coverage_report.csv"

    all_cached = all(
        p.exists() for p in [stock_ret_path, bench_ret_path, rf_path, cov_path]
    )
    if all_cached and not force_refresh:
        logger.info("Loading all processed returns from cache")
        return {
            "stock_returns":     pd.read_parquet(stock_ret_path),
            "benchmark_returns": pd.read_parquet(bench_ret_path).squeeze(),
            "risk_free":         pd.read_parquet(rf_path).squeeze(),
            "coverage":          pd.read_csv(cov_path, index_col=0, parse_dates=True),
        }

    universe  = get_universe(DATA_START, EVAL_END)
    prices    = pull_stock_prices(universe, force_refresh=force_refresh)
    benchmark = pull_benchmark(force_refresh=force_refresh)
    rf        = pull_risk_free(force_refresh=force_refresh)

    # Simple monthly returns; drop the first row (always NaN from pct_change).
    stock_returns     = prices.pct_change().iloc[1:]
    benchmark_returns = benchmark.pct_change().iloc[1:]

    # Data-quality filter: yfinance returns inf/-inf and astronomically large
    # values for tickers whose adjusted-close series is corrupted by delisting
    # or corporate-action misadjustments (e.g. CBE, TNB).  Any monthly return
    # outside [-99.99 %, +MAX_PLAUSIBLE_MONTHLY_RETURN] is set to NaN so the
    # ticker fails the complete-window filter in select_universe.
    stock_returns = stock_returns.replace([float("inf"), float("-inf")], float("nan"))
    bad_mask      = stock_returns > MAX_PLAUSIBLE_MONTHLY_RETURN
    n_bad_cells   = int(bad_mask.sum().sum())
    bad_by_ticker = bad_mask.sum(axis=0)
    bad_tickers   = bad_by_ticker[bad_by_ticker > 0].sort_values(ascending=False)
    logger.info(
        "Return filter (>%.0f%%): %d cells across %d tickers set to NaN",
        MAX_PLAUSIBLE_MONTHLY_RETURN * 100,
        n_bad_cells,
        len(bad_tickers),
    )
    if len(bad_tickers):
        top_str = ", ".join(
            f"{t}({n})" for t, n in bad_tickers.head(20).items()
        )
        logger.info("Most-affected tickers (bad-month count): %s", top_str)
    stock_returns = stock_returns.where(~bad_mask, other=float("nan"))

    # Align everything on the intersection of available dates.
    common_idx = (
        stock_returns.index
        .intersection(benchmark_returns.index)
        .intersection(rf.index)
    )
    stock_returns     = stock_returns.loc[common_idx]
    benchmark_returns = benchmark_returns.loc[common_idx]
    rf                = rf.loc[common_idx]

    # Coverage report: only over the evaluation window.
    eval_dates = common_idx[
        (common_idx >= pd.Timestamp(EVAL_START)) &
        (common_idx <= pd.Timestamp(EVAL_END))
    ]

    cov_rows: list[dict] = []
    for date in eval_dates:
        mems   = members_on(date)
        n_mem  = len(mems)
        in_uni = [t for t in mems if t in stock_returns.columns]
        n_data = int(stock_returns.loc[date, in_uni].notna().sum())
        cov_rows.append(
            {
                "date":           date,
                "n_members":      n_mem,
                "n_in_universe":  len(in_uni),
                "n_with_returns": n_data,
                "coverage_ratio": n_data / n_mem if n_mem else 0.0,
            }
        )
    coverage = pd.DataFrame(cov_rows).set_index("date")

    stock_returns.to_parquet(stock_ret_path)
    benchmark_returns.to_frame(name=BENCHMARK_TICKER).to_parquet(bench_ret_path)
    rf.to_frame(name="RF").to_parquet(rf_path)
    coverage.to_csv(cov_path)
    logger.info("Processed returns saved to %s", DATA_PROCESSED)

    return {
        "stock_returns":     stock_returns,
        "benchmark_returns": benchmark_returns,
        "risk_free":         rf,
        "coverage":          coverage,
    }


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    build_factor_panel(force_refresh=False)

    panel = build_returns_panel(force_refresh=False)

    sr  = panel["stock_returns"]
    cov = panel["coverage"]

    date_range      = f"{sr.index.min().date()} to {sr.index.max().date()}"
    n_zero_tickers  = int((sr.notna().sum() == 0).sum())
    eval_cov        = cov["coverage_ratio"]

    print(f"\n{'='*57}")
    print("  DATA PANEL SUMMARY")
    print(f"{'='*57}")
    print(f"  Stock returns matrix  : {sr.shape[0]} months x {sr.shape[1]} tickers")
    print(f"  Date range            : {date_range}")
    print(f"  Tickers w/ 0 obs      : {n_zero_tickers}")
    print()
    print(f"  Coverage over eval window ({EVAL_START} to {EVAL_END}):")
    print(f"    Mean   : {eval_cov.mean():.1%}")
    print(f"    Min    : {eval_cov.min():.1%}  ({eval_cov.idxmin().date()})")
    print(f"    Max    : {eval_cov.max():.1%}  ({eval_cov.idxmax().date()})")
    print()

    cols = ["n_members", "n_with_returns", "coverage_ratio"]

    print("  10 WORST-COVERED MONTHS")
    print(cov.nsmallest(10, "coverage_ratio")[cols].to_string())
    print()

    print("  10 BEST-COVERED MONTHS")
    print(cov.nlargest(10, "coverage_ratio")[cols].to_string())
    print()
