# 처리 규칙과 지표 정의

규칙의 원본은 `sql/03_core_clean.sql`, `sql/04_core_order_quality.sql`이며 `src/core.py`가 같은 규칙을 구현합니다.

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
4. 주문이 없는 주문 상세는 날짜·고객을 알 수 없으므로 격리(QUARANTINED, `INVALID_REFERENCE`)합니다.
5. 고객·상품은 `hash_diff`(속성 값의 MD5)를 계산해 두고 MART의 SCD2 변경 감지에 씁니다.

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
- 반영 후 품질 검사 17개를 실행하고, 하나라도 실패하면 실행 상태를 `FAILED`로 남깁니다.

참고: [Snowflake MERGE](https://docs.snowflake.com/en/sql-reference/sql/merge)
