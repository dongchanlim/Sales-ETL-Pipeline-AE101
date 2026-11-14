"""AE101 합성 데이터 생성기.

2025-01-01 ~ 2026-10-31 기간의 온라인 쇼핑몰 데이터를 만들고 품질 문제를 심습니다.

실행할 때마다 seed 를 새로 뽑아 다른 데이터셋을 만듭니다. 지역·카테고리·계절성·주문 크기·상태 비율은
정답표 데이터와 같은 모델로 만들고, 카테고리 매출 비중과 평균 단가도 정답표 데이터에 맞춥니다
(popularity_like_reference). 규모(±5%)와 오류 건수(±40%)는 실행마다 달라집니다.

  python scripts/generate_data.py                 # 새 무작위 데이터 → data/raw (seed 는 화면과 answer_key.json 에 남음)
  python scripts/generate_data.py --seed 7        # 같은 seed 면 같은 파일 (재현)
  python scripts/generate_data.py --answer-key    # 정답표 데이터(seed 101)로 되돌리기
  python scripts/generate_data.py --out /tmp/raw  # 다른 폴더에 생성

docs/data_generation.md 3절, 노트북·sql/ 의 기대값 주석, tests/ 는 --answer-key 데이터 기준입니다.
무작위 데이터의 정답은 같은 폴더에 쓰이는 answer_key.json 과 `python -m src.pipeline --dry-run` 보고서로 확인합니다.

심은 문제는 answer_key.json 에 세 종류(kind)로 기록됩니다.
  detected   : 현재 정제 규칙이 잡는 오류. expected 에 error_code / action 이 있습니다.
  undetected : 현재 규칙을 그대로 통과하는 오류 (무작위 모드만). 집계가 조용히 틀어집니다.
  normal     : 오류처럼 보이지만 규칙이 정상 처리하는 값 (선택값 누락, 앞뒤 공백).
수업용 사례 40행(O001~O010 등)은 모든 모드에서 각 파일 맨 앞에 그대로 들어갑니다.
"""
import argparse, calendar, csv, json, math, random
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:                 # 노트북 셀·exec() 로 실행하면 __file__ 이 없음 (Snowflake 노트북 등): 현재 폴더 기준
    ROOT = Path.cwd()
ANSWER_KEY_SEED = 101
REFERENCE_WEIGHTED_PRICE = 26234.9    # 정답표 데이터의 인기도 가중 평균 단가 (weighted_price, seed 101)
REFERENCE_CATEGORY_SHARE = {          # 정답표 데이터의 카테고리별 기대 매출 비중 (인기도 × 단가, seed 101)
    "문구": 0.0485, "생활용품": 0.1216, "주방": 0.1114, "전자기기": 0.4237,
    "패션잡화": 0.0848, "뷰티": 0.0885, "식품": 0.0411, "도서": 0.0803}
TS = "%Y-%m-%d %H:%M:%S"

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
REGION_ALIASES = {   # 다른 시스템·사람이 입력한 지역 표기 (미탐지 오류 region_alias)
    "서울": ["서울특별시", "서울시", "Seoul"], "경기": ["경기도", "Gyeonggi"], "인천": ["인천광역시"],
    "부산": ["부산광역시", "Busan"], "대구": ["대구광역시"], "대전": ["대전광역시"], "광주": ["광주광역시"],
    "울산": ["울산광역시"], "세종": ["세종특별자치시"], "강원": ["강원도", "강원특별자치도"], "충북": ["충청북도"],
    "충남": ["충청남도"], "전북": ["전라북도", "전북특별자치도"], "전남": ["전라남도"], "경북": ["경상북도"],
    "경남": ["경상남도"], "제주": ["제주도", "제주특별자치도"]}
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

