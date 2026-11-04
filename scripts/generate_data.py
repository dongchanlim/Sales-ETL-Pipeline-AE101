"""AE101 합성 데이터 생성기.

2025-01-01 ~ 2026-10-31 기간의 온라인 쇼핑몰 데이터를 만들고, 약 2~3% 의 품질 문제를 심습니다.
수업용 사례 40행(O001~O010 등)은 각 파일 맨 앞에 그대로 들어갑니다.
같은 seed 로 실행하면 항상 같은 파일이 나옵니다.

사용법:  python scripts/generate_data.py            # data/raw 에 생성
         python scripts/generate_data.py --out /tmp/raw --seed 7
"""
import argparse, csv, json, math, random
from datetime import date, datetime, timedelta
from pathlib import Path

COLS = {
    "customers": ["customer_id", "customer_name", "email", "region"],
    "products": ["product_id", "product_name", "category"],
    "orders": ["order_id", "customer_id", "order_date", "order_status", "order_amount"],
    "order_items": ["order_item_id", "order_id", "product_id", "quantity", "unit_price"],
    "payments": ["payment_id", "order_id", "payment_status", "payment_amount", "paid_at"],
}
REGIONS = [("서울", 19), ("경기", 26), ("인천", 6), ("부산", 6.5), ("대구", 4.5), ("대전", 3),
           ("광주", 3), ("울산", 2), ("세종", 0.8), ("강원", 3), ("충북", 3), ("충남", 4),
           ("전북", 3.4), ("전남", 3.5), ("경북", 5), ("경남", 6.4), ("제주", 1.3)]
SURNAMES = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부황보".replace("황보", "")
GIVEN = ["민준", "서연", "도윤", "서윤", "예준", "지우", "시우", "하은", "주원", "하윤", "지호", "민서",
         "준서", "지유", "건우", "채원", "현우", "수아", "지훈", "지아", "우진", "다은", "선우", "예은",
         "연우", "수빈", "유준", "지민", "정우", "소율", "승우", "예린", "승현", "하린", "시윤", "윤서",
         "준혁", "유나", "은우", "가은", "지환", "서현", "승민", "나은", "민재", "채은", "윤우", "아린",
         "하늘", "바다", "태윤", "보람", "한결", "새봄", "다온", "이안"]
DOMAINS = ["example.com", "example.co.kr", "example.net", "mail.example.org"]
CATEGORIES = {   # 카테고리: (상품 수, 최저가, 최고가, 품목 이름들)
    "문구":     (25, 1000, 25000, ["노트", "펜", "형광펜", "스티커", "다이어리", "파일", "연필", "지우개", "메모지", "필통"]),
    "생활용품": (25, 3000, 60000, ["수건", "칫솔", "세제", "휴지", "수납함", "옷걸이", "슬리퍼", "쿠션"]),
    "주방":     (20, 4000, 90000, ["머그컵", "텀블러", "도마", "프라이팬", "냄비", "수저세트", "밀폐용기"]),
    "전자기기": (20, 9000, 300000, ["무선이어폰", "충전기", "보조배터리", "케이블", "마우스", "키보드", "스피커"]),
    "패션잡화": (20, 5000, 120000, ["양말", "모자", "에코백", "지갑", "벨트", "머플러", "장갑"]),
    "뷰티":     (15, 5000, 70000, ["핸드크림", "립밤", "선크림", "토너", "샴푸", "바디로션"]),
    "식품":     (13, 2000, 40000, ["원두커피", "녹차", "견과류", "그래놀라", "초콜릿", "꿀"]),
    "도서":     (10, 9000, 35000, ["SQL 입문", "파이썬 기초", "데이터 모델링", "통계 101", "엑셀 실무"]),
}
ADJ = ["베이직", "프리미엄", "라이트", "클래식", "에센셜", "데일리", "미니", "플러스", "오리지널", "스마트"]
START, END = date(2025, 1, 1), date(2026, 10, 31)

