"""Shared utilities for the PORTS pipeline."""
import os
from contextlib import contextmanager
from datetime import datetime, timedelta

import cx_Oracle
from dotenv import load_dotenv

load_dotenv()


# Private banking HR codes — clients excluded from several PORTS queries.
# This list comes from the original PORTS.ipynb Cell 2.
PB_HR_CODES = [
    'C1284', 'C1285', 'A0033', 'A0361', 'A0362', 'B0874',
    'B7134', 'C1072', 'C0109', 'C5053', 'C7582',
]

# Comma-separated single-quoted form for SQL `IN (...)` clauses.
# Example: 'C1284', 'C1285', 'A0033', ...
PB_DF_SQL = ', '.join(f"'{code}'" for code in PB_HR_CODES)


def make_connection_pool(min_conn=1, max_conn=5):
    """Create a cx_Oracle session pool using credentials from environment.

    Required env vars: DB_USER, DB_PASSWORD, DB_DSN.
    """
    return cx_Oracle.SessionPool(
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        dsn=os.getenv('DB_DSN'),
        min=min_conn,
        max=max_conn,
        increment=1,
        encoding='UTF-8',
    )


@contextmanager
def borrow_connection(pool):
    """Borrow a connection from the pool; release on exit."""
    conn = pool.acquire()
    try:
        yield conn
    finally:
        pool.release(conn)


def compute_dates(end_date_str=None):
    """Compute (start_date, end_date, pre_date) for the PORTS pipeline.

    end_date: from argument, or yesterday (rolled back from Monday to Saturday).
    start_date: first day of end_date's month.
    pre_date:   last day of the previous month.

    Returns three 'YYYY-MM-DD' strings.
    """
    if end_date_str:
        date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        today = datetime.now().date()
        date_obj = today - timedelta(days=1)
        if today.weekday() == 0:        # if today is Monday, roll back to Saturday
            date_obj -= timedelta(days=1)

    end_date = date_obj.strftime('%Y-%m-%d')
    start_date = date_obj.replace(day=1).strftime('%Y-%m-%d')
    pre_date = (date_obj.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')

    return start_date, end_date, pre_date