# ---------------------------------------------------------------------------
# 심는 문제의 종류 : 이름 → (kind, keys 가 가리키는 파일, (error_code, action) 또는 None, 설명)
# keys 는 그 파일의 업무 키(첫 컬럼)입니다. 연쇄 영향(예: 격리된 고객의 주문)은 keys 에 넣지 않습니다.
# ---------------------------------------------------------------------------
D, U, N = "detected", "undetected", "normal"
QUAR, FLAG = "QUARANTINED", "FLAGGED"
ERROR_TYPES = {
    # 정답표 모드와 무작위 모드 공통
    "customers_exact_duplicate": (D, "customers.csv", ("EXACT_DUPLICATE", "REMOVED"), "같은 행이 두 번 추출됨"),
    "products_exact_duplicate": (D, "products.csv", ("EXACT_DUPLICATE", "REMOVED"), "같은 행이 두 번 추출됨"),
    "orders_exact_duplicate": (D, "orders.csv", ("EXACT_DUPLICATE", "REMOVED"), "같은 행이 두 번 추출됨"),
    "order_items_exact_duplicate": (D, "order_items.csv", ("EXACT_DUPLICATE", "REMOVED"), "같은 행이 두 번 추출됨"),
    "payments_exact_duplicate": (D, "payments.csv", ("EXACT_DUPLICATE", "REMOVED"), "PG 웹훅 재전송 등으로 같은 행이 두 번 추출됨"),
    "orders_key_conflict": (D, "orders.csv", ("KEY_CONFLICT", QUAR), "같은 주문 ID에 금액이 다른 행 (추출 도중 수정)"),
    "customers_key_conflict": (D, "customers.csv", ("KEY_CONFLICT", QUAR), "같은 고객 ID에 지역(무작위 모드는 이메일도)이 다른 행"),
    "orders_missing_order_id": (D, "orders.csv", ("INVALID_VALUE", QUAR), "주문 ID 누락 (keys 는 빈 값)"),
    "orders_invalid_amount": (D, "orders.csv", ("INVALID_VALUE", QUAR), "주문 금액 'N/A'"),
    "orders_invalid_date": (D, "orders.csv", ("INVALID_VALUE", QUAR), "없는 날짜 (32일)"),
    "orders_unknown_status": (D, "orders.csv", ("INVALID_VALUE", QUAR), "알 수 없는 주문 상태 'shipped'"),
    "items_missing_quantity": (D, "order_items.csv", ("INVALID_VALUE", QUAR), "상세 수량 누락"),
    "items_zero_quantity": (D, "order_items.csv", ("INVALID_VALUE", QUAR), "상세 수량 0"),
    "payments_missing_paid_at": (D, "payments.csv", ("INVALID_VALUE", QUAR), "결제 시각 누락"),
    "payments_unknown_status": (D, "payments.csv", ("INVALID_VALUE", QUAR), "알 수 없는 결제 상태 'refunded'"),
    "orders_unknown_customer": (D, "orders.csv", ("INVALID_REFERENCE", FLAG), "고객 마스터에 없는 고객 ID"),
    "items_unknown_product": (D, "order_items.csv", ("INVALID_REFERENCE", FLAG), "상품 마스터에 없는 상품 ID"),
    "orphan_items": (D, "order_items.csv", ("INVALID_REFERENCE", QUAR), "주문이 없는 상세 (무작위 모드는 다음 추출에 들어올 주문의 상세)"),
    "orphan_payments": (D, "payments.csv", ("INVALID_REFERENCE", FLAG), "주문이 없는 결제 (무작위 모드는 다음 추출에 들어올 주문의 결제)"),
    "double_success_payment": (D, "orders.csv", ("SUCCESS_PAYMENT_COUNT", FLAG), "같은 금액의 성공 결제 2건 (이중 결제)"),
    "completed_without_payment": (D, "orders.csv", ("SUCCESS_PAYMENT_COUNT", FLAG), "완료 주문인데 결제 없음"),
    "payment_amount_mismatch": (D, "orders.csv", ("AMOUNT_MISMATCH", FLAG), "성공 결제 금액이 주문 금액과 다름"),
    "order_amount_mismatch": (D, "orders.csv", ("AMOUNT_MISMATCH", FLAG), "주문 금액이 상세 합계와 다름"),
    "completed_without_items": (D, "orders.csv", ("MISSING_ITEMS", FLAG), "완료 주문인데 상세 없음"),
    # 무작위 모드에만 : 현재 규칙이 잡는 현실적인 오류
    "orders_status_label": (D, "orders.csv", ("INVALID_VALUE", QUAR), "다른 시스템의 상태 표기 'Completed', 'COMPLETED', '완료'"),
    "payments_status_label": (D, "payments.csv", ("INVALID_VALUE", QUAR), "PG사 상태 표기 'Succeeded', 'SUCCESS', 'paid', '결제완료'"),
    "orders_amount_format": (D, "orders.csv", ("INVALID_VALUE", QUAR), "금액 서식 '12,000', '12000원', '12000.0'"),
    "items_number_format": (D, "order_items.csv", ("INVALID_VALUE", QUAR), "엑셀 저장으로 바뀐 숫자 '1.0', '4500.00'"),
    "orders_impossible_date": (D, "orders.csv", ("INVALID_VALUE", QUAR), "달력에 없는 날짜 (평년 2월 29일, 4월 31일 등)"),
    "orders_sentinel_amount": (D, "orders.csv", ("INVALID_VALUE", QUAR), "기본값 9999999999999 (입력 상한 초과)"),
    "payments_zero_datetime": (D, "payments.csv", ("INVALID_VALUE", QUAR), "MySQL 0 날짜 '0000-00-00 00:00:00'"),
    "refund_as_negative_payment": (D, "payments.csv", ("INVALID_VALUE", QUAR), "부분 환불을 음수 금액의 성공 결제로 기록"),
    "split_payment": (D, "orders.csv", ("SUCCESS_PAYMENT_COUNT", FLAG), "포인트+카드 분할 결제로 성공 결제 2건 (합계는 맞음)"),
    "customers_missing_name": (D, "customers.csv", ("INVALID_VALUE", QUAR), "고객 이름 누락 (그 고객의 주문은 고객 -1 로 FLAGGED)"),
    "customers_withdrawn": (D, "orders.csv", ("INVALID_REFERENCE", FLAG), "탈퇴 고객이 고객 마스터에서 삭제되고 주문만 남음 (keys 는 그 주문)"),
    "products_discontinued": (D, "order_items.csv", ("INVALID_REFERENCE", FLAG), "단종 상품이 상품 마스터에서 삭제됨 (keys 는 그 상품의 상세)"),
    "products_missing_category": (D, "products.csv", ("INVALID_VALUE", QUAR), "카테고리 누락 (그 상품의 상세는 상품 -1 로 FLAGGED)"),
    "products_key_conflict": (D, "products.csv", ("KEY_CONFLICT", QUAR), "같은 상품 ID에 상품명이 다른 행 (리뉴얼 중 추출)"),
    # 무작위 모드에만 : 현재 규칙을 통과하는 오류 (MART 에 그대로 들어감)
    "region_alias": (U, "customers.csv", None, "지역 표기 변형 '서울특별시', 'Seoul' 등: 지역별 매출이 나뉘고 지역 행 정책에서 빠짐"),
    "email_malformed": (U, "customers.csv", None, "이메일 형식 오류 'a@@b', '@' 누락 등: 형식 검사가 없음"),
    "duplicate_customer_account": (U, "customers.csv", None, "같은 사람이 새 ID로 재가입 (이름·이메일 같음): 고객 수가 부풀려짐"),
    "paid_before_order": (U, "orders.csv", None, "결제 시각이 주문일보다 1~3일 이름: 날짜 순서 검사가 없음"),
    "future_order_date": (U, "orders.csv", None, "추출 기간(~2026-10-31) 이후의 주문일: 미래 매출로 집계됨"),
    "zero_unit_price": (U, "orders.csv", None, "단가 0원 라인 (금액은 맞춰져 있음): 매출이 줄어듦"),
    "unit_price_typo": (U, "orders.csv", None, "단가 10배·100배 입력 실수 (금액은 맞춰져 있음): 매출이 부풀려짐"),
    "cancelled_with_success_payment": (U, "orders.csv", None, "취소 주문에 성공 결제가 남음 (환불 누락): 매출에서는 빠지지만 이슈로 남지 않음"),
    # 정상 처리되는 값
    "customers_missing_email": (N, "customers.csv", None, "이메일 누락 (선택값, NULL 유지)"),
    "customers_missing_region": (N, "customers.csv", None, "지역 누락 (선택값, Unknown 으로 적재)"),
    "padded_values": (N, "orders.csv", None, "상태·참조 ID 앞뒤 공백 (TRIM 으로 정상 처리, 무작위 모드만)"),
}

