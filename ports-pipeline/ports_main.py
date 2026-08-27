"""PORTS pipeline orchestrator.

Runs the 7 product notebooks in parallel via papermill, concatenates their
parquet outputs, applies the per-product pivot, aggregates by POS_ID,
and exports to PORT.xlsx.

Usage
-----
    py ports_main.py                  # uses computed dates (yesterday)
    py ports_main.py 2026-05-15       # uses specified end_date
"""
import os
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import papermill as pm

from ports_utils import compute_dates


# Each row: (notebook_filename_stem, sql_product_literal, pivot_column_name)
# - notebook_filename_stem: products/<stem>.ipynb
# - sql_product_literal:    what the notebook's SQL returns in the PRODUCT column
# - pivot_column_name:      name of the column in the final pivoted output
PRODUCTS = [
    ('product_a'         , 'PRODUCT_A'                   , 'PRODUCT_A'),
    ('loans'             , 'PRODUCT_B'                   , 'PRODUCT_B'),
    ('product_c'         , 'PRODUCT_C'                   , 'PRODUCT_C'),
    ('product_d'         , 'PRODUCT_D'                   , 'PRODUCT_D'),
    ('product_e'         , 'PRODUCT_E'                   , 'PRODUCT_E'),
    ('product_f'         , 'PRODUCT_F'                   , 'PRODUCT_F'),
    ('product_g'         , 'PRODUCT_G'                   , 'PRODUCT_G'),
]


def run_one_notebook(name, end_date_arg):
    pm.execute_notebook(
        input_path   = f'products/{name}.ipynb',
        output_path  = f'_executed/{name}_out.ipynb',
        parameters   = {'end_date_arg': end_date_arg},
        progress_bar = False,
    )
    return name


def main():
    # --- Resolve dates ---
    end_date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    start_date, end_date, pre_date = compute_dates(end_date_arg)
    print(f"start_date = {start_date}")
    print(f"end_date   = {end_date}")
    print(f"pre_date   = {pre_date}")

    # --- Directory setup ---
    os.makedirs('_tmp', exist_ok=True)
    os.makedirs('_executed', exist_ok=True)

    # --- Parallel execution ---
    started = datetime.now()
    print(f"\nStarted at {started.strftime('%H:%M:%S')}")
    errors = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(run_one_notebook, name, end_date_arg): name
            for name, _, _ in PRODUCTS
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                print(f"  ✅ {name:12s}  (elapsed: {datetime.now() - started})")
            except Exception as e:
                errors[name] = e
                print(f"  ❌ {name} FAILED — see _executed/{name}_out.ipynb")
                print(f"     {type(e).__name__}: {e}")

    print(f"\nTotal elapsed: {datetime.now() - started}")
    if errors:
        raise RuntimeError(f"Some products failed: {list(errors)}")

    # --- Concatenate parquet outputs ---
    print()
    dfs = []
    for name, _, _ in PRODUCTS:
        df = pd.read_parquet(f'_tmp/{name}_{end_date}.parquet')
        print(f"  {name:12s}: {len(df):>6,} rows")
        dfs.append(df)
    combined_df = pd.concat(dfs, ignore_index=True)

    # --- Per-product pivot (mirrors original PORTS.ipynb Cell 15) ---
    # For each product, create a column = AMT where PRODUCT matches the SQL literal, else 0.
    for _, sql_literal, pivot_col in PRODUCTS:
        combined_df[pivot_col] = combined_df['AMT'] * (
            combined_df['PRODUCT'] == sql_literal
        ).astype(int)

    # TOTAL sums a specific 3-of-7 product subset — a deliberate business rule
    combined_df['TOTAL'] = (combined_df['PRODUCT_C']
                            + combined_df['PRODUCT_D']
                            + combined_df['PRODUCT_B'])

    # --- Group by POS_ID, sum each column ---
    agg_cols = [pivot_col for _, _, pivot_col in PRODUCTS] + ['TOTAL']
    result_df = (combined_df
                 .groupby('POS_ID')[agg_cols]
                 .sum()
                 .reset_index()
                 .sort_values('POS_ID'))

    # --- Export ---
    result_df.to_excel('PORT.xlsx', index=False)
    print(f"\nWrote PORT.xlsx ({len(result_df)} branches)")
    print(result_df.head())


if __name__ == '__main__':
    main()
