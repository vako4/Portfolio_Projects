"""
Central configuration for the MV vs. passive equity comparison pipeline.
All date strings follow ISO 8601 (YYYY-MM-DD).
"""

# ── Evaluation window ──────────────────────────────────────────────────────────
EVAL_START = "2001-01-01"   # first month a full 60-month window is available
EVAL_END   = "2024-12-31"

# Extra history needed to populate the first estimation window
DATA_START = "1996-01-01"

# ── Optimisation parameters ────────────────────────────────────────────────────
ESTIMATION_WINDOW    = 60    # months of history per rolling window
MAX_WEIGHT           = 0.05  # 5 % cap per constituent

# ── Data-quality thresholds ────────────────────────────────────────────────────
# Any monthly simple return above this is treated as a yfinance data artifact
# (corrupted adjusted-close series for delisted/acquired tickers) and set to NaN.
MAX_PLAUSIBLE_MONTHLY_RETURN = 1.0   # +100 % per month

# ── Market-regime definition ───────────────────────────────────────────────────
BEAR_THRESHOLD       = -0.20  # peak-to-trough drawdown that defines a bear market

# ── Transaction costs ─────────────────────────────────────────────────────────
TRANSACTION_COST_BPS = 20     # basis points, per round-trip trade

# ── Benchmark ticker ──────────────────────────────────────────────────────────
# ^SP500TR is the S&P 500 Total Return index; ^GSPC is price-only and would
# understate the benchmark by ~2pp/year in dividend reinvestment, biasing
# comparisons against any dividend-inclusive active strategy.
BENCHMARK_TICKER = "^SP500TR"
BENCHMARK_ETF    = "SPY"      # total-return proxy for passive strategy

# ── Paths ─────────────────────────────────────────────────────────────────────
from pathlib import Path

ROOT_DIR      = Path(__file__).resolve().parents[2]
DATA_RAW      = ROOT_DIR / "data" / "raw"
DATA_PROCESSED = ROOT_DIR / "data" / "processed"
RESULTS_FIGURES = ROOT_DIR / "outputs" / "figures"
RESULTS_TABLES  = ROOT_DIR / "outputs" / "tables"