ANSWER_KEY_COUNTS = {   # 정답표 데이터(seed 101)의 건수. 바꾸면 정답표 숫자가 모두 바뀝니다.
    "orders_key_conflict": 40, "items_missing_quantity": 60, "items_zero_quantity": 15, "orders_invalid_amount": 10,
    "orders_invalid_date": 10, "orders_unknown_status": 10, "payments_missing_paid_at": 20, "payments_unknown_status": 10,
    "orders_unknown_customer": 80, "items_unknown_product": 60, "double_success_payment": 60,
    "payment_amount_mismatch": 80, "order_amount_mismatch": 60, "completed_without_items": 30,
    "completed_without_payment": 40, "orders_missing_order_id": 15, "orphan_items": 40, "orphan_payments": 30,
    "customers_key_conflict": 5, "customers_exact_duplicate": 20, "products_exact_duplicate": 1,
    "orders_exact_duplicate": 150, "order_items_exact_duplicate": 200, "payments_exact_duplicate": 100,
}
RANDOM_ONLY_COUNTS = {   # 무작위 모드에만 더하는 문제의 기준 건수 (고객 2천·주문 3만 기준)
    "orders_status_label": 12, "payments_status_label": 10, "orders_amount_format": 12, "items_number_format": 10,
    "orders_impossible_date": 8, "orders_sentinel_amount": 5, "payments_zero_datetime": 8,
    "refund_as_negative_payment": 8, "split_payment": 20, "customers_missing_name": 4, "customers_withdrawn": 3,
    "region_alias": 40, "email_malformed": 20, "duplicate_customer_account": 8, "paid_before_order": 15,
    "future_order_date": 10, "zero_unit_price": 10, "unit_price_typo": 6, "cancelled_with_success_payment": 12,
    "padded_values": 60,
}
CUSTOMER_LEVEL = ("customers_key_conflict", "customers_missing_name", "customers_withdrawn", "region_alias",
                  "email_malformed", "duplicate_customer_account", "customers_exact_duplicate")
PRODUCT_LEVEL = ("products_discontinued", "products_missing_category", "products_key_conflict")
POOL_TYPES = (   # 서로 겹치지 않는 완료 주문을 하나씩 쓰는 문제 (한 주문에 문제 하나)
    "orders_key_conflict", "items_missing_quantity", "items_zero_quantity", "orders_invalid_amount", "orders_invalid_date",
    "orders_unknown_status", "payments_missing_paid_at", "payments_unknown_status", "orders_unknown_customer",
    "items_unknown_product", "double_success_payment", "payment_amount_mismatch", "order_amount_mismatch",
    "completed_without_items", "completed_without_payment", "orders_status_label", "payments_status_label",
    "orders_amount_format", "items_number_format", "orders_impossible_date", "orders_sentinel_amount",
    "payments_zero_datetime", "refund_as_negative_payment", "split_payment", "paid_before_order", "future_order_date",
    "zero_unit_price", "unit_price_typo", "cancelled_with_success_payment", "duplicate_customer_account", "padded_values")


def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def round100(x):
    return int(round(x / 100.0)) * 100


def random_counts(rnd, n_customers, n_orders):
    """무작위 모드의 문제 건수: 기준 건수 × 규모 × (0.6 ~ 1.4). 상품 단위 문제는 0~1개."""
    counts = {}
    for name, base in {**ANSWER_KEY_COUNTS, **RANDOM_ONLY_COUNTS}.items():
        scale = n_customers / 2000 if name in CUSTOMER_LEVEL else n_orders / 30000
        counts[name] = max(1, round(base * scale * rnd.uniform(0.6, 1.4)))
    counts["products_exact_duplicate"] = 1
    counts["products_discontinued"] = rnd.choice([0, 1, 1])
    counts["products_missing_category"] = rnd.choice([0, 1])
    counts["products_key_conflict"] = rnd.choice([0, 1])
    return counts


