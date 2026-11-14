"""재실행 불변성 : 행 순서를 바꾸고 모든 행을 중복시켜도 CORE·MART 결과가 같아야 합니다."""
import os
import random
import unittest

from src.pipeline import prepare
from tests.helpers import RAW, first_run, copy_raw
from tests.test_mart import business_view


class RerunTests(unittest.TestCase):
    def test_reorder_and_duplicate_source_rows(self):
        def shuffle_and_double(table, rows):
            body = rows[1:] * 2
            random.Random(42).shuffle(body)
            return [rows[0], *body]
        baseline = first_run()
        repeat = prepare(copy_raw(shuffle_and_double), None, "L1", "2026-11-04 10:00:00")
        self.assertEqual(repeat["core"]["summary"]["revenue_amount"], baseline["core"]["summary"]["revenue_amount"])
        self.assertEqual(repeat["core"]["summary"]["revenue_orders"], baseline["core"]["summary"]["revenue_orders"])
        self.assertGreater(repeat["core"]["summary"]["duplicate_rows"], baseline["core"]["summary"]["duplicate_rows"])
        self.assertEqual(business_view(repeat["state"]), business_view(baseline["state"]))


@unittest.skipUnless(os.getenv("AE101_RUN_SNOWFLAKE_TESTS") == "1", "Explicit opt-in and dedicated Snowflake test database required")
class SnowflakeRerunTests(unittest.TestCase):
    """실제 Snowflake 에서 같은 입력을 두 번 적재해 MART 업무 값이 같은지 확인합니다 (_TEST DB 전용)."""

    def test_live_load_twice(self):
        from src.config import connect, DATABASE
        from src.core import build_core
        from src.extract import extract
        from src.load import load
        if not DATABASE.upper().endswith("_TEST"):
            self.fail("Use an initialized, disposable database ending in _TEST (python -m src.pipeline --setup)")
        raw = extract(RAW)
        summary = build_core(raw)["summary"]
        conn = connect()
        query = ("SELECT f.order_item_id, c.customer_id, p.product_id, f.line_amount, f.is_revenue_eligible, f.is_deleted "
                 "FROM MART.FACT_SALES_LINE f JOIN MART.DIM_CUSTOMER c ON f.customer_key = c.customer_key "
                 "JOIN MART.DIM_PRODUCT p ON f.product_key = p.product_key ORDER BY 1")
        try:
            snapshots = []
            for _ in range(2):
                load(conn, raw, summary)
                with conn.cursor() as cur:
                    snapshots.append(cur.execute(query).fetchall())
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(len(snapshots[0]), 65789)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
