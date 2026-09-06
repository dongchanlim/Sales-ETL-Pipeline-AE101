"""AUDIT records are scoped by execution ID, not business keys."""
METRICS = ("input_rows", "duplicate_rows", "error_rows", "excluded_orders", "sales_orders", "sales_amount")

def start(conn, run_id):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO AUDIT.PIPELINE_RUNS (run_id,status,started_at) VALUES (%s,'RUNNING',CURRENT_TIMESTAMP())", (run_id,))

def finish(conn, run_id, status, summary=None, message=None):
    summary = summary or {}
    assignments = ",".join(f"{name}=%s" for name in METRICS)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE AUDIT.PIPELINE_RUNS SET status=%s,finished_at=CURRENT_TIMESTAMP(),{assignments},message=%s WHERE run_id=%s",
                    (status, *(summary.get(n) for n in METRICS), message, run_id))

def record_issues(conn, run_id, result):
    with conn.cursor() as cur:
        columns = ("source_file", "source_row_number", "record_key", "error_code", "error_detail", "order_id")
        rows = result["errors"] + result["duplicates"]
        if rows:
            cur.executemany("INSERT INTO AUDIT.DATA_ISSUES VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            [(run_id, *(r.get(c) for c in columns)) for r in rows])
        if result["exclusions"]:
            cur.executemany("INSERT INTO AUDIT.EXCLUDED_ORDERS VALUES (%s,%s,%s)",
                            [(run_id,r["order_id"],r["reason"]) for r in result["exclusions"]])

def record_checks(conn, run_id, checks):
    if checks:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO AUDIT.VALIDATION_RESULTS VALUES (%s,%s,%s)",
                            [(run_id,str(name),int(count)) for name,count in checks])