class AnswerKey:
    """심은 문제를 기록하고 answer_key.json 형태로 만듭니다."""

    def __init__(self):
        self.keys, self.related = {}, {}

    def add(self, name, keys, related=None):
        assert name in ERROR_TYPES, name
        self.keys.setdefault(name, []).extend(keys)
        if related is not None:
            self.related.setdefault(name, []).extend(related)

    def to_dict(self, meta):
        types = []
        for name, (kind, file, expected, description) in ERROR_TYPES.items():
            if name not in self.keys:
                continue
            entry = {"name": name, "kind": kind, "file": file,
                     "expected": dict(zip(("error_code", "action"), expected)) if expected else None,
                     "description": description, "count": len(self.keys[name]), "keys": self.keys[name]}
            if name in self.related:
                entry["related"] = self.related[name]
            types.append(entry)
        return {**meta, "types": types}


# ---------------------------------------------------------------------------
# 1. 정상 데이터 : 고객 · 상품 · 주문 / 상세 / 결제
# ---------------------------------------------------------------------------
def weighted_price(price, popularity):
    """인기도로 가중한 평균 단가. 평균 주문 금액을 좌우합니다."""
    return sum(price[p] * w for p, w in popularity.items()) / sum(popularity.values())


def popularity_like_reference(rnd, products, price, popularity):
    """상품이 151개뿐이라 인기도를 그냥 뽑으면 평균 주문 금액이 ±40%, 카테고리 비중이 2배까지 흔들립니다.
    무작위 모드는 (1) 카테고리별 기대 매출 비중을 정답표 데이터와 같게 맞추고
    (2) 인기도 가중 평균 단가가 정답표 데이터와 ±5% 안에 들 때까지 인기도를 다시 뽑습니다 (최대 200번, 못 맞추면 가장 가까운 것).
    카테고리 안에서 어느 상품이 잘 팔리는지는 실행마다 다릅니다."""
    category = {p["product_id"]: p["category"] for p in products}
    best, best_gap = None, None
    for _ in range(200):
        revenue_weight = {}
        for p, w in popularity.items():
            revenue_weight[category[p]] = revenue_weight.get(category[p], 0) + w * price[p]
        scaled = {p: w * REFERENCE_CATEGORY_SHARE[category[p]] / revenue_weight[category[p]] for p, w in popularity.items()}
        gap = abs(weighted_price(price, scaled) / REFERENCE_WEIGHTED_PRICE - 1)
        if best is None or gap < best_gap:
            best, best_gap = scaled, gap
        if gap <= 0.05:
            break
        popularity = {p["product_id"]: rnd.lognormvariate(0, 0.8) for p in products}
    return best


def make_base(rnd, n_customers, n_orders, match_reference=False):
    names, customers = set(), []
    for i in range(n_customers):
        while True:
            n = rnd.choice(SURNAMES) + rnd.choice(GIVEN)
            if n not in names or len(names) > 2500:
                names.add(n); break
        cid = f"C{10001 + i}"
        email = "" if rnd.random() < 0.05 else f"user{10001 + i}@{rnd.choice(DOMAINS)}"
        region = "" if rnd.random() < 0.03 else rnd.choices([r for r, _ in REGIONS], [w for _, w in REGIONS])[0]
        customers.append({"customer_id": cid, "customer_name": n, "email": email, "region": region})
    activity = {c["customer_id"]: rnd.lognormvariate(0, 1.0) for c in customers}   # 재구매 편차 (파레토형)

    products, price = [], {}
    pid = 1001
    for cat, (cnt, lo, hi, kinds) in CATEGORIES.items():
        for k in range(cnt):
            name = f"{rnd.choice(ADJ)} {kinds[k % len(kinds)]}"
            if any(p["product_name"] == name for p in products):
                name = f"{name} {k // len(kinds) + 2}"
            p = f"P{pid}"; pid += 1
            products.append({"product_id": p, "product_name": name, "category": cat})
            price[p] = round100(math.exp(rnd.uniform(math.log(lo), math.log(hi))))
    popularity = {p["product_id"]: rnd.lognormvariate(0, 0.8) for p in products}
    if match_reference:
        popularity = popularity_like_reference(rnd, products, price, popularity)

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
        n = max(0, int(round(rnd.gauss(n_orders * weights[d] / total_w, 4))))
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
            attempts = []
            if status == "completed":
                if rnd.random() < 0.08:                         # 한 번 실패 후 성공
                    attempts.append(("failed", t)); t += timedelta(minutes=rnd.randint(1, 30))
                attempts.append(("succeeded", t))
            elif status == "cancelled":
                if rnd.random() < 0.5:
                    attempts.append(("failed", t))
            else:  # pending
                if rnd.random() < 0.5:
                    attempts.append(("pending", t))
            for st, when in attempts:
                pays.append({"payment_id": f"PAY{pyid}", "order_id": o, "payment_status": st, "payment_amount": str(amount),
                             "paid_at": when.strftime(TS)}); pyid += 1
    return {"customers": customers, "products": products, "price": price, "popularity": popularity,
            "prod_ids": prod_ids, "orders": orders, "items": items, "pays": pays,
            "next": {"order": oid, "item": iid, "pay": pyid}}


