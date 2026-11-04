# 데이터 생성과 정답표

`data/raw` 는 `scripts/generate_data.py` (seed 101) 로 생성한 합성 데이터입니다.
2025-01-01 ~ 2026-10-31 기간의 온라인 쇼핑몰 데이터이며, 각 파일 맨 앞에는 판정이 정해진 수업용 사례 40행(O001~O010, C001·C002 등)이 들어 있습니다.

```bash
python scripts/generate_data.py          # data/raw 를 다시 생성 (같은 seed 면 같은 파일)
python -m src.pipeline --dry-run         # 아래 정답과 같은 결과가 나와야 합니다
```

## 1. 파일 규모

| 파일 | 행 수 | 특징 |
|---|---:|---|
| customers.csv | 2,028 | 지역 17개(인구 비례), 지역 누락 52명(→ Unknown), 이메일 누락 98명 (생성 고객 기준, 수업용 C002 제외) |
| products.csv | 151 | 8개 카테고리, 가격 1,000원 ~ 300,000원 |
| orders.csv | 30,081 | 성장 추세, 주말·11~12월 성수기, 완료 약 92% / 취소 약 5% / 대기 약 2.5% |
| order_items.csv | 66,262 | 주문당 1~5줄(평균 약 2.2), 12% 는 프로모션 단가 |
| payments.csv | 31,096 | 완료 주문의 8% 는 실패 후 성공 |
| 합계 | 129,618 | 약 5MB |

## 2. 심어 둔 품질 문제

| 문제 | 건수 | 파이프라인 판정 (error_code → action) |
|---|---:|---|
| 완전 중복 행 (고객 20, 상품 1, 주문 150, 상세 200, 결제 100) | 471 (+수업용 사례 2) | EXACT_DUPLICATE → REMOVED |
| 같은 주문 ID, 다른 금액 | 40 | KEY_CONFLICT → QUARANTINED |
| 같은 고객 ID, 다른 지역 | 5 | KEY_CONFLICT → QUARANTINED (그 고객의 주문은 고객 -1 로 적재, DEPENDENCY_ERROR) |
| 주문 ID 누락 | 15 | INVALID_VALUE → QUARANTINED |
| 주문 금액 "N/A" / 없는 날짜 / 알 수 없는 상태 | 10 / 10 / 10 | INVALID_VALUE → QUARANTINED |
| 상세 수량 누락 / 수량 0 | 60 / 15 | INVALID_VALUE → QUARANTINED, 주문은 DEPENDENCY_ERROR |
| 결제 시각 누락 / 알 수 없는 결제 상태 | 20 / 10 | INVALID_VALUE → QUARANTINED, 주문은 DEPENDENCY_ERROR |
| 없는 고객 참조 | 80 | INVALID_REFERENCE → FLAGGED (customer_key = -1), 주문은 DEPENDENCY_ERROR |
| 없는 상품 참조 | 60 | INVALID_REFERENCE → FLAGGED (product_key = -1), 주문은 DEPENDENCY_ERROR |
| 주문 없는 상세 / 주문 없는 결제 | 40 / 30 | INVALID_REFERENCE → 상세는 QUARANTINED, 결제는 FLAGGED (has_valid_order = FALSE) |
| 성공 결제 2건 | 60 | SUCCESS_PAYMENT_COUNT → FLAGGED |
| 완료 주문인데 결제 없음 | 40 | SUCCESS_PAYMENT_COUNT → FLAGGED |
| 결제 금액 불일치 / 주문 금액 불일치 | 80 / 60 | AMOUNT_MISMATCH → FLAGGED |
| 완료 주문인데 상세 없음 | 30 | MISSING_ITEMS → FLAGGED |

건수는 심은 개수이며, 한 행에 여러 문제가 겹치거나 상위 오류에 가려진 경우가 있어 3절의 이슈 수와 정확히 같지는 않습니다.

## 3. 정답 — 파이프라인 결과

Python 로컬 실행(`python -m src.pipeline --dry-run`), Snowflake 노트북, `python -m src.pipeline --load` 모두 같은 값이 나와야 합니다.
`tests/test_core.py`, `tests/test_mart.py` 가 이 표를 검사합니다.

### CORE (STEP 4~5, `CORE.RUN_SUMMARY`)

