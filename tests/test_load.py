"""Snowflake 연결 없이 load() 의 실행 순서와 실패 처리를 확인합니다 (가짜 연결 사용)."""
import unittest

from src.load import load, BATCH, CORE_FILES, MART_FILES, VIEW_FILES
from tests.helpers import first_run

SUMMARY = {"input_rows": 129618, "duplicate_rows": 473, "quarantined_rows": 441,
           "flagged_issues": 559, "revenue_orders": 27055, "revenue_amount": 2198198700}


class Cursor:
    def __init__(self, conn): self.conn = conn
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params=None):
        self.conn.calls.append(sql)
        self.last = sql
        return self
    def executemany(self, sql, rows): self.conn.calls.append(f"executemany:{sql.split('(')[0]}")
    def fetchone(self):
        if "CORE.RUN_CTX" in self.last:
            return ("LOAD-1", "2026-11-04 10:00:00.000")
        if "CORE.RUN_SUMMARY" in self.last:
            return tuple(self.conn.summary.values())
        if "AUDIT.PIPELINE_RUNS" in self.last:
            return (self.conn.status, None)
        return None


class Connection:
    def __init__(self, summary=SUMMARY, status="SUCCESS"):
        self.calls, self.files, self.summary, self.status = [], [], dict(summary), status
    def cursor(self): return Cursor(self)
    def execute_string(self, text, remove_comments=False):
        self.files.append(text.splitlines()[0].lstrip("- ").strip())
        return []


class LoadTests(unittest.TestCase):
    raw = staticmethod(lambda: first_run()["raw"])

    def test_success_runs_files_in_notebook_order(self):
        conn = Connection()
        self.assertEqual(load(conn, self.raw(), SUMMARY), "LOAD-1")
        self.assertEqual(conn.files, ["01_start_run.sql", *CORE_FILES, *MART_FILES, *VIEW_FILES])
        batches = sum(-(-len(rows) // BATCH) for rows in self.raw().values())   # 테이블별 5,000행 단위
        self.assertEqual(sum(c.startswith("executemany:INSERT INTO RAW.") for c in conn.calls), batches)

    def test_summary_mismatch_stops_before_mart(self):
        conn = Connection(summary={**SUMMARY, "revenue_orders": 1})
        with self.assertRaises(ValueError):
            load(conn, self.raw(), SUMMARY)
        self.assertEqual(conn.files, ["01_start_run.sql", *CORE_FILES])
        self.assertTrue(any("status = 'FAILED'" in c for c in conn.calls))

    def test_dq_failure_raises(self):
        conn = Connection(status="FAILED")
        with self.assertRaises(ValueError):
            load(conn, self.raw(), SUMMARY)
        self.assertNotIn("10_report_views.sql", conn.files)

    def test_empty_revenue_is_explicit(self):
        empty = {**SUMMARY, "revenue_orders": 0, "revenue_amount": 0}
        with self.assertRaises(ValueError):
            load(Connection(summary=empty), self.raw(), empty)
        conn = Connection(summary=empty)
        load(conn, self.raw(), empty, allow_empty=True)
        self.assertIn("09_finalize_run.sql", conn.files)


if __name__ == "__main__":
    unittest.main()