# ---------------------------------------------------------------------------
# 2. 품질 문제 심기
#    정답표 모드는 예전 생성기와 같은 순서로 난수를 써서 같은 파일을 만듭니다.
#    무작위 모드에만 있는 단계는 `if realistic:` 안에 있어 정답표 모드의 난수 순서를 바꾸지 않습니다.
# ---------------------------------------------------------------------------
def plant_problems(rnd, base, counts, key, realistic):
    customers, products, orders, items, pays = (base[k] for k in ("customers", "products", "orders", "items", "pays"))
    nxt, price, prod_ids = base["next"], base["price"], base["prod_ids"]
    c = lambda name: counts.get(name, 0)
    ids = lambda rows, col="order_id": [r[col] for r in rows]
    by_order_items, by_order_pays = {}, {}
    for it in items: by_order_items.setdefault(it["order_id"], []).append(it)
    for p in pays: by_order_pays.setdefault(p["order_id"], []).append(p)
    extra = {t: [] for t in COLS}              # 새로 추가되는 행
    removed_items, removed_pays = set(), set()

    def new_payment(**row):
        row = {"payment_id": f"PAY{nxt['pay']}", **row}; nxt["pay"] += 1
        return row

    def shift_payments(oid, delta):
        for p in by_order_pays.get(oid, []):
            p["paid_at"] = (datetime.strptime(p["paid_at"], TS) + delta).strftime(TS)

    def resync_amount(o):                      # 상세를 고친 뒤 주문·결제 금액을 다시 맞춤 (대사는 통과)
        amount = sum(int(i["quantity"]) * int(i["unit_price"]) for i in by_order_items[o["order_id"]])
        o["order_amount"] = str(amount)
        for p in by_order_pays[o["order_id"]]:
            p["payment_amount"] = str(amount)

    # 2-1. 고객·상품 단위 대상 (무작위 모드). 이 고객·상품의 주문은 아래 주문 풀에서 뺍니다.
    tc, tp, affected_c, affected_p = {}, {}, set(), set()
    if realistic:
        shuffled = rnd.sample(customers, len(customers))
        for name, cond in (("customers_key_conflict", None), ("customers_missing_name", None), ("customers_withdrawn", None),
                           ("region_alias", lambda x: x["region"] in REGION_ALIASES), ("email_malformed", lambda x: x["email"]),
                           ("duplicate_customer_account", None)):
            tc[name] = [x for x in shuffled if cond is None or cond(x)][:c(name)]
            shuffled = [x for x in shuffled if x not in tc[name]]
        affected_c = {x["customer_id"] for n in ("customers_key_conflict", "customers_missing_name", "customers_withdrawn")
                      for x in tc[n]}
        rare = sorted(products, key=lambda p: base["popularity"][p["product_id"]])[:30]   # 판매가 적은 상품
        rare = rnd.sample(rare, len(rare))
        for name in PRODUCT_LEVEL:
            tp[name], rare = rare[:c(name)], rare[c(name):]
        affected_p = {p["product_id"] for n in PRODUCT_LEVEL for p in tp[n]}

    # 2-2. 주문 단위 문제는 서로 겹치지 않는 완료 주문에 하나씩 심습니다.
    completed = [o for o in orders if o["order_status"] == "completed"]
    if realistic:
        eligible = [o for o in completed if o["customer_id"] not in affected_c
                    and not any(i["product_id"] in affected_p for i in by_order_items[o["order_id"]])]
        pool = rnd.sample(eligible, sum(c(n) for n in POOL_TYPES) + 60)
    else:
        pool = rnd.sample(completed, 700)

    def take(k, cond=None):
        out, i = [], len(pool) - 1
        while len(out) < k and i >= 0:
            if cond is None or cond(pool[i]):
                out.append(pool.pop(i))
            i -= 1
        return out

    sel = take(c("orders_key_conflict"))
    for o in sel: extra["orders"].append({**o, "order_amount": str(int(o["order_amount"]) + 1000)})
    key.add("orders_key_conflict", ids(sel))
    sel = take(c("items_missing_quantity"))
    for o in sel: by_order_items[o["order_id"]][0]["quantity"] = ""
    key.add("items_missing_quantity", [by_order_items[o["order_id"]][0]["order_item_id"] for o in sel])
    sel = take(c("items_zero_quantity"))
    for o in sel: by_order_items[o["order_id"]][0]["quantity"] = "0"
    key.add("items_zero_quantity", [by_order_items[o["order_id"]][0]["order_item_id"] for o in sel])
    sel = take(c("orders_invalid_amount"))
    for o in sel: o["order_amount"] = "N/A"
    key.add("orders_invalid_amount", ids(sel))
    sel = take(c("orders_invalid_date"))
    for o in sel: o["order_date"] = o["order_date"][:8] + "32"
    key.add("orders_invalid_date", ids(sel))
    sel = take(c("orders_unknown_status"))
    for o in sel: o["order_status"] = "shipped"
    key.add("orders_unknown_status", ids(sel))
    sel = take(c("payments_missing_paid_at"))
    for o in sel: by_order_pays[o["order_id"]][-1]["paid_at"] = ""
    key.add("payments_missing_paid_at", [by_order_pays[o["order_id"]][-1]["payment_id"] for o in sel])
    sel = take(c("payments_unknown_status"))
    for o in sel: by_order_pays[o["order_id"]][-1]["payment_status"] = "refunded"
    key.add("payments_unknown_status", [by_order_pays[o["order_id"]][-1]["payment_id"] for o in sel])
    sel = take(c("orders_unknown_customer"))                         # 없는 고객
    for k, o in enumerate(sel): o["customer_id"] = f"C9{k:04d}"
    key.add("orders_unknown_customer", ids(sel))
    sel = take(c("items_unknown_product"))                           # 없는 상품
    for k, o in enumerate(sel): by_order_items[o["order_id"]][-1]["product_id"] = f"P9{k:03d}"
    key.add("items_unknown_product", [by_order_items[o["order_id"]][-1]["order_item_id"] for o in sel])
    sel = take(c("double_success_payment"))                          # 성공 결제 2건
    for o in sel:
        p = by_order_pays[o["order_id"]][-1]
        t = datetime.strptime(p["paid_at"], TS) + timedelta(minutes=rnd.randint(1, 5))
        extra["payments"].append({**p, "payment_id": f"PAY{nxt['pay']}", "paid_at": t.strftime(TS)}); nxt["pay"] += 1
    key.add("double_success_payment", ids(sel))
    sel = take(c("payment_amount_mismatch"))                         # 결제 금액 불일치
    for o in sel:
        p = by_order_pays[o["order_id"]][-1]; p["payment_amount"] = str(int(p["payment_amount"]) + rnd.choice([-1000, -500, 500, 1000]))
    key.add("payment_amount_mismatch", ids(sel))
    sel = take(c("order_amount_mismatch"))                           # 주문 금액 불일치
    for o in sel: o["order_amount"] = str(int(o["order_amount"]) + 500)
    key.add("order_amount_mismatch", ids(sel))
    sel = take(c("completed_without_items"))                         # 상세 없음
    for o in sel: removed_items.add(o["order_id"])
    key.add("completed_without_items", ids(sel))
    sel = take(c("completed_without_payment"))                       # 결제 없음
    for o in sel: removed_pays.add(o["order_id"])
    key.add("completed_without_payment", ids(sel))

    if realistic:
        # 현재 규칙이 잡는 현실적인 오류
        sel = take(c("orders_status_label"))
        for o in sel: o["order_status"] = rnd.choice(["Completed", "COMPLETED", "완료"])
        key.add("orders_status_label", ids(sel))
        sel = take(c("payments_status_label"))
        for o in sel: by_order_pays[o["order_id"]][-1]["payment_status"] = rnd.choice(["Succeeded", "SUCCESS", "paid", "결제완료"])
        key.add("payments_status_label", [by_order_pays[o["order_id"]][-1]["payment_id"] for o in sel])
        sel = take(c("orders_amount_format"))
        for o in sel:
            v = int(o["order_amount"])
            text = rnd.choice([f"{v:,}", f"{v}원", f"{v}.0"])
            o["order_amount"] = text if not text.isdigit() else f"{v}원"     # 1,000 미만이면 콤마가 붙지 않음
        key.add("orders_amount_format", ids(sel))
        sel = take(c("items_number_format"))
        for o in sel:
            it = by_order_items[o["order_id"]][0]
            if rnd.random() < 0.5:
                it["quantity"] += ".0"
            else:
                it["unit_price"] += ".00"
        key.add("items_number_format", [by_order_items[o["order_id"]][0]["order_item_id"] for o in sel])
        sel = take(c("orders_impossible_date"))
        for o in sel:
            y, m = int(o["order_date"][:4]), int(o["order_date"][5:7])
            o["order_date"] = f"{y}-{m:02d}-{calendar.monthrange(y, m)[1] + 1:02d}"
        key.add("orders_impossible_date", ids(sel))
        sel = take(c("orders_sentinel_amount"))
        for o in sel: o["order_amount"] = "9999999999999"
        key.add("orders_sentinel_amount", ids(sel))
        sel = take(c("payments_zero_datetime"))
        for o in sel: by_order_pays[o["order_id"]][-1]["paid_at"] = "0000-00-00 00:00:00"
        key.add("payments_zero_datetime", [by_order_pays[o["order_id"]][-1]["payment_id"] for o in sel])
        sel, refunds = take(c("refund_as_negative_payment")), []
        for o in sel:
            p = by_order_pays[o["order_id"]][-1]
            refund = max(100, round100(int(p["payment_amount"]) * rnd.uniform(0.1, 0.5)))
            when = datetime.strptime(p["paid_at"], TS) + timedelta(days=rnd.randint(1, 7), minutes=rnd.randint(0, 600))
            refunds.append(new_payment(order_id=o["order_id"], payment_status="succeeded",
                                       payment_amount=f"-{refund}", paid_at=when.strftime(TS)))
        extra["payments"] += refunds
        key.add("refund_as_negative_payment", ids(refunds, "payment_id"))
        sel = take(c("split_payment"), lambda o: int(o["order_amount"]) >= 1000)
        for o in sel:
            p, total = by_order_pays[o["order_id"]][-1], int(o["order_amount"])
            first = min(total - 100, max(100, round100(total * rnd.uniform(0.2, 0.8))))
            p["payment_amount"] = str(first)
            when = datetime.strptime(p["paid_at"], TS) + timedelta(seconds=rnd.randint(1, 90))
            extra["payments"].append(new_payment(order_id=o["order_id"], payment_status="succeeded",
                                                 payment_amount=str(total - first), paid_at=when.strftime(TS)))
        key.add("split_payment", ids(sel))

        # 현재 규칙을 통과하는 오류 (금액 대사는 맞도록 만들어 매출에 그대로 들어감)
        sel = take(c("paid_before_order"))
        for o in sel: shift_payments(o["order_id"], -timedelta(days=rnd.randint(1, 3)))
        key.add("paid_before_order", ids(sel))
        sel = take(c("future_order_date"))
        for o in sel:
            old = date.fromisoformat(o["order_date"])
            new = END + timedelta(days=rnd.randint(1, 45))
            o["order_date"] = new.isoformat()
            shift_payments(o["order_id"], new - old)
        key.add("future_order_date", ids(sel))
        sel = take(c("zero_unit_price"), lambda o: len(by_order_items[o["order_id"]]) >= 2)
        for o in sel:
            rnd.choice(by_order_items[o["order_id"]])["unit_price"] = "0"
            resync_amount(o)
        key.add("zero_unit_price", ids(sel))
        sel = take(c("unit_price_typo"))
        for o in sel:
            it = rnd.choice(by_order_items[o["order_id"]])
            it["unit_price"] = str(int(it["unit_price"]) * rnd.choice([10, 100]))
            resync_amount(o)
        key.add("unit_price_typo", ids(sel))
        sel = take(c("cancelled_with_success_payment"))
        for o in sel: o["order_status"] = "cancelled"
        key.add("cancelled_with_success_payment", ids(sel))
        first_new = 10001 + len(customers)                           # 같은 사람이 새 ID 로 재가입
        accounts = [{**src, "customer_id": f"C{first_new + k}"} for k, src in enumerate(tc["duplicate_customer_account"])]
        sel = take(len(accounts))
        for acc, o in zip(accounts, sel): o["customer_id"] = acc["customer_id"]
        customers += accounts
        key.add("duplicate_customer_account", ids(accounts, "customer_id"), related=ids(sel))

        # 정상 처리되는 값: 앞뒤 공백
        sel = take(c("padded_values"))
        for o in sel:
            where = rnd.randrange(3)
            if where == 0:
                o["order_status"] = rnd.choice([" completed", "completed "])
            elif where == 1:
                by_order_pays[o["order_id"]][-1]["order_id"] += " "
            else:
                by_order_items[o["order_id"]][0]["product_id"] = " " + by_order_items[o["order_id"]][0]["product_id"]
        key.add("padded_values", ids(sel))

    # 2-3. 새 행: 주문 ID 누락, 주문 없는 상세/결제
    for _ in range(c("orders_missing_order_id")):
        o = rnd.choice(orders)
        extra["orders"].append({**o, "order_id": "", "order_amount": str(rnd.randint(1, 50) * 1000)})
    key.add("orders_missing_order_id", [None] * c("orders_missing_order_id"))
    orphan_items = []
    for k in range(c("orphan_items")):
        p = rnd.choice(prod_ids)
        if realistic:   # 주문 헤더가 다음 추출에 들어올 주문 (지연 도착)
            q = rnd.choices([1, 2, 3, 4, 5], [70, 20, 7, 2, 1])[0]
            row = {"order_id": f"O{nxt['order'] + k}", "product_id": p, "quantity": str(q), "unit_price": str(price[p])}
        else:
            row = {"order_id": f"O9{k:05d}", "product_id": p, "quantity": "1", "unit_price": "10000"}
        orphan_items.append({"order_item_id": f"I{nxt['item']}", **row}); nxt["item"] += 1
    extra["order_items"] += orphan_items
    key.add("orphan_items", ids(orphan_items, "order_item_id"))
    orphan_pays = []
    for k in range(c("orphan_payments")):
        if realistic:
            when = datetime.combine(END, datetime.min.time()) + timedelta(minutes=rnd.randint(8 * 60, 23 * 60 + 50))
            row = {"order_id": f"O{nxt['order'] + c('orphan_items') + k}", "payment_status": "succeeded",
                   "payment_amount": str(round100(rnd.uniform(5000, 150000))), "paid_at": when.strftime(TS)}
        else:
            row = {"order_id": f"O8{k:05d}", "payment_status": "succeeded", "payment_amount": "10000",
                   "paid_at": "2026-05-01 12:00:00"}
        orphan_pays.append(new_payment(**row))
    extra["payments"] += orphan_pays
    key.add("orphan_payments", ids(orphan_pays, "payment_id"))

    # 2-4. 고객·상품 마스터 문제 (고객 키 충돌은 그 고객의 주문 전체를 DEPENDENCY_ERROR 로 번지게 함)
    conflict = tc["customers_key_conflict"] if realistic else rnd.sample(customers, c("customers_key_conflict"))
    for x in conflict:
        if realistic and x["email"] and rnd.random() < 0.5:
            extra["customers"].append({**x, "email": x["email"].replace("@", ".new@")})
        else:
            extra["customers"].append({**x, "region": "제주" if x["region"] != "제주" else "서울"})
    key.add("customers_key_conflict", ids(conflict, "customer_id"))
    if realistic:
        for x in tc["customers_missing_name"]: x["customer_name"] = ""
        key.add("customers_missing_name", ids(tc["customers_missing_name"], "customer_id"))
        for x in tc["region_alias"]: x["region"] = rnd.choice(REGION_ALIASES[x["region"]])
        key.add("region_alias", ids(tc["region_alias"], "customer_id"))
        for x in tc["email_malformed"]:
            local, domain = x["email"].split("@")
            x["email"] = rnd.choice([f"{local}@@{domain}", f"{local}{domain}", f"{local}@", f"{local}@{domain.split('.')[0]}"])
        key.add("email_malformed", ids(tc["email_malformed"], "customer_id"))
        gone = set(ids(tc["customers_withdrawn"], "customer_id"))
        customers[:] = [x for x in customers if x["customer_id"] not in gone]
        key.add("customers_withdrawn", [o["order_id"] for o in orders if o["customer_id"] in gone], related=sorted(gone))
        gone = set(ids(tp["products_discontinued"], "product_id"))
        products[:] = [p for p in products if p["product_id"] not in gone]
        key.add("products_discontinued", [i["order_item_id"] for i in items if i["product_id"] in gone
                                          and i["order_id"] not in removed_items], related=sorted(gone))
        for p in tp["products_missing_category"]: p["category"] = ""
        key.add("products_missing_category", ids(tp["products_missing_category"], "product_id"))
        for p in tp["products_key_conflict"]:
            extra["products"].append({**p, "product_name": p["product_name"] + " (리뉴얼)"})
        key.add("products_key_conflict", ids(tp["products_key_conflict"], "product_id"))

    items = [it for it in items if it["order_id"] not in removed_items]
    pays = [p for p in pays if p["order_id"] not in removed_pays]

    # 2-5. 완전 중복 행, 그리고 실제 추출 파일처럼 ID 순서로 정렬하되 추가·중복 행은 임의 위치에 끼워 넣음
    base_rows = {"customers": customers, "products": products, "orders": orders, "order_items": items, "payments": pays}
    for t in COLS:
        dup = [dict(r) for r in rnd.sample(base_rows[t] + extra[t], c(f"{t}_exact_duplicate"))]
        extra[t] += dup
        key.add(f"{t}_exact_duplicate", [r[COLS[t][0]] or None for r in dup])
    flagged_c = set(ids(conflict, "customer_id")) | set(ids(tc.get("customers_missing_name", []), "customer_id"))
    key.add("customers_missing_email", [x["customer_id"] for x in customers if not x["email"] and x["customer_id"] not in flagged_c])
    key.add("customers_missing_region", [x["customer_id"] for x in customers if not x["region"] and x["customer_id"] not in flagged_c])
    final = {}
    for t in COLS:
        rows = sorted(base_rows[t], key=lambda r: r[COLS[t][0]])
        for r in extra[t]:
            rows.insert(rnd.randint(0, len(rows)), r)
        final[t] = [dict(zip(COLS[t], r)) for r in TEACHING_CASES[t]] + rows    # 수업용 사례 40행은 맨 앞
    return final


