# PORTS Pipeline

A parallel multi-product notebook orchestration pattern: run several
independent, parameterized notebooks concurrently, concatenate their
outputs, and produce one consolidated report. Built with papermill, a
bounded thread pool, and Parquet as the intermediate format.

Seven synthetic products are referenced below to show how the pattern
scales; `products/loans.ipynb` is included as a runnable sample.

## Structure

```
ports-pipeline/
├── ports_utils.py          ← connection pool, date helpers, exclusion list
├── products/
│   ├── product_a.ipynb
│   ├── loans.ipynb         ← included as a runnable sample
│   ├── product_c.ipynb
│   ├── product_d.ipynb
│   ├── product_e.ipynb
│   ├── product_f.ipynb
│   └── product_g.ipynb
├── ports_main.py            ← orchestrator: parallel run → concat → pivot → export
├── _tmp/                    ← Parquet outputs (created at runtime)
└── _executed/                ← executed papermill notebooks (created at runtime)
```

## Architecture

**papermill** runs each product notebook as a parameterized, isolated
process — the same logic as an interactive notebook, executed
programmatically with a single `end_date_arg` injected into the top cell.

**`ThreadPoolExecutor(max_workers=5)`** runs up to 5 notebooks
concurrently. The cap isn't arbitrary: it matches the per-user session
limit on the source database, so the pipeline can't starve other jobs
sharing the same connection budget.

**A single connection pool** lives in `ports_utils.py`
(`make_connection_pool`, `borrow_connection`) instead of each notebook
opening its own connection — one pool, borrowed and released per
notebook, avoids redundant setup/teardown under concurrency.

**Parquet** is the hand-off format between notebook and orchestrator:
each notebook writes its slice to `_tmp/<product>_<end_date>.parquet`,
and the orchestrator reads them back for concatenation — schema-preserving
and fast for several small-to-medium frames.

**The orchestrator runs as a standalone script, not inside Jupyter.**
papermill spawns each notebook execution as its own subprocess kernel;
launching that from within an already-running Jupyter kernel causes the
kernels to hang waiting on each other. A plain `python ports_main.py`
process avoids that conflict entirely.

## Running

```
python ports_main.py                 # uses yesterday (rolled back over weekends)
python ports_main.py 2026-05-15      # specific end_date
```

Output: `PORT.xlsx`, one row per `POS_ID`, one column per product plus `TOTAL`.

## Notes

- `compute_dates()` rolls Monday back to Friday, so weekend gaps don't
  appear as a missing business day.
- `TOTAL` sums only three of the seven pivoted product columns — a
  deliberate business rule, not a bug, included to show that not every
  rollup needs every column.
