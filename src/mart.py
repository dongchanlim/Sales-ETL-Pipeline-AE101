"""MART : 스타 스키마(차원 5 + Fact 3)를 CORE 결과로 갱신합니다.

sql/00_setup.sql 의 MART DDL 과 sql/06 ~ 09 (STEP 7-1 ~ 7-4) 를 Python 으로 옮긴 것입니다.

  차원  DIM_CUSTOMER, DIM_PRODUCT : 대리키 + SCD Type 2 (valid_from / valid_to / is_current), Unknown 멤버 -1
        DIM_DATE                   : 2020-01-01 ~ 2030-12-31 전체 달력 + Unknown(-1)
        DIM_ORDER_STATUS, DIM_PAYMENT_STATUS
  Fact  FACT_SALES_LINE (주문 상세 1행) / FACT_PAYMENT (결제 시도 1건) / FACT_ORDER_LIFECYCLE (주문 1건)
        MERGE(업서트) + 이번 스냅샷에서 사라진 행은 is_deleted = TRUE (소프트 삭제)

상태(state)는 JSON 으로 저장할 수 있는 dict 입니다. 이전 state 를 넘기면 SCD2 이력과 소프트 삭제가 이어집니다.
시각은 'YYYY-MM-DD HH:MM:SS', 날짜는 'YYYY-MM-DD' 문자열로 다룹니다 (문자열 비교 = 시간 순서).
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta

BEGIN_OF_TIME = "1900-01-01 00:00:00"
END_OF_TIME = "9999-12-31 00:00:00"
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")   # Snowflake DAYNAME()

DIM_ORDER_STATUS = [
    {"order_status_key": 1, "status_code": "completed", "status_name": "완료", "is_final": True},
    {"order_status_key": 2, "status_code": "pending", "status_name": "대기", "is_final": False},
    {"order_status_key": 3, "status_code": "cancelled", "status_name": "취소", "is_final": True},
    {"order_status_key": -1, "status_code": "unknown", "status_name": "알 수 없음", "is_final": False},
]
DIM_PAYMENT_STATUS = [
    {"payment_status_key": 1, "status_code": "succeeded", "status_name": "성공", "is_success": True},
    {"payment_status_key": 2, "status_code": "failed", "status_name": "실패", "is_success": False},
    {"payment_status_key": 3, "status_code": "pending", "status_name": "대기", "is_success": False},
    {"payment_status_key": -1, "status_code": "unknown", "status_name": "알 수 없음", "is_success": False},
]


def build_dim_date(start=date(2020, 1, 1), end=date(2030, 12, 31)):
    rows, d = [], start
    while d <= end:
        rows.append({"date_key": d.year * 10000 + d.month * 100 + d.day, "calendar_date": d.isoformat(),
                     "year": d.year, "quarter": (d.month - 1) // 3 + 1, "month": d.month,
                     "year_month": d.strftime("%Y-%m"), "day_of_month": d.day,
                     "day_of_week": d.isoweekday(), "day_name": DAY_NAMES[d.weekday()],
                     "is_weekend": d.isoweekday() in (6, 7)})
        d += timedelta(days=1)
    rows.append({"date_key": -1, "calendar_date": "1900-01-01", "year": 1900, "quarter": 1, "month": 1,
                 "year_month": "Unknown", "day_of_month": 1, "day_of_week": 1, "day_name": "Unk", "is_weekend": False})
    return rows


def empty_state():
    """sql/00_setup.sql 직후 상태: 빈 Fact, Unknown 멤버만 있는 고객/상품 차원, 고정 차원."""
    return {
        "seq": {"customer": 0, "product": 0},
        "dim_customer": [{"customer_key": -1, "customer_id": "-1", "customer_name": "Unknown", "email": None,
                          "region": "Unknown", "valid_from": BEGIN_OF_TIME, "valid_to": None, "is_current": True,
                          "hash_diff": None, "load_id": "SEED"}],
        "dim_product": [{"product_key": -1, "product_id": "-1", "product_name": "Unknown", "category": "Unknown",
                         "valid_from": BEGIN_OF_TIME, "valid_to": None, "is_current": True,
                         "hash_diff": None, "load_id": "SEED"}],
        "dim_date": build_dim_date(),
        "dim_order_status": deepcopy(DIM_ORDER_STATUS),
        "dim_payment_status": deepcopy(DIM_PAYMENT_STATUS),
        "fact_sales_line": [], "fact_payment": [], "fact_order_lifecycle": [],
        "pipeline_runs": [], "dq_results": [],
    }


# ---------------------------------------------------------------- 7-1. SCD2 차원
def _scd2(dim, source, key_col, id_col, attrs, seq_name, state, load_id, run_ts):
    current = {r[id_col]: r for r in dim if r["is_current"] and r[key_col] != -1}
    src = {s[id_col]: s for s in source}
    for bid, row in current.items():                 # 바뀐 행은 기존 버전을 닫고
        if bid in src and row["hash_diff"] != src[bid]["hash_diff"]:
            row["valid_to"], row["is_current"] = run_ts, False
    seen = {r[id_col] for r in dim}
    has_current = {r[id_col] for r in dim if r["is_current"]}
    for bid in sorted(src):                           # 현재 버전이 없는 행은 새 버전을 추가
        if bid in has_current:
            continue
        state["seq"][seq_name] += 1
        s = src[bid]
        dim.append({key_col: state["seq"][seq_name], id_col: bid, **{a: s[a] for a in attrs},
                    "valid_from": run_ts if bid in seen else BEGIN_OF_TIME,   # 처음 보는 행은 과거 전체에 유효
                    "valid_to": None, "is_current": True, "hash_diff": s["hash_diff"], "load_id": load_id})


def _version_lookup(dim, key_col, id_col):
    """주문일 시점에 유효했던 버전의 대리키 (point-in-time lookup). 없으면 -1."""
    versions = defaultdict(list)
    for r in dim:
        if r[key_col] != -1:
            versions[r[id_col]].append(r)

    def lookup(business_id, on_date):
        if business_id is None or on_date is None:
            return -1
        ts = f"{on_date} 00:00:00"
        for r in versions.get(business_id, ()):
            if r["valid_from"] <= ts < (r["valid_to"] or END_OF_TIME):
                return r[key_col]
        return -1
    return lookup


def _merge(fact, rows, key, load_id, run_ts):
    """MERGE (업서트) 후, 이번 입력에 없는 기존 행은 소프트 삭제합니다."""
    by_key = {r[key]: r for r in fact}
    for row in rows:
        new = {**row, "is_deleted": False, "load_id": load_id, "updated_at": run_ts}
        if row[key] in by_key:
            by_key[row[key]].update(new)
        else:
            fact.append(new)
    incoming = {r[key] for r in rows}
    for r in fact:
        if not r["is_deleted"] and r[key] not in incoming:
            r.update(is_deleted=True, load_id=load_id, updated_at=run_ts)


def _days_between(d1, ts):
    if ts is None:
        return None
    return (date.fromisoformat(ts[:10]) - date.fromisoformat(d1)).days


def apply_core(state, core_result, load_id, run_ts):
    """STEP 7-1 ~ 7-2. state 를 복사해 갱신한 새 state 를 돌려줍니다."""
    state = deepcopy(state)
    core = core_result["core"]
    _scd2(state["dim_customer"], core["customers"], "customer_key", "customer_id",
          ("customer_name", "email", "region"), "customer", state, load_id, run_ts)
    _scd2(state["dim_product"], core["products"], "product_key", "product_id",
          ("product_name", "category"), "product", state, load_id, run_ts)

    customer_key = _version_lookup(state["dim_customer"], "customer_key", "customer_id")
    product_key = _version_lookup(state["dim_product"], "product_key", "product_id")
    date_keys = {d["calendar_date"]: d["date_key"] for d in state["dim_date"]}
    date_key = lambda d: date_keys.get(d, -1) if d else -1
    order_status = {s["status_code"]: s["order_status_key"] for s in state["dim_order_status"]}
    payment_status = {s["status_code"]: s["payment_status_key"] for s in state["dim_payment_status"]}

    _merge(state["fact_sales_line"], [{
        "order_item_id": p["order_item_id"], "order_id": p["order_id"],
        "customer_key": customer_key(p["customer_id"], p["order_date"]),
        "product_key": product_key(p["product_id"], p["order_date"]),
        "order_date_key": date_key(p["order_date"]), "order_status_key": order_status.get(p["order_status"], -1),
        "order_date": p["order_date"], "quantity": p["quantity"], "unit_price": p["unit_price"],
        "line_amount": p["line_amount"], "is_revenue_eligible": p["is_revenue_eligible"],
        "exclusion_reason": p["exclusion_reason"]} for p in core_result["sales_line_prep"]],
        "order_item_id", load_id, run_ts)

    _merge(state["fact_payment"], [{
        "payment_id": p["payment_id"], "order_id": p["order_id"],
        "customer_key": customer_key(p["customer_id"], p["order_date"]),
        "paid_date_key": date_key(p["paid_date"]), "payment_status_key": payment_status.get(p["payment_status"], -1),
        "paid_at": p["paid_at"], "payment_amount": p["payment_amount"],
        "has_valid_order": p["has_valid_order"]} for p in core_result["payment_prep"]],
        "payment_id", load_id, run_ts)

    _merge(state["fact_order_lifecycle"], [{
        "order_id": q["order_id"], "customer_key": customer_key(q["customer_id"], q["order_date"]),
        "order_date_key": date_key(q["order_date"]),
        "first_success_paid_date_key": date_key(q["first_success_paid_at"][:10] if q["first_success_paid_at"] else None),
        "order_status_key": order_status.get(q["order_status"], -1), "order_date": q["order_date"],
        "first_success_paid_at": q["first_success_paid_at"], "order_amount": q["order_amount"],
        "line_count": q["line_count"], "line_amount_total": q["line_amount_total"],
        "success_payment_count": q["success_payment_count"], "success_payment_amount": q["success_payment_amount"],
        "days_to_first_success_payment": _days_between(q["order_date"], q["first_success_paid_at"]),
        "is_revenue_eligible": q["is_revenue_eligible"], "exclusion_reason": q["exclusion_reason"]}
        for q in core_result["order_quality"]], "order_id", load_id, run_ts)
    return state


# ---------------------------------------------------------------- 7-3. 품질 검사 (17개)
def dq_checks(state):
    """sql/08_mart_dq_checks.sql 과 같은 이름·같은 기준. failures 가 모두 0 이어야 합니다."""
    dc, dp = state["dim_customer"], state["dim_product"]
    sl, pay, life = state["fact_sales_line"], state["fact_payment"], state["fact_order_lifecycle"]
    ck = {r["customer_key"] for r in dc}
    pk = {r["product_key"] for r in dp}
    dk = {r["date_key"] for r in state["dim_date"]}
    osk = {r["order_status_key"] for r in state["dim_order_status"]}
    psk = {r["payment_status_key"] for r in state["dim_payment_status"]}

    def one_current(dim, id_col):
        cur = Counter({r[id_col]: 0 for r in dim})
        for r in dim:
            cur[r[id_col]] += r["is_current"]
        return sum(1 for n in cur.values() if n != 1)

    def dup(rows, key):
        return sum(1 for n in Counter(r[key] for r in rows).values() if n > 1)

    line_sum = defaultdict(int)
    has_line = set()
    for r in sl:
        if not r["is_deleted"]:
            line_sum[r["order_id"]] += r["line_amount"]
            has_line.add(r["order_id"])
    live_rev = [o for o in life if o["is_revenue_eligible"] and not o["is_deleted"]]
    return [
        ("dim_customer_one_current_version", one_current(dc, "customer_id")),
        ("dim_customer_key_unique", dup(dc, "customer_key")),
        ("dim_customer_valid_range", sum(1 for r in dc if r["valid_to"] is not None and r["valid_to"] <= r["valid_from"])),
        ("dim_product_one_current_version", one_current(dp, "product_id")),
        ("dim_product_key_unique", dup(dp, "product_key")),
        ("fact_sales_line_key_unique", dup(sl, "order_item_id")),
        ("fact_sales_line_customer_fk", sum(1 for r in sl if r["customer_key"] not in ck)),
        ("fact_sales_line_product_fk", sum(1 for r in sl if r["product_key"] not in pk)),
        ("fact_sales_line_date_fk", sum(1 for r in sl if r["order_date_key"] not in dk)),
        ("fact_sales_line_status_fk", sum(1 for r in sl if r["order_status_key"] not in osk)),
        ("fact_sales_line_amount_calc", sum(1 for r in sl if r["quantity"] <= 0 or r["unit_price"] < 0
                                            or r["line_amount"] != r["quantity"] * r["unit_price"])),
        ("fact_payment_key_unique", dup(pay, "payment_id")),
        ("fact_payment_status_fk", sum(1 for r in pay if r["payment_status_key"] not in psk)),
        ("fact_order_lifecycle_key_unique", dup(life, "order_id")),
        ("revenue_order_reconciliation", sum(1 for o in live_rev if o["order_amount"] != o["line_amount_total"]
                                             or o["order_amount"] != o["success_payment_amount"]
                                             or o["success_payment_count"] != 1)),
        ("revenue_line_vs_order", sum(1 for o in live_rev if o["order_id"] not in has_line
                                      or line_sum[o["order_id"]] != o["order_amount"])),
        ("revenue_requires_known_keys", sum(1 for r in sl if r["is_revenue_eligible"] and not r["is_deleted"]
                                            and -1 in (r["customer_key"], r["product_key"], r["order_date_key"]))),
    ]


# ---------------------------------------------------------------- 7-4. 게이트
def run_pipeline(state, core_result, load_id, run_ts):
    """7-1 ~ 7-4 를 한 번에 실행합니다.

    노트북과 같게, 품질 검사가 실패해도 자동으로 되돌리지 않고 실행 상태만 FAILED 로 남깁니다.
    (되돌리려면 이전에 저장한 state 파일을 다시 쓰면 됩니다. Snowflake 에서는 Time Travel.)
    """
    new_state = apply_core(state, core_result, load_id, run_ts)
    checks = dq_checks(new_state)
    failed = [name for name, n in checks if n > 0]
    run = {"load_id": load_id, "status": "FAILED" if failed else "SUCCESS", "started_at": run_ts,
           "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           **core_result["summary"], "message": ("DQ failed: " + ", ".join(failed)) if failed else None}
    new_state["pipeline_runs"].append(run)
    new_state["dq_results"] += [{"load_id": load_id, "check_name": n, "failures": f} for n, f in checks]
    return new_state, run, checks


def table_counts(state):
    return {t: len(state[t]) for t in ("dim_customer", "dim_product", "dim_date", "fact_sales_line",
                                       "fact_payment", "fact_order_lifecycle")}