TEACHING_CASES = {   # 수업용 사례 40행: O001~O010 등 판정이 정해진 사례. 각 파일 맨 앞에 그대로 들어갑니다.
    "customers": [
        ['C001', '김하늘', 'haneul@example.com', '서울'],
        ['C002', '이바다', '', ''],
        ['C001', '김하늘', 'haneul@example.com', '서울'],
    ],
    "products": [
        ['P001', '노트', '문구'],
        ['P002', '펜', '문구'],
    ],
    "orders": [
        ['O001', 'C001', '2026-09-01', 'completed', '30000'],
        ['O002', 'C002', '2026-09-02', 'completed', '15000'],
        ['O003', 'C001', '2026-09-02', 'completed', '10000'],
        ['O004', 'C001', '2026-09-02', 'completed', '5000'],
        ['O005', 'C001', '2026-09-03', 'completed', '10000'],
        ['O006', 'C001', '2026-09-03', 'completed', '10000'],
        ['O007', 'C001', '2026-09-03', 'completed', '10000'],
        ['O007', 'C001', '2026-09-03', 'completed', '12000'],
        ['O008', 'C001', '2026-09-03', 'pending', '10000'],
        ['O009', 'C999', '2026-09-03', 'completed', '10000'],
        ['O010', 'C001', '2026-09-04', 'completed', '10000'],
        ['', 'C001', '2026-09-04', 'completed', '10000'],
        ['O001', 'C001', '2026-09-01', 'completed', '30000'],
    ],
    "order_items": [
        ['I001', 'O001', 'P001', '2', '10000'],
        ['I002', 'O001', 'P002', '2', '5000'],
        ['I003', 'O002', 'P002', '3', '5000'],
        ['I004', 'O003', 'P001', '', '10000'],
        ['I005', 'O004', 'P002', '1', '5000'],
        ['I006', 'O005', 'P001', '1', '10000'],
        ['I007', 'O006', 'P404', '1', '10000'],
        ['I008', 'O007', 'P001', '1', '10000'],
        ['I009', 'O008', 'P001', '1', '10000'],
        ['I010', 'O009', 'P001', '1', '10000'],
        ['I011', 'O404', 'P001', '1', '10000'],
    ],
    "payments": [
        ['PAY001', 'O001', 'failed', '30000', '2026-09-01 09:00:00'],
        ['PAY002', 'O001', 'succeeded', '30000', '2026-09-01 09:01:00'],
        ['PAY003', 'O002', 'succeeded', '15000', '2026-09-02 10:00:00'],
        ['PAY004', 'O003', 'succeeded', '10000', '2026-09-02 10:00:00'],
        ['PAY005', 'O004', 'succeeded', '6000', '2026-09-02 10:00:00'],
        ['PAY006', 'O005', 'succeeded', '10000', '2026-09-03 10:00:00'],
        ['PAY007', 'O005', 'succeeded', '10000', '2026-09-03 10:01:00'],
        ['PAY008', 'O006', 'succeeded', '10000', '2026-09-03 10:00:00'],
        ['PAY009', 'O007', 'succeeded', '10000', '2026-09-03 10:00:00'],
        ['PAY010', 'O009', 'succeeded', '10000', '2026-09-03 10:00:00'],
        ['PAY011', 'O010', 'succeeded', '10000', '2026-09-04 10:00:00'],
    ],
}


