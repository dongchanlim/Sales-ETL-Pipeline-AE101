"""CORE : RAW 최신 배치를 정제·검증하고 주문 단위 매출 인식 여부를 판정합니다.

sql/03_core_clean.sql (STEP 4) 와 sql/04_core_order_quality.sql (STEP 5) 를 Python 으로 옮긴 것입니다.
규칙을 바꿀 때는 SQL 과 이 파일을 함께 바꾸고 tests/ 의 정답값으로 확인하세요.

이슈의 action
  REMOVED     : 완전히 같은 원본 행. 1건만 남기고 제거
  QUARANTINED : 키 충돌·필수값/형식 오류·부모 주문 없는 주문 상세. CORE 에 넣지 않음
  FLAGGED     : 적재는 하되 표시. 없는 고객/상품 참조(-1 로 연결), 주문 없는 결제, 매출 제외 사유
"""
from collections import defaultdict
from datetime import datetime
import hashlib
import re

from .extract import COLUMNS, KEYS

INPUT_LIMIT = 10**12
ORDER_STATUSES = ("completed", "pending", "cancelled")
PAYMENT_STATUSES = ("succeeded", "failed", "pending")
REQUIRED = {
    "customers": ("customer_id", "customer_name"),          # email·region 은 선택값
    "products": ("product_id", "product_name", "category"),
    "orders": COLUMNS["orders"],
    "order_items": COLUMNS["order_items"],
    "payments": COLUMNS["payments"],
}
NUMERIC = {"orders": ("order_amount",), "order_items": ("quantity", "unit_price"), "payments": ("payment_amount",)}
FLAG_REASONS = ("SUCCESS_PAYMENT_COUNT", "MISSING_ITEMS", "AMOUNT_MISMATCH")


def clean_text(value):
    """SQL NULLIF(TRIM(x), '') 와 같음. Snowflake TRIM 은 공백 문자만 제거합니다."""
    if value is None:
        return None
    value = value.strip(" ")
    return value or None


def md5(*parts):
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def _is_int(value):
    return re.fullmatch(r"[0-9]+", value) is not None


def _valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_ts(value):
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def _row_error(table, row):
    """SQL CASE 문의 검사 순서를 그대로 따릅니다. 첫 번째 오류 하나만 돌려줍니다."""
    for col in REQUIRED[table]:
        if row[col] is None:
            return f"{col}: required value missing"
    for col in NUMERIC.get(table, ()):
        if not _is_int(row[col]):
            return f"{col}: expected non-negative integer KRW/quantity"
        if int(row[col]) > INPUT_LIMIT:
            return f"{col}: exceeds project input limit"
    if table == "orders":
        if not _valid_date(row["order_date"]):
            return "order_date: invalid date"
        if row["order_status"] not in ORDER_STATUSES:
            return "unknown order_status"
    if table == "order_items" and int(row["quantity"]) == 0:
        return "quantity must be positive"
    if table == "payments":
        if row["payment_status"] not in PAYMENT_STATUSES:
            return "unknown payment_status"
        if not _valid_ts(row["paid_at"]):
            return "paid_at: invalid timestamp"
    return None


def issue(table, row, code, detail, action, order_id=None):
    return {"source_file": f"{table}.csv", "source_row_number": row["src_row"],
            "record_key": row.get(KEYS[table]), "error_code": code, "error_detail": detail,
            "order_id": order_id, "action": action}


def check_table(table, rows):
    """*_CHK 단계: 각 원본 행의 dq_status (DUPLICATE / CONFLICT / INVALID / OK) 를 판정합니다."""
    cols = COLUMNS[table]
    seen, unique, checked = set(), [], []
    for row in sorted(rows, key=lambda r: r["src_row"]):
        signature = tuple(row[c] for c in cols)          # 완전 중복은 TRIM 전 원본 값으로 판단
        cleaned = {"src_row": row["src_row"], **{c: clean_text(row[c]) for c in cols}}
        if signature in seen:
            checked.append({**cleaned, "dq_status": "DUPLICATE", "err": None})
        else:
            seen.add(signature)
            unique.append(cleaned)
    key_cnt = defaultdict(int)
    for row in unique:
        key_cnt[row[KEYS[table]]] += 1
    for row in unique:
        err = _row_error(table, row)
        key = row[KEYS[table]]
        status = "CONFLICT" if key is not None and key_cnt[key] > 1 else ("INVALID" if err else "OK")
        checked.append({**row, "dq_status": status, "err": err})
    return checked


