# Portfolio Projects

Business Analyst moving toward analytics engineering. Comfortable in Oracle
SQL, Python, and Power BI, building toward dbt-centered pipelines.

## [ports-pipeline/](./ports-pipeline/)

A parallel multi-product notebook orchestration pattern: papermill-driven,
parameterized notebooks run concurrently under a bounded thread pool, with
a shared connection pool and Parquet intermediates tying them together.
One sample product notebook is included; all data is synthetic.

## [ma-thesis/](./ma-thesis/)

MA thesis code: does a constrained minimum-variance portfolio beat a
passive cap-weighted benchmark on a risk-adjusted basis? A rolling-window
optimization pipeline with Ledoit-Wolf covariance shrinkage, backtested
against the S&P 500 (2001–2024) and tested with the Jobson-Korkie-Memmel
Sharpe test, factor regressions, and a regime-conditional bootstrap.

## [premier-league-bi/](./premier-league-bi/)

A Power BI dashboard over 11 seasons of Premier League results (2015/16–2025/26):
league standings, a home-field-advantage breakdown per team, and rolling 5-match
form over time. Python script pulls and reconciles the source data; DAX measures
use an unpivoted team-match fact table and a manual sliding-window pattern for
the form calculation.
