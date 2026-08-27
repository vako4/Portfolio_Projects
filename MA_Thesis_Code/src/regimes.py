"""
Regime classification for the MV vs. passive equity comparison.

Three regimes, classified on the S&P 500 Total Return index (monthly):

  bear       -- the period from the month after an all-time-high peak
               (confirmed by a >=20% drawdown from that peak) through
               the trough month (lowest close before full recovery).
  recovery   -- the month after the trough through the first month the
               index re-attains the prior peak level.
  bull       -- all other months, including the peak month itself.

Detection runs over the full available price series (from the first return
in benchmark_returns.parquet, 1996-02 onward) so that the regime context at
the start of the evaluation window (2001-02) is established correctly.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from src.config import (
    BEAR_THRESHOLD,
    DATA_PROCESSED,
    EVAL_END,
    EVAL_START,
    RESULTS_FIGURES,
    RESULTS_TABLES,
)

logger = logging.getLogger(__name__)

# BEAR_THRESHOLD is stored as a negative fraction in config; work with its magnitude.
_THRESHOLD_DEFAULT: float = abs(BEAR_THRESHOLD)

_REGIME_COLORS: dict[str, str] = {
    "bull":     "#d6ead7",  # muted green
    "bear":     "#f5d0d0",  # muted red
    "recovery": "#cde8f0",  # muted blue
}


# ── public API ─────────────────────────────────────────────────────────────────

def identify_peaks_and_troughs(
    prices: pd.Series,
    drawdown_threshold: float = _THRESHOLD_DEFAULT,
) -> pd.DataFrame:
    """
    Walk through *prices* chronologically and identify bear-market cycles.

    A cycle is confirmed once the drawdown from the running all-time high
    exceeds *drawdown_threshold* (accepts both 0.20 and -0.20).  The trough
    is the lowest close reached between the confirmed peak and the subsequent
    recovery to that peak level.  If the series ends before the recovery,
    recovery_date is NaT and a warning is logged.

    Parameters
    ----------
    prices : pd.Series
        Monthly price levels, indexed by month-end Timestamps.
    drawdown_threshold : float
        Magnitude of the peak-to-trough drawdown that confirms a bear market
        (default 0.20 = 20 %).  Both positive and negative values accepted.

    Returns
    -------
    pd.DataFrame with columns:
        peak_date, trough_date, recovery_date   (Timestamp / NaT)
        peak_value, trough_value                (float)
        drawdown                                (negative fraction)
    """
    threshold = abs(drawdown_threshold)
    prices = prices.sort_index().dropna()
    dates = prices.index
    vals = prices.values.astype(float)

    records: list[dict] = []

    # State machine: 'bull' tracks running ATH; 'bear' tracks trough and awaits recovery.
    state: str = "bull"
    running_peak_val: float = vals[0]
    running_peak_date: pd.Timestamp = dates[0]

    # Bear-phase accumulators (initialised on transition into 'bear').
    confirmed_peak_val: float = float("nan")
    confirmed_peak_date: pd.Timestamp = dates[0]
    trough_val: float = float("nan")
    trough_date: pd.Timestamp = dates[0]

    for date, price in zip(dates, vals):
        if state == "bull":
            if price > running_peak_val:
                running_peak_val = price
                running_peak_date = date
            dd = (price - running_peak_val) / running_peak_val
            if dd <= -threshold:
                state = "bear"
                confirmed_peak_val = running_peak_val
                confirmed_peak_date = running_peak_date
                trough_val = price
                trough_date = date

        else:  # state == "bear"
            if price < trough_val:
                trough_val = price
                trough_date = date
            if price >= confirmed_peak_val:
                records.append({
                    "peak_date":     confirmed_peak_date,
                    "trough_date":   trough_date,
                    "recovery_date": date,
                    "peak_value":    confirmed_peak_val,
                    "trough_value":  trough_val,
                    "drawdown":      (trough_val - confirmed_peak_val) / confirmed_peak_val,
                })
                # New bull phase starts from the recovery price.
                state = "bull"
                running_peak_val = price
                running_peak_date = date

    # Handle a cycle that spans the end of the series.
    if state == "bear":
        logger.warning(
            "Series ends mid-cycle: peak %s (%.4f), trough so far %s (%.4f), "
            "not yet recovered by %s",
            confirmed_peak_date.date(), confirmed_peak_val,
            trough_date.date(), trough_val,
            dates[-1].date(),
        )
        records.append({
            "peak_date":     confirmed_peak_date,
            "trough_date":   trough_date,
            "recovery_date": pd.NaT,
            "peak_value":    confirmed_peak_val,
            "trough_value":  trough_val,
            "drawdown":      (trough_val - confirmed_peak_val) / confirmed_peak_val,
        })

    df = pd.DataFrame(records)
    if not df.empty:
        for col in ("peak_date", "trough_date", "recovery_date"):
            df[col] = pd.to_datetime(df[col])
    return df


def classify_regimes(
    prices: pd.Series,
    drawdown_threshold: float = _THRESHOLD_DEFAULT,
) -> pd.Series:
    """
    Classify every month in *prices* as 'bull', 'bear', or 'recovery'.

    Labelling rules (month-end index):
      peak month                          -> bull  (peak month ends the bull run)
      (peak_date, trough_date]            -> bear
      (trough_date, recovery_date]        -> recovery
      all other months                    -> bull

    If the series ends mid-cycle, months after the known trough are labeled
    'recovery' and a warning is logged.

    Parameters
    ----------
    prices : pd.Series
        Monthly price levels, indexed by month-end Timestamps.

    Returns
    -------
    pd.Series[str] with the same index as *prices*.
    """
    prices = prices.sort_index().dropna()
    cycles = identify_peaks_and_troughs(prices, drawdown_threshold)

    regimes = pd.Series("bull", index=prices.index, dtype=object)

    for _, row in cycles.iterrows():
        peak_date     = row["peak_date"]
        trough_date   = row["trough_date"]
        recovery_date = row["recovery_date"]

        bear_mask = (prices.index > peak_date) & (prices.index <= trough_date)
        regimes[bear_mask] = "bear"

        if pd.isna(recovery_date):
            rec_mask = prices.index > trough_date
            logger.warning(
                "Incomplete cycle (peak %s): months after trough %s labeled 'recovery'",
                peak_date.date(), trough_date.date(),
            )
        else:
            rec_mask = (prices.index > trough_date) & (prices.index <= recovery_date)
        regimes[rec_mask] = "recovery"

    return regimes


def summarize_regimes(regimes: pd.Series) -> pd.DataFrame:
    """
    Compress a month-level regime Series into one row per contiguous episode.

    Returns a pd.DataFrame with columns:
        regime, start_date, end_date, n_months
    """
    if regimes.empty:
        return pd.DataFrame(columns=["regime", "start_date", "end_date", "n_months"])

    regimes = regimes.sort_index()
    # Group ID increments every time the regime label changes.
    group_id = (regimes != regimes.shift()).cumsum()

    episodes: list[dict] = []
    for _, group in regimes.groupby(group_id, sort=False):
        episodes.append({
            "regime":     group.iloc[0],
            "start_date": group.index[0],
            "end_date":   group.index[-1],
            "n_months":   len(group),
        })
    return pd.DataFrame(episodes)


# ── helpers ────────────────────────────────────────────────────────────────────

def _plot_timeline(
    eval_prices: pd.Series,
    eval_episodes: pd.DataFrame,
    threshold_pct: int,
    out_path: Path,
) -> None:
    """Save a regime-shaded cumulative return figure."""
    threshold_str = f">= −{threshold_pct}%"

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for _, ep in eval_episodes.iterrows():
        ax.axvspan(
            ep["start_date"], ep["end_date"],
            color=_REGIME_COLORS[ep["regime"]], alpha=1.0, zorder=0,
        )

    ax.yaxis.grid(True, color="#c8c8c8", linewidth=0.6, zorder=1)
    ax.xaxis.grid(False)
    ax.set_axisbelow(False)

    ax.plot(
        eval_prices.index, eval_prices.values,
        color="#1a3a5c", linewidth=1.8, zorder=2, label="S&P 500 TR (cumulative)",
    )

    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.1f}x"))
    ax.yaxis.set_minor_formatter(mticker.NullFormatter())
    ax.set_xlim(eval_prices.index[0], eval_prices.index[-1])
    ax.set_xlabel("Date", fontsize=10)
    ax.set_ylabel("Growth of $1  (log scale)", fontsize=10)
    ax.set_title(
        f"S&P 500 Total Return — Market Regime Classification, 2001–2024\n"
        f"(green = bull  |  red = bear [peak-to-trough {threshold_str}]  |  blue = recovery)",
        fontsize=11, fontweight="bold", pad=10,
    )

    legend_handles = [
        mpatches.Patch(color=_REGIME_COLORS["bull"],     label="Bull"),
        mpatches.Patch(color=_REGIME_COLORS["bear"],     label=f"Bear  ({threshold_str})"),
        mpatches.Patch(color=_REGIME_COLORS["recovery"], label="Recovery"),
        ax.lines[0],
    ]
    ax.legend(handles=legend_handles, fontsize=9, loc="upper left", framealpha=0.85)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", out_path)


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    # ── Load benchmark returns and build price-level series ────────────────────
    bm_ret = pd.read_parquet(DATA_PROCESSED / "benchmark_returns.parquet").squeeze()
    bm_ret.index = pd.to_datetime(bm_ret.index)
    bm_ret = bm_ret.sort_index()

    # (1 + r).cumprod() gives a scale-invariant cumulative level starting at
    # 1+r_0, which is sufficient for drawdown detection.
    prices = (1 + bm_ret).cumprod()
    prices.name = "SP500TR_level"

    logger.info(
        "Price series: %d months (%s to %s)",
        len(prices), prices.index[0].date(), prices.index[-1].date(),
    )

    eval_lo = pd.Timestamp("2001-02-28")
    eval_hi = pd.Timestamp(EVAL_END) + pd.offsets.MonthEnd(0)
    eval_prices = prices[(prices.index >= eval_lo) & (prices.index <= eval_hi)]

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)
    RESULTS_FIGURES.mkdir(parents=True, exist_ok=True)

    # ── Run both threshold versions ────────────────────────────────────────────
    _CONFIGS = [
        ("main",        0.20, "regimes_main.parquet",        "regime_episodes_main.csv",        "regimes_timeline_main.png"),
        ("sensitivity", 0.15, "regimes_sensitivity.parquet", "regime_episodes_sensitivity.csv", "regimes_timeline_sensitivity.png"),
    ]

    _results: dict[str, dict] = {}
    for _name, _thr, _parquet, _ep_csv, _fig_png in _CONFIGS:
        _cycles_all = identify_peaks_and_troughs(prices, _thr)
        _all_reg    = classify_regimes(prices, _thr)
        _reg_eval   = _all_reg[(_all_reg.index >= eval_lo) & (_all_reg.index <= eval_hi)]
        _episodes   = summarize_regimes(_reg_eval)

        _reg_eval.to_frame(name="regime").to_parquet(DATA_PROCESSED / _parquet)
        _episodes.to_csv(RESULTS_TABLES / _ep_csv, index=False)
        _plot_timeline(eval_prices, _episodes, int(_thr * 100), RESULTS_FIGURES / _fig_png)

        _results[_name] = {"cycles": _cycles_all, "regimes": _reg_eval, "episodes": _episodes}

        print()
        print("=" * 72)
        print(f"  BEAR-MARKET CYCLES  (S&P 500 TR, >= {int(_thr * 100)}% drawdown threshold)")
        print("=" * 72)
        print(
            f"  {'Peak':9}  {'Trough':9}  {'Recovery':10}  "
            f"{'Drawdown':>10}  {'Peak val':>10}  {'Trough val':>10}"
        )
        print("  " + "-" * 66)
        for _, row in _cycles_all.iterrows():
            rec = row["recovery_date"]
            rec_str = rec.strftime("%Y-%m") if not pd.isna(rec) else "ongoing  "
            print(
                f"  {row['peak_date'].strftime('%Y-%m'):<9}  "
                f"{row['trough_date'].strftime('%Y-%m'):<9}  "
                f"{rec_str:<10}  "
                f"{row['drawdown']:>+9.1%}  "
                f"{row['peak_value']:>10.4f}  {row['trough_value']:>10.4f}"
            )

    # ── 1. Comparison table: month counts ─────────────────────────────────────
    reg_main = _results["main"]["regimes"]
    reg_sens = _results["sensitivity"]["regimes"]
    c_main   = reg_main.value_counts()
    c_sens   = reg_sens.value_counts()
    _LABELS  = ["bull", "bear", "recovery"]

    print()
    print("=" * 56)
    print("  REGIME MONTH COUNTS  MAIN vs. SENSITIVITY")
    print("=" * 56)
    print(f"  {'Regime':<12}  {'Main (-20%)':>12}  {'Sens (-15%)':>12}  {'Delta':>6}")
    print("  " + "-" * 50)
    for lbl in _LABELS:
        nm = int(c_main.get(lbl, 0))
        ns = int(c_sens.get(lbl, 0))
        print(f"  {lbl:<12}  {nm:>12}  {ns:>12}  {ns - nm:>+6}")
    print("  " + "-" * 50)
    print(f"  {'Total':<12}  {len(reg_main):>12}  {len(reg_sens):>12}  {len(reg_sens) - len(reg_main):>+6}")

    # ── 2. COVID detection confirmation ───────────────────────────────────────
    cycles_sens = _results["sensitivity"]["cycles"]
    covid_rows  = cycles_sens[
        (cycles_sens["peak_date"] >= "2019-12-01") &
        (cycles_sens["peak_date"] <= "2020-03-31")
    ]
    print()
    print("=" * 56)
    print("  COVID-19 EPISODE DETECTION  (sensitivity, -15% threshold)")
    print("=" * 56)
    if covid_rows.empty:
        print("  !! NOT DETECTED — check threshold or data coverage")
    else:
        for _, row in covid_rows.iterrows():
            rec = row["recovery_date"]
            rec_str = rec.strftime("%Y-%m") if not pd.isna(rec) else "ongoing"
            print(f"  Peak:      {row['peak_date'].strftime('%Y-%m')}")
            print(f"  Trough:    {row['trough_date'].strftime('%Y-%m')}")
            print(f"  Recovery:  {rec_str}")
            print(f"  Drawdown:  {row['drawdown']:+.1%}")

    # ── 3. Post-2015 breakdown ─────────────────────────────────────────────────
    post2015_lo  = pd.Timestamp("2015-01-01")
    reg_main_p15 = reg_main[reg_main.index >= post2015_lo]
    reg_sens_p15 = reg_sens[reg_sens.index >= post2015_lo]
    c_m15 = reg_main_p15.value_counts()
    c_s15 = reg_sens_p15.value_counts()

    print()
    print("=" * 56)
    print("  POST-2015 REGIME COUNTS  (2015-01 onward)")
    print("=" * 56)
    print(f"  {'Regime':<12}  {'Main (-20%)':>12}  {'Sens (-15%)':>12}")
    print("  " + "-" * 42)
    for lbl in _LABELS:
        nm = int(c_m15.get(lbl, 0))
        ns = int(c_s15.get(lbl, 0))
        print(f"  {lbl:<12}  {nm:>12}  {ns:>12}")
    print("  " + "-" * 42)
    print(f"  {'Total':<12}  {len(reg_main_p15):>12}  {len(reg_sens_p15):>12}")
    print()
