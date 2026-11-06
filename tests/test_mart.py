"""MART (STEP 7~8) : 스타 스키마 행 수, 품질 검사, 리포트 뷰, SCD2, 소프트 삭제, 멱등성."""
import unittest

from src import mart, reports
from src.pipeline import prepare
from tests.helpers import RAW, first_run, copy_raw


def business_view(state):
    """대리키 대신 업무 키로 바꾼 비교용 스냅샷 (load_id·updated_at 제외)."""
    ckey = {r["customer_key"]: (r["customer_id"], r["valid_from"]) for r in state["dim_customer"]}
    pkey = {r["product_key"]: (r["product_id"], r["valid_from"]) for r in state["dim_product"]}
    drop = ("load_id", "updated_at", "customer_key", "product_key")
    out = {}
    for t in ("fact_sales_line", "fact_payment", "fact_order_lifecycle"):
        out[t] = sorted(repr(sorted({**{k: v for k, v in r.items() if k not in drop},
                                     "customer": ckey[r["customer_key"]],
                                     "product": pkey.get(r.get("product_key"))}.items())) for r in state[t])
    for t in ("dim_customer", "dim_product"):
        out[t] = sorted(repr(sorted((k, v) for k, v in r.items() if not k.endswith("_key") and k != "load_id"))
                        for r in state[t])
    return out


class MartTests(unittest.TestCase):
    def setUp(self):
        self.run = first_run()
        self.state = self.run["state"]

    def test_row_counts_and_status(self):
        self.assertEqual(self.run["run"]["status"], "SUCCESS")
        self.assertEqual(mart.table_counts(self.state), {
            "dim_customer": 1998, "dim_product": 151, "dim_date": 4019,
            "fact_sales_line": 65789, "fact_payment": 30966, "fact_order_lifecycle": 29802})

    def test_all_17_dq_checks_pass(self):
        self.assertEqual(len(self.run["checks"]), 17)
        self.assertEqual([n for n, f in self.run["checks"] if f], [])

    def test_unknown_members(self):
        lines = self.state["fact_sales_line"]
        self.assertEqual(sum(r["customer_key"] == -1 for r in lines), 254)
        self.assertEqual(sum(r["product_key"] == -1 for r in lines), 61)
        self.assertFalse(any(r["is_revenue_eligible"] and -1 in (r["customer_key"], r["product_key"]) for r in lines))

    def test_report_views(self):
        self.assertEqual(reports.headline(self.state), {"revenue": 2198198700, "orders": 27055, "avg_order_value": 81249})
        self.assertEqual(len(reports.revenue_calendar(self.state)), 669)
        category = {}
        for p in reports.revenue_by_product(self.state):
            category[p["category"]] = category.get(p["category"], 0) + p["revenue"]
        self.assertEqual(category["전자기기"], 921160700)
        self.assertEqual(category["식품"], 93567100)
        region = {r["region"]: (r["order_count"], r["revenue"]) for r in reports.revenue_by_region_aswas(self.state)}
        self.assertEqual(region["서울"], (5189, 420094900))
        self.assertEqual(region["경기"], (7741, 635003900))
        pay = {r["payment_status"]: (r["attempts"], r["orphan_payments"]) for r in reports.payment_summary(self.state)}
        self.assertEqual(pay, {"성공": (27702, 101), "실패": (2904, 7), "대기": (360, 0)})
        gross = sum(r["line_amount"] for r in self.state["fact_sales_line"] if not r["is_deleted"])
        self.assertEqual(gross, 2421319800)

    def test_dashboard_views(self):
        lines = reports.sales_line(self.state)
        self.assertEqual(len(lines), 59921)
        self.assertEqual(sum(r["revenue"] for r in lines), 2198198700)
        self.assertEqual(len({r["order_id"] for r in lines}), 27055)
        self.assertEqual(sum(r["revenue"] for r in lines if r["region"] == "서울"), 420094900)
        pay = reports.payment_daily(self.state)
        self.assertEqual(sum(r["attempts"] for r in pay), 30966)
        self.assertEqual(sum(r["orphan_payments"] for r in pay), 108)

    def test_same_input_twice_is_idempotent(self):
        again = prepare(RAW, self.state, "L2", "2026-11-04 11:00:00")
        self.assertEqual(again["run"]["status"], "SUCCESS")
        self.assertEqual(business_view(again["state"]), business_view(self.state))

    def test_scd2_region_change(self):
        def to_busan(table, rows):
            if table == "customers":
                for r in rows[1:]:
                    if r[0].strip() == "C002":
                        r[3] = "부산"
        second = prepare(copy_raw(to_busan), self.state, "L2", "2026-11-04 12:00:00")["state"]
        c002 = [(r["region"], r["valid_to"], r["is_current"]) for r in second["dim_customer"] if r["customer_id"] == "C002"]
        self.assertEqual(sorted(c002, key=repr), sorted([("Unknown", "2026-11-04 12:00:00", False), ("부산", None, True)], key=repr))
        aswas = {r["region"]: r["revenue"] for r in reports.revenue_by_region_aswas(second)}
        asis = {r["region"]: r["revenue"] for r in reports.revenue_by_region_asis(second)}
        self.assertEqual((aswas["부산"], aswas["Unknown"]), (120881700, 51063400))   # 주문 당시 기준: 그대로
        self.assertEqual((asis["부산"], asis["Unknown"]), (120896700, 51048400))     # 현재 기준: O002 15,000원 이동

    def test_missing_line_is_soft_deleted(self):
        def drop_i001(table, rows):
            if table == "order_items":
                return [r for r in rows if r[0] != "I001"]
        second = prepare(copy_raw(drop_i001), self.state, "L2", "2026-11-04 12:00:00")["state"]
        i001 = next(r for r in second["fact_sales_line"] if r["order_item_id"] == "I001")
        self.assertTrue(i001["is_deleted"])
        self.assertEqual(i001["load_id"], "L2")
        self.assertEqual(len(second["fact_sales_line"]), 65789)       # 물리 삭제 없음


if __name__ == "__main__":
    unittest.main()
