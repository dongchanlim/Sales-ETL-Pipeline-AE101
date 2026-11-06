"""리포트 뷰 : sql/10_report_views.sql (STEP 8) 의 MART.V_* 뷰를 Python 으로 계산합니다.

모든 매출 뷰는 '매출 인식 + 삭제되지 않은' FACT_SALES_LINE 만 사용하고, 고객 차원과 연결합니다.
"""
from collections import defaultdict
from datetime import date, timedelta


def _live_revenue_lines(state):
    return [r for r in state["fact_sales_line"] if r["is_revenue_eligible"] and not r["is_deleted"]]


def _index(rows, key):
    return {r[key]: r for r in rows}


def revenue_daily(state):
    """V_REVENUE_DAILY : 주문일별 주문 수·수량·매출."""
    dates = _index(state["dim_date"], "date_key")
    agg = defaultdict(lambda: [set(), 0, 0])
    for r in _live_revenue_lines(state):
        d = dates[r["order_date_key"]]
        a = agg[(d["calendar_date"], d["day_name"])]
        a[0].add(r["order_id"]); a[1] += r["quantity"]; a[2] += r["line_amount"]
    return [{"order_date": k[0], "day_name": k[1], "order_count": len(v[0]), "quantity": v[1], "revenue": v[2]}
            for k, v in sorted(agg.items())]


def revenue_calendar(state):
    """V_REVENUE_CALENDAR : 첫 주문일 ~ 마지막 주문일의 모든 날. 매출 없는 날은 0."""
    live = [o["order_date"] for o in state["fact_order_lifecycle"] if not o["is_deleted"]]
    if not live:
        return []
    daily = {r["order_date"]: r for r in revenue_daily(state)}
    d, end, out = date.fromisoformat(min(live)), date.fromisoformat(max(live)), []
    while d <= end:
        r = daily.get(d.isoformat())
        out.append({"calendar_date": d.isoformat(), "order_count": r["order_count"] if r else 0,
                    "revenue": r["revenue"] if r else 0})
        d += timedelta(days=1)
    return out


def revenue_by_product(state):
    """V_REVENUE_BY_PRODUCT : 상품(주문 당시 버전)별 수량·매출."""
    products = _index(state["dim_product"], "product_key")
    agg = defaultdict(lambda: [0, 0])
    for r in _live_revenue_lines(state):
        p = products[r["product_key"]]
        a = agg[(p["product_id"], p["product_name"], p["category"])]
        a[0] += r["quantity"]; a[1] += r["line_amount"]
    return sorted(({"product_id": k[0], "product_name": k[1], "category": k[2], "quantity": v[0], "revenue": v[1]}
                   for k, v in agg.items()), key=lambda x: (-x["revenue"], x["product_id"]))


def _by_region(state, as_is):
    customers = _index(state["dim_customer"], "customer_key")
    current = {c["customer_id"]: c for c in state["dim_customer"] if c["is_current"]}
    agg = defaultdict(lambda: [set(), 0])
    for r in _live_revenue_lines(state):
        c = customers[r["customer_key"]]
        region = current[c["customer_id"]]["region"] if as_is else c["region"]
        agg[region][0].add(r["order_id"]); agg[region][1] += r["line_amount"]
    return sorted(({"region": k, "order_count": len(v[0]), "revenue": v[1]} for k, v in agg.items()),
                  key=lambda x: (-x["revenue"], x["region"]))


def revenue_by_region_aswas(state):
    """V_REVENUE_BY_REGION_ASWAS : 주문 '당시' 고객 지역 기준 (SCD2 버전 그대로)."""
    return _by_region(state, as_is=False)


def revenue_by_region_asis(state):
    """V_REVENUE_BY_REGION_ASIS : 고객의 '현재' 지역 기준."""
    return _by_region(state, as_is=True)


def order_quality(state):
    """V_ORDER_QUALITY : 매출에서 빠진 주문도 사유와 함께."""
    customers = _index(state["dim_customer"], "customer_key")
    status = _index(state["dim_order_status"], "order_status_key")
    return [{"order_id": o["order_id"], "order_date": o["order_date"],
             "order_status": status[o["order_status_key"]]["status_name"],
             "customer_id": customers[o["customer_key"]]["customer_id"], "region": customers[o["customer_key"]]["region"],
             "order_amount": o["order_amount"], "is_revenue_eligible": o["is_revenue_eligible"],
             "exclusion_reason": o["exclusion_reason"]}
            for o in state["fact_order_lifecycle"] if not o["is_deleted"]]


def payment_summary(state):
    """V_PAYMENT_SUMMARY : 결제 상태별 시도 수·금액·주문 없는 결제 수."""
    status = _index(state["dim_payment_status"], "payment_status_key")
    agg = defaultdict(lambda: [0, 0, 0])
    for p in state["fact_payment"]:
        if p["is_deleted"]:
            continue
        a = agg[status[p["payment_status_key"]]["status_name"]]
        a[0] += 1; a[1] += p["payment_amount"]; a[2] += 0 if p["has_valid_order"] else 1
    return [{"payment_status": k, "attempts": v[0], "amount": v[1], "orphan_payments": v[2]} for k, v in sorted(agg.items())]


def headline(state):
    """대시보드 상단 지표 : 총매출·주문 수·평균 주문 금액 (V_REVENUE_DAILY 합계)."""
    daily = revenue_daily(state)
    revenue = sum(r["revenue"] for r in daily)
    orders = sum(r["order_count"] for r in daily)
    return {"revenue": revenue, "orders": orders, "avg_order_value": round(revenue / orders) if orders else None}


def sales_line(state):
    """V_SALES_LINE : 대시보드용 라인 단위 매출 (매출 인식 + 미삭제, 지역 = 주문 당시)."""
    dates = _index(state["dim_date"], "date_key")
    customers = _index(state["dim_customer"], "customer_key")
    products = _index(state["dim_product"], "product_key")
    out = []
    for r in _live_revenue_lines(state):
        d, c, p = dates[r["order_date_key"]], customers[r["customer_key"]], products[r["product_key"]]
        out.append({"order_id": r["order_id"], "order_item_id": r["order_item_id"], "order_date": d["calendar_date"],
                    "year_month": d["year_month"], "is_weekend": d["is_weekend"], "customer_id": c["customer_id"],
                    "region": c["region"], "product_id": p["product_id"], "product_name": p["product_name"],
                    "category": p["category"], "quantity": r["quantity"], "unit_price": r["unit_price"],
                    "revenue": r["line_amount"]})
    return out


def payment_daily(state):
    """V_PAYMENT_DAILY : 결제일·지역·상태별 시도 수·금액·주문 없는 결제 수."""
    dates = _index(state["dim_date"], "date_key")
    customers = _index(state["dim_customer"], "customer_key")
    status = _index(state["dim_payment_status"], "payment_status_key")
    agg = defaultdict(lambda: [0, 0, 0])
    for p in state["fact_payment"]:
        if p["is_deleted"]:
            continue
        key = (dates[p["paid_date_key"]]["calendar_date"], customers[p["customer_key"]]["region"],
               status[p["payment_status_key"]]["status_name"])
        a = agg[key]
        a[0] += 1; a[1] += p["payment_amount"]; a[2] += 0 if p["has_valid_order"] else 1
    return [{"paid_date": k[0], "region": k[1], "payment_status": k[2], "attempts": v[0], "amount": v[1],
             "orphan_payments": v[2]} for k, v in sorted(agg.items())]
