import unittest
from copy import deepcopy
from src.config import ROOT
from src.extract import extract
from src.transform import transform

class TransformTests(unittest.TestCase):
    def setUp(self):
        self.raw = extract(ROOT / "data/raw")

    def test_duplicates_and_optional_values(self):
        clean, errors, duplicates = transform(self.raw)
        self.assertEqual(len(duplicates), 2)
        customer = next(r for r in clean["customers"] if r["customer_id"] == "C002")
        self.assertIsNone(customer["email"])
        self.assertEqual(customer["region"], "Unknown")
        self.assertNotIn("O007", [r["order_id"] for r in clean["orders"]])
        self.assertEqual(sum(e["error_code"] == "KEY_CONFLICT" for e in errors), 2)

    def test_invalid_numbers_do_not_become_zero(self):
        for value in ("", "1.2", "-1", "NaN", "1e3", "1000000000001"):
            with self.subTest(value=value):
                raw = deepcopy(self.raw)
                raw["order_items"][0]["unit_price"] = value
                clean, errors, _ = transform(raw)
                self.assertNotIn("I001", [r["order_item_id"] for r in clean["order_items"]])
                self.assertTrue(any(e["record_key"] == "I001" for e in errors))

    def test_missing_header_is_fatal(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "customers.csv").write_text("customer_id\nC1\n")
            with self.assertRaises(ValueError):
                extract(folder)