def _chk_issues(table, checked):
    out = []
    for r in checked:
        if r["dq_status"] == "OK":
            continue
        order_id = r.get("order_id") if table in ("orders", "order_items", "payments") else None
        if r["dq_status"] == "DUPLICATE":
            out.append(issue(table, r, "EXACT_DUPLICATE", "Identical source row removed", "REMOVED", order_id))
        elif r["dq_status"] == "CONFLICT":
            out.append(issue(table, r, "KEY_CONFLICT", "Same business key has conflicting source rows", "QUARANTINED", order_id))
        else:
            out.append(issue(table, r, "INVALID_VALUE", r["err"], "QUARANTINED", order_id))
    return out


def clean(raw):
    """STEP 4. 정제 결과(CORE 테이블)와 이슈 목록을 돌려줍니다."""
    issues, core = [], {}
    chk = {t: check_table(t, raw[t]) for t in COLUMNS}
    ok = {t: [r for r in chk[t] if r["dq_status"] == "OK"] for t in COLUMNS}
    for t in COLUMNS:
        issues += _chk_issues(t, chk[t])

    core["customers"] = [{
        "customer_id": r["customer_id"], "customer_name": r["customer_name"], "email": r["email"],
        "region": r["region"] or "Unknown",
        "hash_diff": md5(r["customer_name"] or "", r["email"] or "", r["region"] or "Unknown"),
        "src_row": r["src_row"]} for r in ok["customers"]]
    core["products"] = [{
        "product_id": r["product_id"], "product_name": r["product_name"], "category": r["category"],
        "hash_diff": md5(r["product_name"] or "", r["category"] or ""),
        "src_row": r["src_row"]} for r in ok["products"]]
    customer_ids = {c["customer_id"] for c in core["customers"]}
    product_ids = {p["product_id"] for p in core["products"]}

    core["orders"] = [{
        "order_id": r["order_id"], "customer_id": r["customer_id"], "order_date": r["order_date"],
        "order_status": r["order_status"], "order_amount": int(r["order_amount"]),
        "has_valid_customer": r["customer_id"] in customer_ids, "src_row": r["src_row"]} for r in ok["orders"]]
    for o in core["orders"]:
        if not o["has_valid_customer"]:
            issues.append(issue("orders", o, "INVALID_REFERENCE", "Unknown customer: loaded with customer_key = -1",
                                "FLAGGED", o["order_id"]))
    order_ids = {o["order_id"] for o in core["orders"]}

    core["order_items"] = []
    for r in ok["order_items"]:
        if r["order_id"] not in order_ids:      # 주문이 없는 상세: 날짜·고객을 알 수 없어 격리
            issues.append(issue("order_items", r, "INVALID_REFERENCE", "Parent order not found: quarantined",
                                "QUARANTINED", r["order_id"]))
            continue
        core["order_items"].append({
            "order_item_id": r["order_item_id"], "order_id": r["order_id"], "product_id": r["product_id"],
            "quantity": int(r["quantity"]), "unit_price": int(r["unit_price"]),
            "has_valid_product": r["product_id"] in product_ids, "src_row": r["src_row"]})
    for i in core["order_items"]:
        if not i["has_valid_product"]:
            issues.append(issue("order_items", i, "INVALID_REFERENCE", "Unknown product: loaded with product_key = -1",
                                "FLAGGED", i["order_id"]))

    core["payments"] = [{
        "payment_id": r["payment_id"], "order_id": r["order_id"], "payment_status": r["payment_status"],
        "payment_amount": int(r["payment_amount"]), "paid_at": r["paid_at"],
        "has_valid_order": r["order_id"] in order_ids, "src_row": r["src_row"]} for r in ok["payments"]]
    for p in core["payments"]:
        if not p["has_valid_order"]:
            issues.append(issue("payments", p, "INVALID_REFERENCE", "Parent order not found: loaded with customer_key = -1",
                                "FLAGGED", p["order_id"]))
    return core, issues


