# PORTS Pipeline

Refactored version of `PORTS.ipynb` using the parallel papermill architecture
validated by the earlier `papermill_pilot/` synthetic test.

> **Portfolio sample.** The original pipeline runs 7 product notebooks; only
> `products/loans.ipynb` is included here to illustrate the pattern. Real Oracle
> schema and table names in its SQL have been replaced with generic placeholders
> (e.g. `FINREP_SCHEMA.LOAN_FACT`) — query structure and column names are
> otherwise unchanged. `ports_main.py`'s `PRODUCTS` list still references all 7
> for context, so it won't run end-to-end without the other 6 notebooks.

## Structure

```
ports_pipeline/
├── ports_utils.py             ← shared helpers: connection pool, dates, PB HR codes
├── products/
│   ├── deposits.ipynb         ← PORT_DEPOS
│   ├── loans.ipynb            ← PORT_LOANS  (included as a sample)
│   ├── soc_loans.ipynb        ← PORT_SOC_LOANS
│   ├── soc_ovd.ipynb          ← PORT_SOC_OVD_LOANS
│   ├── collateral.ipynb       ← PORT_COLLOTERAL_LOANS
│   ├── mortgage.ipynb         ← PORT_MORTGAGE_LOANS
│   └── savings.ipynb          ← Saiving_Meti_portfolio
├── ports_main.py              ← orchestrator: parallel run → concat → pivot → export
├── _tmp/                      ← parquet outputs (created at runtime)
└── _executed/                 ← executed papermill notebooks (created at runtime)
```

## Setup (work laptop)

```
py -m pip install jupyter pandas papermill pyarrow openpyxl cx_Oracle python-dotenv
```

Create a `.env` file in this folder:

```
DB_USER=your_user
DB_PASSWORD=your_password
DB_DSN=your_dsn
```

## Running

```
py ports_main.py                    # uses yesterday (rolled back from Monday → Friday)
py ports_main.py 2026-05-15         # specific end_date
```

Output: `PORT.xlsx` in the project folder.

## What changed vs. the original PORTS.ipynb

| Before | After |
|--------|-------|
| 7 product cells run sequentially | Each in its own notebook, run in parallel (up to 5 concurrent) |
| 5 redundant `cx_Oracle.connect(...)` cells | One central `cx_Oracle.SessionPool` in `ports_utils.py` |
| `pb_df` rebuilt as a string in setup | `PB_DF_SQL` defined once in `ports_utils.py` |
| Run inside Jupyter (`Run All` had threading/kernel hangs) | Runs as a script for clean subprocess teardown |
| Pivot logic in final notebook cell | Pivot logic preserved verbatim in `ports_main.py` |
| Date math inline in Cell 2 | Centralized in `compute_dates()` (Monday → Friday rollback fixed) |

## Validation before production use

1. Run the original `PORTS.ipynb` for a known `end_date`. Keep `PORT.xlsx` as `PORT_original.xlsx`.
2. Run `py ports_main.py 2026-XX-YY` (same date). Save its `PORT.xlsx` as `PORT_new.xlsx`.
3. Compare in Python:
   ```python
   import pandas as pd
   old = pd.read_excel('PORT_original.xlsx').sort_values('POS_ID').reset_index(drop=True)
   new = pd.read_excel('PORT_new.xlsx').sort_values('POS_ID').reset_index(drop=True)
   pd.testing.assert_frame_equal(old, new, check_dtype=False)
   print("✅ Outputs match")
   ```
4. If they match → safe to swap in production.

## Notes

- The `compute_dates()` Monday-rollback in the original PORTS only subtracted **1 day**
  on Mondays (would land on Sunday). This refactor subtracts **2 days** (lands on Friday).
  If your team expects Sunday's date on Mondays, change `timedelta(days=2)` back to
  `timedelta(days=1)` in `ports_utils.py`.
- Before running with `max_workers=5`, confirm with your DBAs that 5 concurrent
  connections from your user are OK.
- The SQL queries inside each product notebook are **byte-for-byte identical**
  to the originals — only the surrounding plumbing changed. (In this public
  sample, `loans.ipynb` is the exception: schema/table names were genericized,
  see note at the top of this README.)
