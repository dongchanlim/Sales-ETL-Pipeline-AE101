import unittest
from src.pipeline import prepare
from src.config import ROOT

class ValidationTests(unittest.TestCase):
    def test_sales_and_whole_order_quarantine(self):
        result = prepare(ROOT / "data/raw")
        self.assertEqual(result["summary"]["sales_orders"], 27055)
        self.assertEqual(result["summary"]["sales_amount"], 2198198700)
        self.assertEqual(len(result["dw"]["fact_order_items"]), 59921)
        self.assertEqual(sum(i["line_amount"] for i in result["dw"]["fact_order_items"]), 2198198700)
        # 수업용 사례 O001~O010: O001·O002 만 매출
        teaching = {o["order_id"] for o in result["dw"]["fact_orders"] if len(o["order_id"]) == 4}
        self.assertEqual(teaching, {"O001", "O002"})
        exclusions = {e["order_id"]:e["reason"] for e in result["exclusions"]}
        self.assertEqual(exclusions["O003"], "DEPENDENCY_ERROR")
        self.assertEqual(exclusions["O004"], "AMOUNT_MISMATCH")
        self.assertEqual(exclusions["O005"], "SUCCESS_PAYMENT_COUNT")
        self.assertEqual(exclusions["O006"], "DEPENDENCY_ERROR")
        self.assertEqual(exclusions["O007"], "INVALID_OR_MISSING_ORDER")
        self.assertEqual(exclusions["O008"], "NOT_COMPLETED")
        self.assertEqual(exclusions["O010"], "MISSING_ITEMS")
        self.assertEqual(exclusions["O404"], "INVALID_OR_MISSING_ORDER")

    def test_failed_then_succeeded_payment_is_allowed(self):
        result = prepare(ROOT / "data/raw")
        self.assertIn("O001", [r["order_id"] for r in result["dw"]["fact_orders"]])
