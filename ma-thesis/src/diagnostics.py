"""
Diagnostic artifacts for thesis Chapter 3 (Data & Methodology).

Responsibilities:
  - plot_coverage_over_time : line chart of monthly data coverage, saved to
    results/figures/coverage_over_time.png and a companion CSV for the table appendix.
  - analyze_missing_tickers : breakdown of the 411 zero-observation tickers by
    membership period, saved as CSV + histogram of exit years.
  - __main__ : runs both functions and prints a human-readable paragraph summary.
"""

from __future__ import annotations

import logging

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from src.config import (
    DATA_PROCESSED,
    EVAL_END,
    EVAL_START,
    RESULTS_FIGURES,
    RESULTS_TABLES,
)
from src.constituents import load_constituents

logger = logging.getLogger(__name__)

# ── shared style constants ─────────────────────────────────────────────────────
_DARK_BLUE   = "#1a3a5c"
_SHADE_BLUE  = "#d6e4f0"
_REFLINE_CLR = "#aaaaaa"
_FIG_DPI     = 300
_FONT_FAMILY = "DejaVu Sans"   # ships with matplotlib, no install needed

plt.rcParams.update(
    {
        "font.family":       _FONT_FAMILY,
        "axes.spines.top":   False,
        "axes.spines.right": False,
        "axes.grid":         True,
        "grid.color":        "#e0e0e0",
        "grid.linewidth":    0.6,
        "axes.axisbelow":    True,
    }
)


def _apply_yonly_grid(ax: plt.Axes) -> None:
    """Show only horizontal gridlines (y-axis) — no vertical clutter."""
    ax.xaxis.grid(False)
    ax.yaxis.grid(True)


# ── helpers ────────────────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    RESULTS_FIGURES.mkdir(parents=True, exist_ok=True)
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)


def _load_coverage() -> pd.DataFrame:
    path = DATA_PROCESSED / "coverage_report.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Coverage report not found at {path}. Run src/data_pull.py first."
        )
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = df.index + pd.offsets.MonthEnd(0)   # ensure month-end alignment
    return df


def _load_zero_obs_tickers() -> list[str]:
    path = DATA_PROCESSED / "stock_returns.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Stock returns not found at {path}. Run src/data_pull.py first."
        )
    sr = pd.read_parquet(path)
    return sorted(sr.columns[(sr.notna().sum() == 0)].tolist())


# ── public API ─────────────────────────────────────────────────────────────────

