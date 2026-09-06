"""주문 전체를 검증한 후에만 매출 Fact를 만듭니다."""
from collections import defaultdict
from .transform import issue

def validate(clean, errors):
    errors = list(errors)
    customers = {r["customer_id"] for r in clean["customers"]}
    products = {r["product_id"] for r in clean["products"]}
    orders = {r["order_id"]: r for r in clean["orders"]}
    blocked = {e["order_id"] for e in errors if e["order_id"]}
    items, payments = defaultdict(list), defaultdict(list)
    for table, grouping in (("order_items", items), ("payments", payments)):
        for row in clean[table]:
            oid = row["order_id"]
            if oid not in orders or (table == "order_items" and row["product_id"] not in products):
                errors.append(issue(table, row, "INVALID_REFERENCE", "Missing accepted parent order/product"))
                blocked.add(oid)
            else:
                grouping[oid].append(row)
    valid_orders, valid_items, exclusions = [], [], []
    for oid, order in orders.items():
        if order["customer_id"] not in customers:
            errors.append(issue("orders", order, "INVALID_REFERENCE", "Missing accepted customer"))
            blocked.add(oid)
        if oid in blocked:
            reason = "DEPENDENCY_ERROR"
        elif order["order_status"] != "completed":
            reason = "NOT_COMPLETED"
        else:
            successes = [p for p in payments[oid] if p["payment_status"] == "succeeded"]
            if len(successes) != 1:
                reason = "SUCCESS_PAYMENT_COUNT"
            elif not items[oid]:
                reason = "MISSING_ITEMS"
            elif not (order["order_amount"] == sum(r["quantity"] * r["unit_price"] for r in items[oid]) == successes[0]["payment_amount"]):
                reason = "AMOUNT_MISMATCH"
            else:
                reason = None
        if reason:
            exclusions.append({"order_id": oid, "reason": reason})
            if reason not in {"NOT_COMPLETED", "DEPENDENCY_ERROR"}:
                errors.append(issue("orders", order, reason, "Order excluded from sales reporting"))
            continue
        valid_orders.append(order)
        valid_items.extend(items[oid])
    # Invalid/conflicting order records must also be counted as excluded orders.
    existing = {e["order_id"] for e in exclusions}
    for oid in sorted(blocked - set(orders) - existing):
        exclusions.append({"order_id": oid, "reason": "INVALID_OR_MISSING_ORDER"})
    return valid_orders, valid_items, errors, exclusions

def build_dw(clean, orders, items):
    dates = sorted({r["order_date"] for r in orders})
    return {
        "dim_customer": [{k: r[k] for k in ("customer_id", "customer_name", "region")} for r in clean["customers"]],
        "dim_product": [{k: r[k] for k in ("product_id", "product_name", "category")} for r in clean["products"]],
        "dim_date": [{"date_key": int(d.replace("-", "")), "calendar_date": d, "year": int(d[:4]), "month": int(d[5:7]), "year_month": d[:7]} for d in dates],
        "fact_orders": [{"order_id": r["order_id"], "customer_id": r["customer_id"], "date_key": int(r["order_date"].replace("-", "")), "order_amount": r["order_amount"]} for r in orders],
        "fact_order_items": [{**{k: r[k] for k in ("order_item_id", "order_id", "product_id", "quantity", "unit_price")}, "line_amount": r["quantity"] * r["unit_price"]} for r in items],
    }
