"""Single-writer, complete-snapshot publication. No DDL inside the DW transaction."""
from .config import ROOT
from .audit import record_issues, record_checks, finish

COLUMNS = {'dim_customer': ('customer_id', 'customer_name', 'region'), 'dim_product': ('product_id', 'product_name', 'category'), 'dim_date': ('date_key', 'calendar_date', 'year', 'month', 'year_month'), 'fact_orders': ('order_id', 'customer_id', 'date_key', 'order_amount'), 'fact_order_items': ('order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'line_amount')}

def statements(filename):
    return [s.strip() for s in (ROOT / "sql" / filename).read_text().split(";") if s.strip()]

def load(conn, run_id, result, allow_empty=False):
    conn.autocommit(True)
    record_issues(conn, run_id, result)
    if not result["dw"]["fact_orders"] and not allow_empty:
        raise ValueError("Zero valid sales orders: inspect report, or explicitly use --allow-empty")
    checks = []
    with conn.cursor() as cur:
        for table, cols in COLUMNS.items():
            rows = result["dw"][table]
            keys = [r[cols[0]] for r in rows]
            if len(keys) != len(set(keys)):
                raise ValueError(f"Duplicate staging key: {table}")
            if rows:
                cur.executemany(f"INSERT INTO STG.{table} (run_id,{','.join(cols)}) VALUES ({','.join(['%s']*(len(cols)+1))})",
                                [(run_id, *(r[c] for c in cols)) for r in rows])
        cur.execute("BEGIN")
        try:
            # Full snapshot: remove stale rows child-first, including previously valid orders
            # which are now excluded. This is not an incremental input contract.
            for table in reversed(COLUMNS):
                key = COLUMNS[table][0]
                cur.execute(f"DELETE FROM DW.{table} WHERE {key} NOT IN (SELECT {key} FROM STG.{table} WHERE run_id=%s)", (run_id,))
            for filename in ("03_merge_dimensions.sql", "04_merge_facts.sql"):
                for sql in statements(filename):
                    cur.execute(sql, (run_id,))
            for sql in statements("05_validate_dw.sql"):
                checks.extend(cur.execute(sql).fetchall())
            if any(int(count) for _,count in checks):
                raise ValueError("DW validation failed")
            record_checks(conn, run_id, checks)
            finish(conn, run_id, "SUCCESS", result["summary"])
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            record_checks(conn, run_id, checks)
            raise