def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def round100(x):
    return int(round(x / 100.0)) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--customers", type=int, default=2000)
    ap.add_argument("--orders", type=int, default=30000)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    orig = {t: [dict(zip(COLS[t], r)) for r in TEACHING_CASES[t]] for t in COLS}
    manifest = {}

    # ---------- 1. 고객 ----------
    names = set()
    customers = []
    for i in range(a.customers):
        while True:
            n = rnd.choice(SURNAMES) + rnd.choice(GIVEN)
            if n not in names or len(names) > 2500:
                names.add(n); break
        cid = f"C{10001 + i}"
        email = "" if rnd.random() < 0.05 else f"user{10001 + i}@{rnd.choice(DOMAINS)}"
        region = "" if rnd.random() < 0.03 else rnd.choices([r for r, _ in REGIONS], [w for _, w in REGIONS])[0]
        customers.append({"customer_id": cid, "customer_name": n, "email": email, "region": region})
    manifest["customers_missing_region(→Unknown, 정상)"] = sum(1 for c in customers if not c["region"])
    manifest["customers_missing_email(정상)"] = sum(1 for c in customers if not c["email"])
    activity = {c["customer_id"]: rnd.lognormvariate(0, 1.0) for c in customers}   # 재구매 편차 (파레토형)

    # ---------- 2. 상품 ----------
    products, price = [], {}
    pid = 1001
    for cat, (cnt, lo, hi, items) in CATEGORIES.items():
        for k in range(cnt):
            name = f"{rnd.choice(ADJ)} {items[k % len(items)]}"
            if any(p["product_name"] == name for p in products):
                name = f"{name} {k // len(items) + 2}"
            p = f"P{pid}"; pid += 1
            products.append({"product_id": p, "product_name": name, "category": cat})
            price[p] = round100(math.exp(rnd.uniform(math.log(lo), math.log(hi))))
    popularity = {p["product_id"]: rnd.lognormvariate(0, 0.8) for p in products}

    # ---------- 3. 주문 / 상세 / 결제 (정상 데이터) ----------
    days = (END - START).days + 1
    weights = []
    for d in range(days):
        day = START + timedelta(d)
        w = 0.75 + 0.55 * d / days                     # 성장 추세
        w *= 1.15 if day.weekday() >= 5 else 1.0       # 주말
        w *= {11: 1.35, 12: 1.45, 1: 0.9, 2: 0.85}.get(day.month, 1.0)   # 시즌
        if (day.month, day.day) in {(11, 11), (12, 24), (12, 25)}:
            w *= 2.2                                   # 이벤트일
        weights.append(w)
    total_w = sum(weights)
    cust_ids, cust_w = list(activity), list(activity.values())
    prod_ids, prod_w = list(popularity), list(popularity.values())

    orders, items, pays = [], [], []
    oid, iid, pyid = 100001, 1000001, 1000001
    for d in range(days):
        day = START + timedelta(d)
        n = max(0, int(round(rnd.gauss(a.orders * weights[d] / total_w, 4))))
        for _ in range(n):
            o = f"O{oid}"; oid += 1
            age = (END - day).days
            r = rnd.random()
            status = "pending" if (age < 7 and r < 0.35) or r < 0.02 else ("cancelled" if r < 0.07 else "completed")
            nlines = rnd.choices([1, 2, 3, 4, 5], [35, 30, 20, 10, 5])[0]
            chosen = set()
            while len(chosen) < nlines:
                chosen.add(rnd.choices(prod_ids, prod_w)[0])
            amount = 0
            for p in sorted(chosen):
                q = rnd.choices([1, 2, 3, 4, 5], [70, 20, 7, 2, 1])[0]
                up = price[p] if rnd.random() > 0.12 else round100(price[p] * rnd.uniform(0.8, 0.9))  # 프로모션가
                items.append({"order_item_id": f"I{iid}", "order_id": o, "product_id": p, "quantity": str(q), "unit_price": str(up)})
                iid += 1; amount += q * up
            orders.append({"order_id": o, "customer_id": rnd.choices(cust_ids, cust_w)[0], "order_date": day.isoformat(),
                           "order_status": status, "order_amount": str(amount)})
            t = datetime.combine(day, datetime.min.time()) + timedelta(minutes=rnd.randint(8 * 60, 23 * 60 + 50))
            def pay(st, amt, when):
                nonlocal pyid
                pays.append({"payment_id": f"PAY{pyid}", "order_id": o, "payment_status": st, "payment_amount": str(amt),
                             "paid_at": when.strftime("%Y-%m-%d %H:%M:%S")}); pyid += 1
            if status == "completed":
                if rnd.random() < 0.08:                         # 한 번 실패 후 성공
                    pay("failed", amount, t); t += timedelta(minutes=rnd.randint(1, 30))
                pay("succeeded", amount, t)
            elif status == "cancelled":
                if rnd.random() < 0.5:
                    pay("failed", amount, t)
            else:  # pending
                if rnd.random() < 0.5:
                    pay("pending", amount, t)

    # ---------- 4. 품질 문제 심기 ----------
    by_order_items, by_order_pays = {}, {}
    for it in items: by_order_items.setdefault(it["order_id"], []).append(it)
    for p in pays: by_order_pays.setdefault(p["order_id"], []).append(p)
    completed = [o for o in orders if o["order_status"] == "completed"]
    pool = rnd.sample(completed, 700)          # 주문 단위 문제는 서로 겹치지 않게 뽑음
    take = lambda k: [pool.pop() for _ in range(k)]
    extra = {t: [] for t in COLS}              # 새로 추가되는 행
    removed_items, removed_pays = set(), set()

    def log(key, n): manifest[key] = n

    sel = take(40)                                                   # 주문 키 충돌
    for o in sel: extra["orders"].append({**o, "order_amount": str(int(o["order_amount"]) + 1000)})
    log("orders_key_conflict(KEY_CONFLICT)", len(sel))
    sel = take(60)                                                   # 상세 수량 누락
    for o in sel: by_order_items[o["order_id"]][0]["quantity"] = ""
    log("items_missing_quantity(INVALID_VALUE)", len(sel))
    sel = take(15)                                                   # 상세 수량 0
    for o in sel: by_order_items[o["order_id"]][0]["quantity"] = "0"
    log("items_zero_quantity(INVALID_VALUE)", len(sel))
    sel = take(10)
    for o in sel: o["order_amount"] = "N/A"
    log("orders_invalid_amount(INVALID_VALUE)", len(sel))
    sel = take(10)
    for o in sel: o["order_date"] = o["order_date"][:8] + "32"
    log("orders_invalid_date(INVALID_VALUE)", len(sel))
    sel = take(10)
    for o in sel: o["order_status"] = "shipped"
    log("orders_unknown_status(INVALID_VALUE)", len(sel))
    sel = take(20)
    for o in sel: by_order_pays[o["order_id"]][-1]["paid_at"] = ""
    log("payments_missing_paid_at(INVALID_VALUE)", len(sel))
    sel = take(10)
    for o in sel: by_order_pays[o["order_id"]][-1]["payment_status"] = "refunded"
    log("payments_unknown_status(INVALID_VALUE)", len(sel))
    sel = take(80)                                                   # 없는 고객
    for k, o in enumerate(sel): o["customer_id"] = f"C9{k:04d}"
    log("orders_unknown_customer(INVALID_REFERENCE)", len(sel))
    sel = take(60)                                                   # 없는 상품
    for k, o in enumerate(sel): by_order_items[o["order_id"]][-1]["product_id"] = f"P9{k:03d}"
    log("items_unknown_product(INVALID_REFERENCE)", len(sel))
    sel = take(60)                                                   # 성공 결제 2건
    for o in sel:
        p = by_order_pays[o["order_id"]][-1]
        t = datetime.strptime(p["paid_at"], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=rnd.randint(1, 5))
        extra["payments"].append({**p, "payment_id": f"PAY{pyid}", "paid_at": t.strftime("%Y-%m-%d %H:%M:%S")}); pyid += 1
    log("double_success_payment(SUCCESS_PAYMENT_COUNT)", len(sel))
    sel = take(80)                                                   # 결제 금액 불일치
    for o in sel:
        p = by_order_pays[o["order_id"]][-1]; p["payment_amount"] = str(int(p["payment_amount"]) + rnd.choice([-1000, -500, 500, 1000]))
    log("payment_amount_mismatch(AMOUNT_MISMATCH)", len(sel))
    sel = take(60)                                                   # 주문 금액 불일치
    for o in sel: o["order_amount"] = str(int(o["order_amount"]) + 500)
    log("order_amount_mismatch(AMOUNT_MISMATCH)", len(sel))
    sel = take(30)                                                   # 상세 없음
    for o in sel: removed_items.add(o["order_id"])
    log("completed_without_items(MISSING_ITEMS)", len(sel))
    sel = take(40)                                                   # 결제 없음
    for o in sel: removed_pays.add(o["order_id"])
    log("completed_without_payment(SUCCESS_PAYMENT_COUNT)", len(sel))

    # 새 행: 주문 ID 누락, 주문 없는 상세/결제
    for k in range(15):
        o = rnd.choice(orders)
        extra["orders"].append({**o, "order_id": "", "order_amount": str(rnd.randint(1, 50) * 1000)})
    log("orders_missing_order_id(INVALID_VALUE)", 15)
    for k in range(40):
        extra["order_items"].append({"order_item_id": f"I{iid}", "order_id": f"O9{k:05d}", "product_id": rnd.choice(prod_ids),
                                     "quantity": "1", "unit_price": "10000"}); iid += 1
    log("orphan_items(INVALID_REFERENCE)", 40)
    for k in range(30):
        extra["payments"].append({"payment_id": f"PAY{pyid}", "order_id": f"O8{k:05d}", "payment_status": "succeeded",
                                  "payment_amount": "10000", "paid_at": "2026-05-01 12:00:00"}); pyid += 1
    log("orphan_payments(INVALID_REFERENCE)", 30)

    # 고객 키 충돌 (해당 고객의 주문 전체가 DEPENDENCY_ERROR 로 번짐)
    conflict_c = rnd.sample(customers, 5)
    for c in conflict_c:
        extra["customers"].append({**c, "region": "제주" if c["region"] != "제주" else "서울"})
    log("customers_key_conflict(KEY_CONFLICT)", 5)

    items = [it for it in items if it["order_id"] not in removed_items]
    pays = [p for p in pays if p["order_id"] not in removed_pays]

    base = {"customers": customers, "products": products, "orders": orders, "order_items": items, "payments": pays}
    for t, k in (("customers", 20), ("products", 1), ("orders", 150), ("order_items", 200), ("payments", 100)):
        extra[t] += [dict(r) for r in rnd.sample(base[t] + extra[t], k)]     # 완전 중복 행
        log(f"{t}_exact_duplicate(EXACT_DUPLICATE)", k)
    final = {}
    for t in COLS:
        # 실제 추출 파일처럼 ID 순서로 정렬하되, 추가·중복 행은 임의 위치에 끼워 넣음
        rows = sorted(base[t], key=lambda r: r[COLS[t][0]])
        for r in extra[t]:
            rows.insert(rnd.randint(0, len(rows)), r)
        final[t] = orig[t] + rows           # 수업용 사례 40행은 맨 앞
        write_csv(out / f"{t}.csv", COLS[t], final[t])
    manifest["row_counts"] = {t: len(final[t]) for t in COLS}
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
