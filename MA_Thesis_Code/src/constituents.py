"""
Historical S&P 500 membership handling.

Responsibilities:
  - Fetch the full membership snapshot CSV from the fja05680/sp500 GitHub repo on
    first run and cache it locally; read from cache on subsequent runs.
  - Parse each snapshot row into a tidy long-format (date, ticker) table, deduplicating
    to one snapshot per calendar month-end (the latest change event within the month).
  - Normalise tickers to yfinance conventions: uppercase, strip whitespace, dot → dash
    for share-class suffixes (BF.B → BF-B).
  - Provide point-in-time universe lookups with no look-ahead.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Union

import pandas as pd
import requests

from src.config import DATA_PROCESSED, DATA_RAW

logger = logging.getLogger(__name__)

# Update this URL when the repo publishes a newer dated file.
_RAW_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes(01-17-2026).csv"
)
_CACHE_FILE = DATA_RAW / "sp500_historical_constituents.csv"

# Module-level parsed cache so repeated calls within one process are free.
_PARSED: pd.DataFrame | None = None

_RE_UNUSUAL = re.compile(r"[^A-Z0-9\-]")


# ── internal helpers ───────────────────────────────────────────────────────────

def _fetch_raw() -> None:
    """Download the constituent snapshot CSV and write to _CACHE_FILE."""
    logger.info("Fetching S&P 500 constituent data from GitHub…")
    try:
        resp = requests.get(_RAW_URL, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Network error fetching constituent data: {exc}") from exc
    if not resp.ok:
        raise RuntimeError(
            f"Failed to fetch S&P 500 constituents (HTTP {resp.status_code}): {_RAW_URL}"
        )
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(resp.text, encoding="utf-8")
    logger.info("Cached to %s", _CACHE_FILE)


def _parse(path: Path) -> pd.DataFrame:
    """
    Parse the raw snapshot CSV into a long-format (date, ticker) DataFrame.

    Each source row is a full membership snapshot on a change-event date.
    We keep the latest snapshot per calendar month (to get end-of-month membership),
    snap dates to month-end, and explode the ticker list.
    """
    raw = pd.read_csv(path, parse_dates=["date"])

    # Sort by original date so .last() picks the latest change event within each month.
    raw = raw.sort_values("date")
    raw["date"] = raw["date"] + pd.offsets.MonthEnd(0)
    raw = raw.groupby("date", as_index=False).last()

    # Explode comma-separated tickers into individual rows.
    raw["ticker"] = raw["tickers"].str.split(",")
    long = raw[["date", "ticker"]].explode("ticker")

    # Normalise: strip whitespace, uppercase, dot → dash for share classes.
    long["ticker"] = (
        long["ticker"]
        .str.strip()
        .str.upper()
        .str.replace(".", "-", regex=False)
    )
    long = long[long["ticker"] != ""].copy()

    # Log any ticker that still contains characters outside [A-Z0-9-].
    unusual_mask = long["ticker"].str.contains(_RE_UNUSUAL, regex=True)
    for t in long.loc[unusual_mask, "ticker"].unique():
        logger.warning("Unusual ticker after normalisation: %r", t)

    return long.sort_values(["date", "ticker"]).reset_index(drop=True)


# ── public API ─────────────────────────────────────────────────────────────────

def load_constituents() -> pd.DataFrame:
    """
    Return a long-format DataFrame with columns [date, ticker].

    *date* is a month-end Timestamp; *ticker* is the yfinance-normalised symbol.
    Fetches from GitHub and writes data/raw/sp500_historical_constituents.csv on
    first call; reads from that cache on subsequent calls within the same process.
    """
    global _PARSED
    if _PARSED is not None:
        return _PARSED
    if not _CACHE_FILE.exists():
        _fetch_raw()
    _PARSED = _parse(_CACHE_FILE)
    return _PARSED


def get_universe(start: str, end: str) -> list[str]:
    """
    Return the sorted list of all unique tickers that appeared in the S&P 500
    at any point between *start* and *end* (inclusive, month-end aligned).

    This is the full download universe to hand to data_pull.py — it intentionally
    includes stocks that were later removed, to avoid survivorship bias.
    """
    df = load_constituents()
    lo = pd.Timestamp(start) + pd.offsets.MonthEnd(0)
    hi = pd.Timestamp(end)   + pd.offsets.MonthEnd(0)
    mask = (df["date"] >= lo) & (df["date"] <= hi)
    return sorted(df.loc[mask, "ticker"].unique().tolist())


def members_on(date: Union[str, pd.Timestamp]) -> list[str]:
    """
    Return the sorted list of tickers that were S&P 500 members as of the most
    recent membership snapshot on or before *date*.

    Safe for point-in-time use: only snapshots with date ≤ *date* are considered.
    """
    df = load_constituents()
    cutoff = pd.Timestamp(date)
    eligible = df.loc[df["date"] <= cutoff, "date"]
    if eligible.empty:
        raise ValueError(f"No membership data on or before {date!r}")
    floor_date = eligible.max()
    return sorted(df.loc[df["date"] == floor_date, "ticker"].tolist())


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    df = load_constituents()

    n_tickers  = df["ticker"].nunique()
    n_dates    = df["date"].nunique()
    mean_count = df.groupby("date")["ticker"].count().mean()
    date_range = f"{df['date'].min().date()} to {df['date'].max().date()}"

    print(f"Unique tickers (full history) : {n_tickers}")
    print(f"Distinct membership dates     : {n_dates}")
    print(f"Mean constituents per date    : {mean_count:.1f}")
    print(f"Date range                    : {date_range}")

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    summary = (
        f"Unique tickers: {n_tickers} | "
        f"Distinct dates: {n_dates} | "
        f"Mean constituents/date: {mean_count:.1f} | "
        f"Range: {date_range}"
    )
    summary_path = DATA_PROCESSED / "constituents_summary.txt"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"\nSummary saved -> {summary_path}")