def order_quality(core, issues):
    """STEP 5. 모든 주문에 매출 인식 여부와 제외 사유를 붙입니다. 제외된 주문도 MART 에 적재됩니다."""
    blocked = {i["order_id"] for i in issues if i["action"] in ("QUARANTINED", "FLAGGED") and i["order_id"] is not None}
    items = defaultdict(lambda: [0, 0])
    for i in core["order_items"]:
        items[i["order_id"]][0] += 1
        items[i["order_id"]][1] += i["quantity"] * i["unit_price"]
    pays = defaultdict(lambda: [0, 0, None])
    for p in core["payments"]:
        if p["has_valid_order"] and p["payment_status"] == "succeeded":
            agg = pays[p["order_id"]]
            agg[0] += 1
            agg[1] += p["payment_amount"]
            agg[2] = p["paid_at"] if agg[2] is None else min(agg[2], p["paid_at"])
    result, new_issues = [], []
    for o in core["orders"]:
        oid = o["order_id"]
        line_count, line_total = items.get(oid, (0, 0))
        pay_count, pay_amount, first_paid = pays.get(oid, (0, 0, None))
        if oid in blocked:
            reason = "DEPENDENCY_ERROR"
        elif o["order_status"] != "completed":
            reason = "NOT_COMPLETED"
        elif pay_count != 1:
            reason = "SUCCESS_PAYMENT_COUNT"
        elif line_count == 0:
            reason = "MISSING_ITEMS"
        elif not (o["order_amount"] == line_total == pay_amount):
            reason = "AMOUNT_MISMATCH"
        else:
            reason = None
        result.append({
            "order_id": oid, "customer_id": o["customer_id"], "order_date": o["order_date"],
            "order_status": o["order_status"], "order_amount": o["order_amount"],
            "line_count": line_count, "line_amount_total": line_total,
            "success_payment_count": pay_count, "success_payment_amount": pay_amount,
            "first_success_paid_at": first_paid, "exclusion_reason": reason,
            "is_revenue_eligible": reason is None})
        if reason in FLAG_REASONS:
            new_issues.append(issue("orders", o, reason, "Order excluded from revenue (still loaded)", "FLAGGED", oid))
    return result, new_issues


def prepare_facts(core, quality):
    """Fact 적재 직전 형태 (키는 아직 업무 키). SALES_LINE_PREP / PAYMENT_PREP."""
    q = {r["order_id"]: r for r in quality}
    orders = {o["order_id"]: o for o in core["orders"]}
    sales_line = [{
        "order_item_id": i["order_item_id"], "order_id": i["order_id"], "customer_id": q[i["order_id"]]["customer_id"],
        "product_id": i["product_id"], "order_date": q[i["order_id"]]["order_date"],
        "order_status": q[i["order_id"]]["order_status"], "quantity": i["quantity"], "unit_price": i["unit_price"],
        "line_amount": i["quantity"] * i["unit_price"],
        "is_revenue_eligible": q[i["order_id"]]["is_revenue_eligible"],
        "exclusion_reason": q[i["order_id"]]["exclusion_reason"]} for i in core["order_items"]]
    payment = []
    for p in core["payments"]:
        o = orders.get(p["order_id"])
        payment.append({
            "payment_id": p["payment_id"], "order_id": p["order_id"],
            "customer_id": o["customer_id"] if o else None, "order_date": o["order_date"] if o else None,
            "paid_at": p["paid_at"], "paid_date": p["paid_at"][:10], "payment_status": p["payment_status"],
            "payment_amount": p["payment_amount"], "has_valid_order": p["has_valid_order"]})
    return sales_line, payment


def run_summary(raw, issues, quality):
    """CORE.RUN_SUMMARY 와 같은 6개 지표."""
    eligible = [q for q in quality if q["is_revenue_eligible"]]
    return {
        "input_rows": sum(len(rows) for rows in raw.values()),
        "duplicate_rows": sum(i["action"] == "REMOVED" for i in issues),
        "quarantined_rows": len({(i["source_file"], i["source_row_number"]) for i in issues if i["action"] == "QUARANTINED"}),
        "flagged_issues": sum(i["action"] == "FLAGGED" for i in issues),
        "revenue_orders": len(eligible),
        "revenue_amount": sum(q["order_amount"] for q in eligible),
    }


def build_core(raw):
    """STEP 4 ~ 5 전체. 반환값은 MART 적재와 보고서에 필요한 모든 CORE 결과입니다."""
    core, issues = clean(raw)
    quality, flagged = order_quality(core, issues)
    issues += flagged
    sales_line, payment = prepare_facts(core, quality)
    return {"core": core, "issues": issues, "order_quality": quality,
            "sales_line_prep": sales_line, "payment_prep": payment,
            "summary": run_summary(raw, issues, quality)}