def plot_coverage_over_time() -> None:
    """
    Line chart of monthly S&P 500 price-data coverage over the full eval window.

    Saves:
      results/figures/coverage_over_time.png
      results/tables/coverage_eval_period.csv
    """
    _ensure_dirs()
    cov = _load_coverage()

    eval_start = pd.Timestamp(EVAL_START) + pd.offsets.MonthEnd(0)
    eval_end   = pd.Timestamp(EVAL_END)   + pd.offsets.MonthEnd(0)

    eval_cov = cov.loc[
        (cov.index >= eval_start) & (cov.index <= eval_end),
        "coverage_ratio",
    ]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    _apply_yonly_grid(ax)

    # Eval-period shade
    ax.axvspan(eval_start, eval_end, color=_SHADE_BLUE, alpha=0.35, zorder=0, label="Evaluation period")

    # Reference lines
    for level, label in [(0.90, "90 %"), (0.75, "75 %"), (0.50, "50 %")]:
        ax.axhline(level, color=_REFLINE_CLR, linewidth=0.9, linestyle="--", zorder=1)
        ax.text(
            eval_end + pd.DateOffset(months=1),
            level,
            label,
            va="center",
            fontsize=8,
            color=_REFLINE_CLR,
        )

    # Main coverage line
    ax.plot(eval_cov.index, eval_cov.values, color=_DARK_BLUE, linewidth=1.6, zorder=2)

    ax.set_xlim(eval_cov.index.min() - pd.DateOffset(months=2),
                eval_cov.index.max() + pd.DateOffset(months=8))
    ax.set_ylim(0.40, 1.02)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0, decimals=0))
    ax.set_xlabel("Date", fontsize=10)
    ax.set_ylabel("Coverage ratio\n(tickers with returns / index members)", fontsize=10)
    ax.set_title(
        "S&P 500 Constituent Price Data Coverage, yfinance, 2001–2024",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.legend(loc="lower right", fontsize=9, framealpha=0.7)

    fig.tight_layout()
    out_path = RESULTS_FIGURES / "coverage_over_time.png"
    fig.savefig(out_path, dpi=_FIG_DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", out_path)

    # Save eval-period table
    csv_path = RESULTS_TABLES / "coverage_eval_period.csv"
    eval_cov.to_frame().to_csv(csv_path)
    logger.info("Saved %s", csv_path)


def analyze_missing_tickers() -> pd.DataFrame:
    """
    For each zero-observation ticker, find its S&P 500 membership span and
    produce a histogram of exit years.

    Saves:
      results/tables/missing_tickers_breakdown.csv
      results/figures/missing_tickers_by_exit_year.png

    Returns the breakdown DataFrame.
    """
    _ensure_dirs()
    missing = _load_zero_obs_tickers()
    members_df = load_constituents()

    rows: list[dict] = []
    for ticker in missing:
        ticker_rows = members_df.loc[members_df["ticker"] == ticker, "date"]
        if ticker_rows.empty:
            # Not in membership data at all — shouldn't happen but handle gracefully
            rows.append(
                {
                    "ticker":            ticker,
                    "first_member_date": pd.NaT,
                    "last_member_date":  pd.NaT,
                    "months_as_member":  0,
                }
            )
        else:
            rows.append(
                {
                    "ticker":            ticker,
                    "first_member_date": ticker_rows.min(),
                    "last_member_date":  ticker_rows.max(),
                    "months_as_member":  len(ticker_rows),
                }
            )

    breakdown = pd.DataFrame(rows)

    # ── CSV ───────────────────────────────────────────────────────────────────
    csv_path = RESULTS_TABLES / "missing_tickers_breakdown.csv"
    breakdown.to_csv(csv_path, index=False)
    logger.info("Saved %s", csv_path)

    # ── Histogram: missing tickers by year of last S&P 500 membership ─────────
    valid = breakdown.dropna(subset=["last_member_date"])
    exit_years = valid["last_member_date"].dt.year.astype(int)

    year_min, year_max = exit_years.min(), exit_years.max()
    bins = np.arange(year_min, year_max + 2)   # one bin per year

    fig, ax = plt.subplots(figsize=(10, 4))
    _apply_yonly_grid(ax)

    eval_start_yr = pd.Timestamp(EVAL_START).year
    eval_end_yr   = pd.Timestamp(EVAL_END).year

    # Shade the eval period
    ax.axvspan(eval_start_yr, eval_end_yr + 1, color=_SHADE_BLUE, alpha=0.40,
               zorder=0, label=f"Evaluation period ({eval_start_yr}–{eval_end_yr})")

    ax.hist(
        exit_years,
        bins=bins,
        color=_DARK_BLUE,
        edgecolor="white",
        linewidth=0.5,
        zorder=2,
        label="Missing tickers",
        align="left",
    )

    ax.set_xlabel("Year of last S&P 500 membership", fontsize=10)
    ax.set_ylabel("Number of missing tickers", fontsize=10)
    ax.set_title(
        "Missing Tickers (Zero yfinance Observations) by Last Membership Year",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.xaxis.set_major_locator(mticker.MultipleLocator(2))
    ax.xaxis.set_minor_locator(mticker.MultipleLocator(1))
    ax.set_xlim(year_min - 0.5, year_max + 1.5)
    ax.legend(fontsize=9, framealpha=0.7)

    fig.tight_layout()
    hist_path = RESULTS_FIGURES / "missing_tickers_by_exit_year.png"
    fig.savefig(hist_path, dpi=_FIG_DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", hist_path)

    return breakdown


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    print("Running coverage plot...")
    plot_coverage_over_time()

    print("Analysing missing tickers...")
    breakdown = analyze_missing_tickers()

    # ── summary stats ──────────────────────────────────────────────────────────
    cov = _load_coverage()
    eval_start = pd.Timestamp(EVAL_START) + pd.offsets.MonthEnd(0)
    eval_end   = pd.Timestamp(EVAL_END)   + pd.offsets.MonthEnd(0)
    eval_cov   = cov.loc[(cov.index >= eval_start) & (cov.index <= eval_end), "coverage_ratio"]

    mean_cov  = eval_cov.mean()
    worst_yr  = eval_cov.groupby(eval_cov.index.year).mean().idxmin()
    best_yr   = eval_cov.groupby(eval_cov.index.year).mean().idxmax()
    worst_avg = eval_cov.groupby(eval_cov.index.year).mean().min()
    best_avg  = eval_cov.groupby(eval_cov.index.year).mean().max()

    # Missing-ticker exit distribution
    valid = breakdown.dropna(subset=["last_member_date"])
    exits = valid["last_member_date"].dt.year

    pre2001     = int((exits < 2001).sum())
    in_2001_10  = int(((exits >= 2001) & (exits <= 2010)).sum())
    in_2010_20  = int(((exits > 2010) & (exits <= 2020)).sum())
    post2020    = int((exits > 2020).sum())
    not_in_data = int(breakdown["last_member_date"].isna().sum())

    print()
    print("=" * 70)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 70)
    print(
        f"\nMean coverage across the 2001-2024 evaluation window is {mean_cov:.1%}, "
        f"with the worst annual average in {worst_yr} ({worst_avg:.1%}) and the best "
        f"in {best_yr} ({best_avg:.1%}). Coverage starts low in the early 2000s because "
        f"many pre-2001 S&P 500 constituents (acquired companies, pre-dot-com names) "
        f"have no Yahoo Finance price history, then rises steadily as the surviving "
        f"ticker universe stabilises."
        f"\n\nOf the {len(breakdown)} tickers with zero yfinance observations, "
        f"{pre2001} exited the S&P 500 before 2001 (outside the evaluation window entirely), "
        f"{in_2001_10} exited during 2001-2010, "
        f"{in_2010_20} during 2011-2020, "
        f"and {post2020} after 2020. "
        f"{not_in_data} tickers appeared in the constituent file but not in the "
        f"membership table. "
        f"The heavy concentration of missing tickers in the pre-2001 and early-2000s "
        f"cohort is consistent with survivorship-free data construction: we pulled the "
        f"full historical universe, but Yahoo Finance simply does not carry price "
        f"histories for many companies that were acquired or delisted before 2005."
    )
    print()
