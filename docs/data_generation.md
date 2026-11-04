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
| customers.csv | 2,028 | 지역 17개(인구 비례), 지역 누락 52명(→ Unknown), 이메일 누락 98명 |
| products.csv | 151 | 8개 카테고리, 가격 1,000원 ~ 300,000원 |
| orders.csv | 30,081 | 성장 추세, 주말·11~12월 성수기, 완료 약 92% / 취소 약 5% / 대기 약 2.5% |
| order_items.csv | 66,262 | 주문당 1~5줄(평균 약 2.2), 12% 는 프로모션 단가 |
| payments.csv | 31,096 | 완료 주문의 8% 는 실패 후 성공 |
| 합계 | 129,618 | 약 5MB |

## 2. 심어 둔 품질 문제

| 문제 | 건수 | 파이프라인 판정 |
|---|---:|---|
| 완전 중복 행 (고객 20, 상품 1, 주문 150, 상세 200, 결제 100) | 471 (+수업용 사례 2) | EXACT_DUPLICATE → 제거 |
| 같은 주문 ID, 다른 금액 | 40 | KEY_CONFLICT → 격리 |
| 같은 고객 ID, 다른 지역 | 5 | KEY_CONFLICT → 격리 (그 고객의 주문 전체가 DEPENDENCY_ERROR) |
| 주문 ID 누락 | 15 | INVALID_VALUE |
| 주문 금액 "N/A" / 없는 날짜 / 알 수 없는 상태 | 10 / 10 / 10 | INVALID_VALUE |
| 상세 수량 누락 / 수량 0 | 60 / 15 | INVALID_VALUE → 주문은 DEPENDENCY_ERROR |
| 결제 시각 누락 / 알 수 없는 결제 상태 | 20 / 10 | INVALID_VALUE → 주문은 DEPENDENCY_ERROR |
| 없는 고객 참조 | 80 | INVALID_REFERENCE |
| 없는 상품 참조 | 60 | INVALID_REFERENCE |
| 주문 없는 상세 / 주문 없는 결제 | 40 / 30 | INVALID_REFERENCE |
| 성공 결제 2건 | 60 | SUCCESS_PAYMENT_COUNT |
| 완료 주문인데 결제 없음 | 40 | SUCCESS_PAYMENT_COUNT |
| 결제 금액 불일치 / 주문 금액 불일치 | 80 / 60 | AMOUNT_MISMATCH |
| 완료 주문인데 상세 없음 | 30 | MISSING_ITEMS |

## 3. 정답 — Python 파이프라인 (`src.pipeline --dry-run`)

| 지표 | 값 |
|---|---:|
| input_rows | 129,618 |
| duplicate_rows | 473 |
| error_rows | 1,000 |
| excluded_orders | 2,889 |
| sales_orders | 27,055 |
| sales_amount | 2,198,198,700 |
| fact_order_items | 59,921 |

제외 사유: NOT_COMPLETED 2,190 / DEPENDENCY_ERROR 284 / INVALID_OR_MISSING_ORDER 142 / AMOUNT_MISMATCH 141 / SUCCESS_PAYMENT_COUNT 101 / MISSING_ITEMS 31

## 4. 정답 — Snowflake 엔터프라이즈 워크스루

RAW → CORE → MART(스타 스키마) 구조로 같은 데이터를 처리하는 Snowflake 실습 스크립트의 기대값입니다.
매출 인식 규칙이 같으므로 매출 주문 수와 총매출은 Python 결과와 일치합니다.

| 확인 항목 | 기대값 |
|---|---:|
| RUN_SUMMARY (input / 중복 / 격리 / 플래그) | 129,618 / 473 / 441 / 559 |
| 매출 주문 / 총매출 | 27,055 / 2,198,198,700 |
| 평균 주문 금액 | 약 81,249 |
| 판매 수량 | 86,068 |
| 매출 인식 전 총 라인 금액 | 2,421,319,800 |
| DIM_CUSTOMER / DIM_PRODUCT / DIM_DATE | 1,998 / 151 / 4,019 |
| FACT_SALES_LINE / FACT_PAYMENT / FACT_ORDER_LIFECYCLE | 65,789 / 30,966 / 29,802 |
| Unknown 고객·상품으로 연결된 라인 | 254 / 61 |
| 품질 검사 17개 | 모두 0 |
| 결제 요약 | 성공 27,702 / 실패 2,904 / 대기 360, 주문 없는 결제 108 |

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