| 지표 | 값 |
|---|---:|
| input_rows | 129,618 |
| duplicate_rows (REMOVED) | 473 |
| quarantined_rows (QUARANTINED 고유 행) | 441 |
| flagged_issues (FLAGGED) | 559 |
| revenue_orders | 27,055 |
| revenue_amount | 2,198,198,700 |

이슈 내역: REMOVED `EXACT_DUPLICATE` 473 / QUARANTINED `KEY_CONFLICT` 92 · `INVALID_VALUE` 152 · `INVALID_REFERENCE` 197 / FLAGGED `INVALID_REFERENCE` 286 · `AMOUNT_MISMATCH` 141 · `SUCCESS_PAYMENT_COUNT` 101 · `MISSING_ITEMS` 31

주문 판정: 매출 인식 27,055 / NOT_COMPLETED 2,190 / DEPENDENCY_ERROR 284 / AMOUNT_MISMATCH 141 / SUCCESS_PAYMENT_COUNT 101 / MISSING_ITEMS 31 (합계 29,802, 모두 MART 에 적재)

### MART (STEP 7~8)

| 확인 항목 | 기대값 |
|---|---:|
| 실행 상태 / 품질 검사 17개 | SUCCESS / 모두 0 |
| 매출 주문 / 총매출 / 평균 주문 금액 | 27,055 / 2,198,198,700 / 약 81,249 |
| 매출 라인 / 판매 수량 | 59,921 / 86,068 |
| 매출 인식 전 총 라인 금액 | 2,421,319,800 |
| DIM_CUSTOMER / DIM_PRODUCT / DIM_DATE (Unknown 포함) | 1,998 / 151 / 4,019 |
| FACT_SALES_LINE / FACT_PAYMENT / FACT_ORDER_LIFECYCLE | 65,789 / 30,966 / 29,802 |
| Unknown 고객·상품으로 연결된 라인 | 254 / 61 |
| V_REVENUE_CALENDAR 일수 | 669 |
| 결제 요약 | 성공 27,702 / 실패 2,904 / 대기 360, 주문 없는 결제 108 |

### 노트북으로 실행할 때

노트북은 `SET load_id = UUID_STRING()` 을 허용하지 않으므로 STEP 2 에서 `CORE.RUN_CTX` 에 `load_id`·`run_ts` 를 먼저 만들고 세션 변수는 그 테이블에서 읽습니다.
STEP 7 은 셀(7-0 가드 → 7-1 SCD2 차원 → 7-2 Fact MERGE → 7-3 품질 검사 → 7-4 상태 확정)로 나뉘어 있고, 검사 실패 시 자동 ROLLBACK 은 없습니다.
7-3 에서 17개 검사가 모두 0, 7-4 에서 `AUDIT.PIPELINE_RUNS` 가 SUCCESS / 27,055 / 2,198,198,700 이면 정상입니다.

### 카테고리별 매출

| 카테고리 | 매출 |
|---|---:|
| 전자기기 | 921,160,700 |
| 생활용품 | 263,837,900 |
| 주방 | 247,517,500 |
| 패션잡화 | 201,015,400 |
| 뷰티 | 187,888,800 |
| 도서 | 174,657,900 |
| 문구 | 108,553,400 |
| 식품 | 93,567,100 |

### 지역별 매출 (주문 당시, 상위 5)

| 지역 | 주문 | 매출 |
|---|---:|---:|
| 경기 | 7,741 | 635,003,900 |
| 서울 | 5,189 | 420,094,900 |
| 경남 | 2,113 | 169,902,600 |
| 인천 | 1,562 | 124,064,800 |
| 부산 | 1,506 | 120,881,700 |

### 역할별 결과 (STEP 9)

| 쿼리 | AE101_ANALYST_SEOUL | AE101_MANAGER |
|---|---|---|
| DIM_CUSTOMER | 389행, 이메일 마스킹 | 1,998행, 이메일 원문 |
| V_REVENUE_DAILY 합계 | 420,094,900 | 2,198,198,700 |

### SCD2 체험 (STEP 11, C002 → 부산)

| 뷰 | 부산 | Unknown |
|---|---:|---:|
| V_REVENUE_BY_REGION_ASWAS | 120,881,700 | 51,063,400 |
| V_REVENUE_BY_REGION_ASIS | 120,896,700 | 51,048,400 |
