# 데이터 사전

UTF-8 CSV, 한국 시간 기준, KRW 정수이며 모든 값은 교육용 합성 데이터입니다.

## 원본 파일 (`data/raw`)

| 파일 | 한 행의 의미 | 키 | 컬럼 |
|---|---|---|---|
| customers.csv | 고객 | customer_id | customer_name: 이름, email: 선택 이메일(PII), region: 선택 지역 |
| products.csv | 상품 | product_id | product_name: 이름, category: 분류 |
| orders.csv | 주문 | order_id | customer_id: 고객, order_date: 주문일, order_status: 상태, order_amount: 주문 금액 |
| order_items.csv | 주문 상품 항목 | order_item_id | order_id: 주문, product_id: 상품, quantity: 수량, unit_price: 거래 시점 단가 |
| payments.csv | 결제 시도 | payment_id | order_id: 주문, payment_status: 결제 상태, payment_amount: 시도 금액, paid_at: 시도 일시 |

`paid_at`은 실패 시도에서도 필수인 **결제 시도 일시**입니다. 성공 시 정산 일시를 뜻하지 않습니다.

| 허용값 | 정의 |
|---|---|
| order_status | completed / pending / cancelled (완료 / 대기 / 취소) |
| payment_status | succeeded / failed / pending (성공 / 실패 / 대기) |
| order_date | `YYYY-MM-DD` |
| paid_at | `YYYY-MM-DD HH:MM:SS`, 시간대 표기 없음, KST로 해석 |
| 금액·수량 | 0 이상 정수 (수량은 1 이상), 입력 상한 10^12 |

선택값은 고객 email·region뿐입니다. 나머지 누락은 오류입니다.

## 계층별 공통 컬럼

| 컬럼 | 위치 | 의미 |
|---|---|---|
| load_id | RAW, AUDIT, MART | 실행(배치) ID. `CORE.RUN_CTX`에서 발급 |
| loaded_at | RAW | 배치 적재 시각 (= run_ts). 최근 배치 판별 기준 |
| src_file, src_row | RAW, CORE | 원본 파일명과 행 번호 (헤더 = 1행). 이슈 위치 추적용 |
| dq_status | CORE `*_CHK` | DUPLICATE / CONFLICT / INVALID / OK |
| action | AUDIT.DATA_ISSUES | REMOVED / QUARANTINED / FLAGGED |
| hash_diff | CORE, MART 차원 | 속성 값 MD5. SCD2 변경 감지 |
| valid_from, valid_to, is_current | MART 차원 | SCD2 버전 유효 기간 (`valid_to` NULL = 현재) |
| *_key | MART | 대리키. `-1` = Unknown |
| is_revenue_eligible, exclusion_reason | CORE, MART Fact | 매출 인식 여부와 제외 사유 |
| is_deleted | MART Fact | 최신 스냅샷에서 사라진 행 (소프트 삭제) |
| updated_at | MART Fact | 마지막으로 반영된 실행 시각 |

## 파생 값

- `date_key`: `YYYYMMDD` 정수. 범위 밖이거나 알 수 없으면 `-1`.
- `line_amount`: `quantity × unit_price`.
- `days_to_first_success_payment`: 주문일부터 첫 성공 결제일까지의 일수. 성공 결제가 없으면 NULL.
- `first_success_paid_date_key`: 성공 결제 전이면 `-1`.