# ---------------------------------------------------------------------------
# 3. 실행
# ---------------------------------------------------------------------------
def generate(out, seed=None, answer_key=False, customers=2000, orders=30000):
    """데이터셋 하나를 out 폴더에 CSV 5개와 answer_key.json 으로 쓰고, 정답표(dict)를 돌려줍니다."""
    if answer_key:
        seed, customers, orders = ANSWER_KEY_SEED, 2000, 30000
    elif seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    rnd = random.Random(seed)
    if not answer_key:                         # 규모도 실행마다 조금씩 다름
        customers = round(customers * rnd.uniform(0.95, 1.05))
        orders = round(orders * rnd.uniform(0.95, 1.05))
    base = make_base(rnd, customers, orders, match_reference=not answer_key)
    counts = ANSWER_KEY_COUNTS if answer_key else random_counts(rnd, customers, orders)
    key = AnswerKey()
    final = plant_problems(rnd, base, counts, key, realistic=not answer_key)

    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for t in COLS:
        write_csv(out / f"{t}.csv", COLS[t], final[t])
    result = key.to_dict({
        "generator": "scripts/generate_data.py", "mode": "answer-key" if answer_key else "random", "seed": seed,
        "period": {"start": START.isoformat(), "end": END.isoformat()},
        "volume": {"customers": customers, "orders_target": orders},
        "row_counts": {t: len(final[t]) for t in COLS}, "teaching_case_rows": sum(map(len, TEACHING_CASES.values())),
    })
    with open(out / "answer_key.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return result


def summary(result):
    by_kind = {}
    for t in result["types"]:
        by_kind.setdefault(t["kind"], {})[t["name"]] = t["count"]
    return {**{k: result[k] for k in ("mode", "seed", "row_counts")}, **by_kind}


def main(argv=None):
    """argv=None 이면 명령줄 인자를 읽습니다. 노트북 셀에서는 sys.argv 에 커널 인자가 들어 있으므로
    인자를 읽지 않고 기본값으로 실행합니다. 옵션은 main(["--seed", "7", "--out", "/tmp/raw"]) 처럼 넘기세요."""
    if argv is None and "__file__" not in globals():
        argv = []
    ap = argparse.ArgumentParser(description="AE101 합성 데이터 생성기 (기본: 실행마다 새 무작위 데이터)")
    ap.add_argument("--out", type=Path, default=ROOT / "data/raw", help="CSV 와 answer_key.json 을 쓸 폴더")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--seed", type=int, help="같은 데이터를 다시 만들 때 (answer_key.json 의 seed)")
    mode.add_argument("--answer-key", action="store_true", help="정답표 데이터(seed 101) 생성. 문서·테스트의 기대값 기준")
    ap.add_argument("--customers", type=int, default=2000, help="고객 수 기준값 (무작위 모드는 ±5%%)")
    ap.add_argument("--orders", type=int, default=30000, help="주문 수 기준값 (무작위 모드는 ±5%%)")
    a = ap.parse_args(argv)
    if a.answer_key and (a.customers, a.orders) != (2000, 30000):
        ap.error("--answer-key 는 규모를 바꿀 수 없습니다 (정답표 숫자가 달라집니다)")
    result = generate(a.out, seed=a.seed, answer_key=a.answer_key, customers=a.customers, orders=a.orders)
    print(json.dumps(summary(result), ensure_ascii=False, indent=2))
    print(f"정답표: {Path(a.out) / 'answer_key.json'}")


if __name__ == "__main__":
    main()
