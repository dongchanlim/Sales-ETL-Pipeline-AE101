"""CORE (STEP 4~5) : 정제 결과와 매출 판정이 정답표(docs/data_generation.md)와 같은지 확인합니다."""
from collections import Counter
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from src.core import build_core
from src.extract import extract
from tests.helpers import RAW, first_run


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.result = first_run()["core"]

    def test_run_summary(self):
        self.assertEqual(self.result["summary"], {
            "input_rows": 129618, "duplicate_rows": 473, "quarantined_rows": 441,
            "flagged_issues": 559, "revenue_orders": 27055, "revenue_amount": 2198198700})

    def test_issue_actions(self):
        counts = Counter((i["action"], i["error_code"]) for i in self.result["issues"])
        self.assertEqual(counts, Counter({
            ("REMOVED", "EXACT_DUPLICATE"): 473,
            ("QUARANTINED", "KEY_CONFLICT"): 92, ("QUARANTINED", "INVALID_VALUE"): 152,
            ("QUARANTINED", "INVALID_REFERENCE"): 197,
            ("FLAGGED", "INVALID_REFERENCE"): 286, ("FLAGGED", "AMOUNT_MISMATCH"): 141,
            ("FLAGGED", "SUCCESS_PAYMENT_COUNT"): 101, ("FLAGGED", "MISSING_ITEMS"): 31}))

    def test_exclusion_reasons(self):
        counts = Counter(q["exclusion_reason"] for q in self.result["order_quality"])
        self.assertEqual(counts, Counter({None: 27055, "NOT_COMPLETED": 2190, "DEPENDENCY_ERROR": 284,
                                          "AMOUNT_MISMATCH": 141, "SUCCESS_PAYMENT_COUNT": 101, "MISSING_ITEMS": 31}))

    def test_teaching_cases(self):
        q = {r["order_id"]: r["exclusion_reason"] for r in self.result["order_quality"]}
        self.assertEqual({k for k in q if len(k) == 4 and q[k] is None}, {"O001", "O002"})
        self.assertEqual(q["O003"], "DEPENDENCY_ERROR")      # 주문 상세 필수값 누락
        self.assertEqual(q["O004"], "AMOUNT_MISMATCH")
        self.assertEqual(q["O005"], "SUCCESS_PAYMENT_COUNT")
        self.assertEqual(q["O006"], "DEPENDENCY_ERROR")      # 없는 상품 참조 (FLAGGED, 적재는 됨)
        self.assertNotIn("O007", q)                            # 키 충돌 → 격리 (CORE 에 없음)
        self.assertEqual(q["O008"], "NOT_COMPLETED")
        self.assertEqual(q["O009"], "DEPENDENCY_ERROR")      # 없는 고객 참조 (FLAGGED)
        self.assertEqual(q["O010"], "MISSING_ITEMS")
        c002 = next(c for c in self.result["core"]["customers"] if c["customer_id"] == "C002")
        self.assertIsNone(c002["email"])
        self.assertEqual(c002["region"], "Unknown")

    def test_reference_errors_are_flagged_not_dropped(self):
        orphan_payments = [p for p in self.result["payment_prep"] if not p["has_valid_order"]]
        self.assertEqual(len(orphan_payments), 108)
        self.assertEqual(len(self.result["sales_line_prep"]), 65789)

    def test_invalid_numbers_do_not_become_zero(self):
        raw = extract(RAW)
        for value in ("", "1.2", "-1", "NaN", "1e3", "1000000000001"):
            with self.subTest(value=value):
                changed = deepcopy(raw)
                changed["order_items"][0]["unit_price"] = value
                result = build_core(changed)
                self.assertNotIn("I001", [r["order_item_id"] for r in result["core"]["order_items"]])
                self.assertTrue(any(i["record_key"] == "I001" and i["action"] == "QUARANTINED" for i in result["issues"]))

    def test_missing_header_is_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "customers.csv").write_text("customer_id\nC1\n")
            with self.assertRaises(ValueError):
                extract(folder)


if __name__ == "__main__":
    unittest.main()
