# 처리 규칙과 지표 정의

규칙의 원본은 `sql/03_core_clean.sql`, `sql/04_core_order_quality.sql`, `sql/08_mart_dq_checks.sql`이며 `src/core.py`와 `src/mart.py`가 같은 규칙을 구현합니다.

## 정제 (CORE, STEP 4)

각 원본 행에 `dq_status`를 붙이고, 문제가 있으면 이슈를 기록합니다.

| dq_status | 조건 | 이슈 action | CORE 적재 |
|---|---|---|---|
| DUPLICATE | 원본 값이 완전히 같은 행 (공백 제거 전 값 기준). 첫 행만 남김 | REMOVED (`EXACT_DUPLICATE`) | 1건만 |
| CONFLICT | 같은 업무 키에 서로 다른 원본 행. 어느 쪽이 최신인지 모르므로 **모두** 격리 | QUARANTINED (`KEY_CONFLICT`) | 안 함 |
| INVALID | 필수값 누락, 숫자·날짜·시각 형식 오류, 상한(10^12) 초과, 수량 0, 알 수 없는 상태값 | QUARANTINED (`INVALID_VALUE`) | 안 함 |
| OK | 그 외 | 없음 | 함 |

추가 규칙은 다음과 같습니다.

1. 앞뒤 공백을 제거하고 빈 문자열은 NULL로 봅니다. 숫자 변환 실패를 0으로 바꾸지 않습니다.
2. email은 선택값(NULL 유지), region은 선택값(없으면 `Unknown`)입니다. 나머지 컬럼은 필수입니다.
3. **참조 오류는 격리하지 않고 표시(FLAGGED)합니다.** 없는 고객을 가리키는 주문은 `customer_key = -1`, 없는 상품을 가리키는 주문 상세는 `product_key = -1`로 적재합니다. 주문이 없는 결제는 `has_valid_order = FALSE`로 적재합니다.
4. 주문이 없는 주문 상세는 날짜·고객·상태를 알 수 없으므로 격리(QUARANTINED, `INVALID_REFERENCE`)합니다. 참조 오류 중 이 경우만 격리하는 이유는 아래 [INVALID_REFERENCE: 네 가지 경우](#invalid_reference-네-가지-경우)를 보세요.
5. 고객·상품은 `hash_diff`(속성 값의 MD5)를 계산해 두고 MART의 SCD2 변경 감지에 씁니다.

### INVALID_REFERENCE: 네 가지 경우

`INVALID_REFERENCE`는 "가리키는 상대 행이 CORE에 없다"는 오류 코드이고, STEP 4의 네 곳에서 만들어집니다. 코드는 같지만 처리는 둘로 갈리므로, 구분하려면 `action`과 `error_detail`을 함께 보세요.

| 경우 | `action` | `error_detail` | 적재 결과 | 연결된 주문의 매출 | 첫 실행 건수 |
|---|---|---|---|---|---:|
| 주문의 고객이 없음 | FLAGGED | `Unknown customer: loaded with customer_key = -1` | 적재. `customer_key = -1` | 제외 (DEPENDENCY_ERROR) | 117 |
| 주문 상세의 상품이 없음 | FLAGGED | `Unknown product: loaded with product_key = -1` | 적재. `product_key = -1` | 제외 (DEPENDENCY_ERROR) | 61 |
| 결제의 주문이 없음 | FLAGGED | `Parent order not found: loaded with customer_key = -1` | 적재. `has_valid_order = FALSE`, MART에서 `customer_key = -1` | 해당 없음 (주문이 CORE에 없음) | 108 |
| 주문 상세의 주문이 없음 | **QUARANTINED** | `Parent order not found: quarantined` | **적재 안 함**. `AUDIT.DATA_ISSUES`에만 남음 | 해당 없음 (주문이 CORE에 없음) | 197 |

건수는 기본 데이터(`data/raw`)를 처음 실행한 결과이며, 위 세 줄의 합이 FLAGGED 286건, 마지막 줄이 QUARANTINED 197건입니다. 결제와 주문 상세의 `error_detail`은 둘 다 `Parent order not found`로 시작하지만 `action`이 다르니 혼동하지 마세요.

**판단 기준: 그 행이 자기 정보만으로 Fact 행이 될 수 있는가.**

- 앞의 세 경우는 모르는 것이 키 하나뿐입니다. 주문은 날짜·상태·금액이, 주문 상세는 수량·금액과 주문 헤더에서 오는 고객·날짜가, 결제는 결제 시각·상태·금액이 그대로 있습니다. 모르는 키만 Unknown 멤버(`-1`)에 연결하면 나머지 열로 집계할 수 있고, 표시(FLAGGED)로 원인도 추적됩니다.
- 주문 상세는 고객·주문일·주문 상태를 주문 헤더에서 가져옵니다(`CORE.SALES_LINE_PREP`이 `ORDER_ITEMS`와 `ORDER_QUALITY`를 내부 조인). 주문이 없으면 세 가지를 한꺼번에 모릅니다. 이 행을 `-1`로 적재하면 다음 문제가 생깁니다.
    1. 고객·날짜·상태가 모두 Unknown이라 누구에게 언제 판 것인지 집계할 수 없습니다. Unknown 멤버는 한 차원이 불명일 때 쓰는 장치입니다.
    2. 주문일이 없으면 고객·상품의 SCD2 버전을 고르는 기준 날짜가 없습니다.
    3. 주문이 없으니 `FACT_ORDER_LIFECYCLE` 행도 없어서 이 라인이 매출로 인정되는지 판정할 수 없습니다.
- 결제는 주문이 없어도 `paid_at`으로 날짜 키를 만들 수 있고, 상태·금액도 자기 값입니다. 주문에서 오던 고객만 모르므로 `customer_key = -1`로 적재합니다(`CORE.PAYMENT_PREP`은 `PAYMENTS`에 `ORDERS`를 LEFT JOIN).

**"주문이 없다"의 뜻.** 판단 기준은 "`CORE.ORDERS`에 없다"입니다. 원본에 아예 없는 경우뿐 아니라, 원본에는 있지만 STEP 4에서 격리된 주문(`KEY_CONFLICT`, `INVALID_VALUE`)도 포함합니다. 고객·상품도 같은 방식입니다. 그래서 부모 행 하나가 격리되면 그 자식 행이 연달아 `INVALID_REFERENCE`로 잡힙니다.

| 경우 | 부모가 원본에 없음 | 부모는 원본에 있으나 격리됨 |
|---|---:|---:|
| 주문의 고객이 없음 | 81 | 36 |
| 주문 상세의 상품이 없음 | 61 | 0 |
| 결제의 주문이 없음 | 30 | 78 |
| 주문 상세의 주문이 없음 | 41 | 156 |

이슈 수를 원인 수로 읽지 마세요. 오른쪽 열의 건수는 부모의 `KEY_CONFLICT`·`INVALID_VALUE`를 고치면 함께 사라집니다. 먼저 부모의 이슈를 확인하세요.

```sql
-- 최근 실행의 INVALID_REFERENCE 를 경우별로 (action 까지 같이 봄)
SELECT action, error_detail, COUNT(*) AS cnt
FROM AUDIT.DATA_ISSUES
WHERE load_id = (SELECT load_id FROM MART.V_LATEST_RUN)
  AND error_code = 'INVALID_REFERENCE'
GROUP BY action, error_detail
ORDER BY action, error_detail;

-- 부모 주문이 없는 상세·결제를 원인별로: 주문이 원본에 없는지, 있는데 격리됐는지
SELECT i.source_file,
       CASE WHEN o.order_id IS NULL THEN '주문이 원본에 없음' ELSE '주문은 있으나 격리됨' END AS cause,
       COUNT(*) AS cnt
FROM AUDIT.DATA_ISSUES i
LEFT JOIN (SELECT DISTINCT TRIM(order_id) AS order_id FROM RAW.V_ORDERS_LATEST) o ON i.order_id = o.order_id
WHERE i.load_id = (SELECT load_id FROM MART.V_LATEST_RUN)
  AND i.error_detail LIKE 'Parent order not found%'
GROUP BY i.source_file, cause
ORDER BY i.source_file, cause;
```

## 매출 인식 (CORE, STEP 5)

주문마다 아래 순서로 첫 번째 해당 사유를 `exclusion_reason`에 기록합니다. 사유가 없으면 매출로 인식합니다(`is_revenue_eligible = TRUE`).

| 순서 | 사유 | 조건 |
|---:|---|---|
| 1 | DEPENDENCY_ERROR | 이 주문에 연결된 행(주문 자신, 주문 상세, 결제)에 격리 또는 표시 이슈가 있음 |
| 2 | NOT_COMPLETED | 주문 상태가 completed 가 아님 |
| 3 | SUCCESS_PAYMENT_COUNT | 성공 결제가 정확히 1건이 아님 (실패 후 성공은 허용) |
| 4 | MISSING_ITEMS | 주문 상세가 없음 |
| 5 | AMOUNT_MISMATCH | 주문 금액 = 상세 합계 = 성공 결제 금액이 아님 |

3~5번 사유는 FLAGGED 이슈로도 기록합니다. **제외된 주문도 삭제하지 않고 MART에 적재합니다.**
키 충돌로 격리된 주문(예: O007)은 CORE에 없으므로 판정 대상이 아니며, AUDIT 이슈로만 남습니다.

## 지표

| 지표 | 정의 | 원천 |
|---|---|---|
| 총매출 | 매출 인식 주문의 `line_amount` 합계 (= 주문 금액 합계) | `V_REVENUE_DAILY.revenue` |
| 주문 수 | 매출 인식 주문 수 | `V_REVENUE_DAILY.order_count` |
| 평균 주문 금액 | 총매출 / 주문 수. 0건이면 계산 대상 없음 | 계산 |
| 상품 매출 | 상품별 `line_amount` 합계 | `V_REVENUE_BY_PRODUCT` |
| 지역 매출 | 주문 당시 지역(ASWAS) 또는 현재 지역(ASIS) 기준 | `V_REVENUE_BY_REGION_*` |
| input_rows | 이번 배치의 RAW 행 수 | `CORE.RUN_SUMMARY` |
| duplicate_rows | REMOVED 이슈 수 | 〃 |
| quarantined_rows | QUARANTINED 이슈가 있는 고유 (파일, 행) 수 | 〃 |
| flagged_issues | FLAGGED 이슈 수 (한 주문에 여러 건일 수 있음) | 〃 |
| revenue_orders / revenue_amount | 매출 인식 주문 수 / 주문 금액 합계 | 〃 |

모든 매출 지표는 `is_revenue_eligible AND NOT is_deleted` 조건으로 집계합니다.
일별 기준은 주문일(한국 시간)이며 시작일과 종료일을 모두 포함합니다. 결제일 매출, 회계상 수익 인식, 환불·수수료·정산은 이 지표와 다릅니다.

## 게시 정책 (MART, STEP 7)

- 차원은 SCD2로 이력을 남기고, Fact는 업무 키로 MERGE(업서트)합니다.
- 이번 스냅샷에서 사라진 Fact 행은 `is_deleted = TRUE`로 표시합니다. 물리 삭제는 하지 않습니다.
- 반영 후 품질 검사 17개를 실행하고, 하나라도 실패하면 실행 상태를 `FAILED`로 남깁니다. 검사별 기준은 아래 [품질 검사](#품질-검사-mart-step-7-3)를 보세요.

참고: [Snowflake MERGE](https://docs.snowflake.com/en/sql-reference/sql/merge)

## 품질 검사 (MART, STEP 7-3)

MART 반영이 끝나면 17개 검사를 실행해 결과를 `AUDIT.DQ_RESULTS`에 저장합니다. 원본은 `sql/08_mart_dq_checks.sql`(노트북 셀 `step7_3_dq`)이고, `src/mart.py`의 `dq_checks()`가 같은 이름·같은 기준으로 로컬에서 계산합니다.
Snowflake는 PK/FK를 선언만 하고 강제하지 않으므로, 키 유일성·참조 무결성·금액 대사를 이 검사로 직접 확인합니다.

### 저장 형태와 판정

| 항목 | 내용 |
|---|---|
| 저장 위치 | `AUDIT.DQ_RESULTS (load_id, check_name, failures)`. 실행 1회당 17행 |
| 다시 실행할 때 | 같은 `load_id`의 결과를 지우고 다시 넣으므로 중복되지 않습니다 |
| `failures` | 기준을 어긴 건수. **0이어야 통과**입니다. 세는 단위는 검사마다 다릅니다 (아래 표의 "센다") |
| 판정 (STEP 7-4) | 17개의 `failures` 합이 0이면 `AUDIT.PIPELINE_RUNS.status = SUCCESS`, 아니면 `FAILED`이고 `message`에 `DQ failed: <실패한 검사 이름>`을 남깁니다 |
| 실패해도 | MART는 이미 바뀐 상태이며 자동으로 되돌리지 않습니다. 매일 배치에서는 `daily_gate` 셀이 오류를 내 태스크도 실패로 표시됩니다 |
| 조회 | `MART.V_DQ_RESULTS`(검사별), `MART.V_RUN_HISTORY`(`failed_checks` / `total_checks`), Streamlit "데이터 운영" 탭 |

**Unknown(-1) 멤버와의 관계.** 모든 차원에 `-1` 행이 있으므로, 고객·상품·날짜를 찾지 못해 `-1`로 연결된 Fact 행은 참조 무결성 검사(5~9번 그룹)를 통과합니다. 참조 오류 자체는 STEP 4에서 FLAGGED 이슈로 기록되고, 그런 행이 매출에 들어갔는지는 17번 `revenue_requires_known_keys`가 따로 확인합니다.

### 검사 17개

| # | check_name | 대상 | 실패 조건 | 센다 | 왜 필요한가 |
|---:|---|---|---|---|---|
| 1 | `dim_customer_one_current_version` | DIM_CUSTOMER | `is_current = TRUE` 버전이 정확히 1개가 아닌 고객 | 고객 ID 수 | 현재 버전이 0개면 As-Is 지역 매출에서 빠지고, 2개 이상이면 중복 집계됩니다. SCD2 UPDATE·INSERT 중 하나만 반영된 경우에 걸립니다 |
| 2 | `dim_customer_key_unique` | DIM_CUSTOMER | 같은 `customer_key`가 2행 이상 | 중복된 키 수 | 대리키가 겹치면 Fact가 한 고객에 연결돼도 조인에서 행이 늘어 매출이 부풀어 오릅니다 |
| 3 | `dim_customer_valid_range` | DIM_CUSTOMER | `valid_to`가 있는데 `valid_from`보다 늦지 않음 | 행 수 | 유효 기간이 비거나 뒤집히면 point-in-time 조인이 그 버전을 찾지 못해 고객이 Unknown으로 연결됩니다. 같은 `run_ts`로 만든 버전을 바로 닫은 경우(같은 실행을 바뀐 입력으로 다시 돌림) 등에 걸립니다 |
| 4 | `dim_product_one_current_version` | DIM_PRODUCT | `is_current = TRUE` 버전이 정확히 1개가 아닌 상품 | 상품 ID 수 | 1번과 같은 이유 (상품) |
| 5 | `dim_product_key_unique` | DIM_PRODUCT | 같은 `product_key`가 2행 이상 | 중복된 키 수 | 2번과 같은 이유 (상품) |
| 6 | `fact_sales_line_key_unique` | FACT_SALES_LINE | 같은 `order_item_id`가 2행 이상 | 중복된 키 수 | 그레인(주문 상세 1줄 = 1행)이 깨지면 매출·수량이 이중 집계됩니다. MERGE 조건이 잘못됐을 때 걸립니다 |
| 7 | `fact_sales_line_customer_fk` | FACT_SALES_LINE → DIM_CUSTOMER | `customer_key`가 DIM_CUSTOMER에 없음 | Fact 행 수 | 내부 조인하는 리포트 뷰에서 그 행이 조용히 사라집니다 |
| 8 | `fact_sales_line_product_fk` | FACT_SALES_LINE → DIM_PRODUCT | `product_key`가 DIM_PRODUCT에 없음 | Fact 행 수 | 7번과 같은 이유 (상품별 매출) |
| 9 | `fact_sales_line_date_fk` | FACT_SALES_LINE → DIM_DATE | `order_date_key`가 DIM_DATE에 없음 | Fact 행 수 | 일별·월별 매출에서 빠집니다 |
| 10 | `fact_sales_line_status_fk` | FACT_SALES_LINE → DIM_ORDER_STATUS | `order_status_key`가 DIM_ORDER_STATUS에 없음 | Fact 행 수 | 상태별 분석에서 빠집니다 |
| 11 | `fact_sales_line_amount_calc` | FACT_SALES_LINE | 수량 ≤ 0, 단가 < 0, 또는 `line_amount ≠ quantity × unit_price` | Fact 행 수 | 매출의 최소 단위인 라인 금액이 계산식과 다르면 그 위의 모든 합계가 틀립니다 |
| 12 | `fact_payment_key_unique` | FACT_PAYMENT | 같은 `payment_id`가 2행 이상 | 중복된 키 수 | 결제 시도 수·성공률이 부풀어 오릅니다 |
| 13 | `fact_payment_status_fk` | FACT_PAYMENT → DIM_PAYMENT_STATUS | `payment_status_key`가 DIM_PAYMENT_STATUS에 없음 | Fact 행 수 | 결제 상태별 집계에서 빠집니다 |
| 14 | `fact_order_lifecycle_key_unique` | FACT_ORDER_LIFECYCLE | 같은 `order_id`가 2행 이상 | 중복된 키 수 | 주문 수와 주문 금액(헤더 금액은 이 Fact에만 있음)이 이중 집계됩니다 |
| 15 | `revenue_order_reconciliation` | FACT_ORDER_LIFECYCLE (매출 인정·삭제 안 된 주문) | 주문 금액 ≠ 상세 합계, 주문 금액 ≠ 성공 결제 금액, 또는 성공 결제 ≠ 1건 | 주문 수 | STEP 5의 매출 인정 규칙이 MART까지 그대로 지켜졌는지 다시 확인합니다. MART를 직접 고쳤거나 MERGE가 일부 컬럼만 갱신했을 때 걸립니다 |
| 16 | `revenue_line_vs_order` | FACT_ORDER_LIFECYCLE ↔ FACT_SALES_LINE | 매출 인정 주문의 주문 금액 ≠ 삭제 안 된 상세 Fact의 `line_amount` 합, 또는 상세가 하나도 없음 | 주문 수 | 주문 그레인과 라인 그레인의 매출 합계가 같아야 어느 Fact로 집계해도 숫자가 같습니다. Fact 셀 일부만 다시 실행해 두 Fact가 서로 다른 실행을 반영하고 있을 때 걸립니다 |
| 17 | `revenue_requires_known_keys` | FACT_SALES_LINE (매출 인정·삭제 안 된 행) | 고객·상품·주문일 키 중 하나라도 `-1` | Fact 행 수 | 매출은 누구에게 무엇을 언제 팔았는지 알 때만 인정합니다. 참조 오류 주문은 STEP 5에서 이미 빠지므로, 여기서 걸리면 point-in-time 조인이 버전을 찾지 못했거나 주문일이 `DIM_DATE` 범위(2030-12-31)를 넘은 경우입니다 |

| 그룹 | 검사 | 확인하는 것 |
|---|---|---|
| 차원 무결성 | 1 ~ 5 | SCD2 현재 버전 1개, 대리키 유일, 유효 기간 순서 |
| Fact 키 유일성 | 6, 12, 14 | 각 Fact의 그레인 |
| 참조 무결성 | 7 ~ 10, 13 | Fact의 대리키가 차원에 있음 (선언만 된 FK를 직접 확인) |
| 금액 계산 | 11 | 라인 금액 계산식 |
| 매출 대사 | 15 ~ 17 | 매출 인정 주문의 금액이 주문·상세·결제 사이에서 맞고, 알 수 있는 키에만 매출이 있음 |

**현재 검사하지 않는 것.** `DIM_PRODUCT`의 유효 기간 순서, `FACT_PAYMENT`의 고객·결제일 키, `FACT_ORDER_LIFECYCLE`의 고객·날짜·상태 키는 검사 대상이 아닙니다. 이 키들은 `FACT_SALES_LINE`과 같은 방식으로 연결되므로 함께 깨질 가능성이 높지만, 엄격히 보려면 아래 "검사 추가 방법"으로 늘리세요.

### 결과 확인과 원인 찾기

실행별 결과는 다음처럼 봅니다.

```sql
-- 최근 실행의 검사 결과 (실패한 것부터)
SELECT check_name, failures
FROM MART.V_DQ_RESULTS
WHERE load_id = (SELECT load_id FROM MART.V_LATEST_RUN)
ORDER BY failures DESC, check_name;

-- 실패가 있었던 실행만
SELECT r.started_at, r.status, d.check_name, d.failures
FROM MART.V_DQ_RESULTS d JOIN MART.V_RUN_HISTORY r ON r.load_id = d.load_id
WHERE d.failures > 0
ORDER BY r.started_at DESC, d.check_name;
```

`failures`가 0이 아니면 아래 쿼리로 해당 행을 찾습니다. 검사 SQL의 `COUNT(*)`를 행 조회로 바꾼 것입니다.
원인 하나가 여러 검사를 함께 실패시킬 수 있습니다. 예를 들어 상세 Fact 행이 중복되면 6번과 16번이, 라인 금액이 틀리면 11번과 16번이 함께 실패합니다. 번호가 작은 검사부터 보세요.

```sql
-- 1, 4. 현재 버전이 1개가 아닌 고객 (상품은 DIM_PRODUCT, product_id 로 바꿈)
SELECT customer_id, COUNT_IF(is_current) AS current_versions, COUNT(*) AS versions
FROM MART.DIM_CUSTOMER GROUP BY customer_id HAVING COUNT_IF(is_current) <> 1;

-- 2, 5, 6, 12, 14. 키 중복 (테이블·키 컬럼만 바꿈)
SELECT customer_key, COUNT(*) AS cnt FROM MART.DIM_CUSTOMER GROUP BY customer_key HAVING COUNT(*) > 1;

-- 3. 유효 기간이 뒤집힌 버전
SELECT * FROM MART.DIM_CUSTOMER WHERE valid_to IS NOT NULL AND valid_to <= valid_from;

-- 7 ~ 10, 13. 차원에 없는 키 (차원·키 컬럼만 바꿈)
SELECT f.* FROM MART.FACT_SALES_LINE f
LEFT JOIN MART.DIM_CUSTOMER c ON f.customer_key = c.customer_key
WHERE c.customer_key IS NULL;

-- 11. 라인 금액 계산 오류
SELECT order_item_id, quantity, unit_price, line_amount, quantity * unit_price AS expected
FROM MART.FACT_SALES_LINE
WHERE quantity <= 0 OR unit_price < 0 OR line_amount <> quantity * unit_price;

-- 15. 매출 인정 주문의 금액 불일치
SELECT order_id, order_amount, line_amount_total, success_payment_amount, success_payment_count
FROM MART.FACT_ORDER_LIFECYCLE
WHERE is_revenue_eligible AND NOT is_deleted
  AND (order_amount <> line_amount_total OR order_amount <> success_payment_amount OR success_payment_count <> 1);

-- 16. 주문 금액과 상세 Fact 합계가 다른 매출 주문
SELECT o.order_id, o.order_amount, l.amt AS line_amount_sum
FROM MART.FACT_ORDER_LIFECYCLE o
LEFT JOIN (SELECT order_id, SUM(line_amount) AS amt FROM MART.FACT_SALES_LINE
           WHERE NOT is_deleted GROUP BY order_id) l ON o.order_id = l.order_id
WHERE o.is_revenue_eligible AND NOT o.is_deleted AND (l.amt IS NULL OR l.amt <> o.order_amount);

-- 17. Unknown 키에 들어간 매출
SELECT order_item_id, order_id, customer_key, product_key, order_date_key, order_date
FROM MART.FACT_SALES_LINE
WHERE is_revenue_eligible AND NOT is_deleted
  AND (customer_key = -1 OR product_key = -1 OR order_date_key = -1);
```

실패 원인을 고친 뒤에는 STEP 7(06)부터 다시 실행합니다. 이미 반영된 MART를 되돌려야 하면 [실행 순서와 복구](execution_flow.md#오류와-복구)의 Time Travel 방법을 씁니다.

### 검사 추가 방법

검사 이름과 기준은 SQL과 Python 두 곳에서 같아야 합니다. 하나를 추가하려면 다음을 함께 바꿉니다.

1. 워크스루 노트북 `step7_3_dq` 셀과 `sql/08_mart_dq_checks.sql`에 `UNION ALL SELECT '<check_name>', COUNT(*) ...`을 추가합니다. 두 파일은 `tests/test_notebook_sync.py`가 같은지 검사합니다.
2. `src/mart.py`의 `dq_checks()`에 같은 이름·같은 기준을 추가합니다.
3. `python scripts/build_daily_notebook.py`로 매일 배치 노트북을 다시 만듭니다.
4. 이 문서의 표에 한 줄을 추가하고, "17개"라고 적힌 문서와 테스트(`tests/test_mart.py`, `tests/test_docs.py`)의 개수를 고칩니다.
5. `python -m unittest discover -s tests`로 확인합니다. `tests/test_docs.py`는 SQL과 Python의 검사 이름이 같은지, 이 문서에 모든 검사가 있는지 확인합니다.
