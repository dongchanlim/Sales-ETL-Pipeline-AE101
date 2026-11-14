# 데이터 생성과 정답표

`data/raw` 는 `scripts/generate_data.py` 로 만든 합성 데이터입니다.
2025-01-01 ~ 2026-10-31 기간의 온라인 쇼핑몰 데이터이며, 각 파일 맨 앞에는 판정이 정해진 수업용 사례 40행(O001~O010, C001·C002 등)이 들어 있습니다.
생성기는 CSV 5개와 함께, 무엇을 어디에 심었는지 적은 `answer_key.json` 을 같은 폴더에 씁니다.

```bash
python scripts/generate_data.py                # 새 무작위 데이터 (실행할 때마다 다름) → data/raw
python scripts/generate_data.py --seed 7       # 같은 seed 로 같은 데이터를 다시 만들기
python scripts/generate_data.py --answer-key   # 정답표 데이터(seed 101)로 되돌리기
python -m src.pipeline --dry-run               # 지금 data/raw 의 결과 보고서 (outputs/)
```

### Snowflake 안에서 새 데이터로 실행하기 (스테이지)

Snowflake에서는 생성기를 노트북에 붙여 넣어 실행할 필요가 없습니다. STEP 3이 스테이지를 거쳐 적재하므로, 노트북의 `landing_source` 값만 바꾸면 됩니다.

```
STEP 3-0  landing_source 선택     'git' (워크스루 기본) | 'random' (매일 배치 기본) | 'answer-key'
STEP 3-0a Git data/raw ──COPY FILES──▶ @RAW.LANDING/current/   (항상)
STEP 3-0b 'random'·'answer-key' 이면 CALL RAW.GENERATE_LANDING_FILES(...) 가 같은 이름의 파일 6개를 덮어씀
          이번 배치의 answer_key.json 을 @RAW.LANDING/batches/<load_id>/ 에 복사 (어떤 데이터였는지 기록)
STEP 3-1  @RAW.LANDING/current/*.csv ──INSERT──▶ RAW 새 배치
```

- **생성 프로시저:** `RAW.GENERATE_LANDING_FILES(SOURCE, SEED)`는 STEP 1에서 만듭니다. Git 저장소의 `scripts/generate_data.py`를 `IMPORTS`로 불러와 핸들러 `land_to_stage`를 실행합니다.
- **파일 경로:** 파일은 메모리에서 만들어 `put_stream`으로 스테이지에 바로 올립니다. 그래서 노트북의 로컬 파일 시스템을 거치지 않습니다.
- **`SEED` 값:** `0`이면 새로 뽑고, 다른 값이면 그 seed로 같은 데이터를 다시 만듭니다. 노트북에서는 `landing_seed`로 넘깁니다.
- **생성기를 고쳤을 때:** STEP 0의 FETCH 다음에 STEP 1의 `CREATE OR REPLACE PROCEDURE` 문을 다시 실행하면 확실하게 반영됩니다.
- **워크시트에서 실행할 때:** `sql/02` 를 실행한 다음 `CALL RAW.GENERATE_LANDING_FILES('random', 0);` 를 실행합니다. 이 CALL은 3-0a의 `COPY FILES` 와 STEP 3-1의 `INSERT` 사이에 있어야 합니다.
- **정답 확인:** 배치마다 심은 문제의 정답은 `@RAW.LANDING/batches/<load_id>/answer_key.json`에 있습니다.

```sql
LIST @RAW.LANDING/batches/;                                          -- 배치별 정답표 파일
CREATE FILE FORMAT IF NOT EXISTS RAW.JSON_FORMAT TYPE = JSON;        -- 스테이지 파일 조회는 이름 있는 파일 포맷이 필요
SELECT $1:seed, $1:mode, $1:row_counts                               -- 최근 배치의 seed 와 행 수
FROM @RAW.LANDING/current/answer_key.json (FILE_FORMAT => 'RAW.JSON_FORMAT');
```

### Python으로 실행할 때 (노트북 셀 포함)

노트북 셀에 생성기 코드를 붙여 넣어 실행해도 동작합니다. 셀에는 `__file__`이 없고 `sys.argv`에 커널 인자가 들어 있으므로, 생성기는 현재 폴더 기준 `data/raw`에 쓰고 `sys.argv`는 읽지 않습니다. 옵션은 `main(["--seed", "7", "--out", "/tmp/raw"])`처럼 리스트로 넘깁니다. 이렇게 만든 파일은 노트북의 로컬 파일 시스템에만 생기고 파이프라인에는 들어가지 않으므로, Snowflake에서는 위의 스테이지 방식을 쓰세요.

## 0. 생성 모드

| 모드 | seed | 규모 | 심는 문제 | 기대값 확인 |
|---|---|---|---|---|
| 기본 (무작위) | 실행마다 새로 뽑아 화면과 `answer_key.json`에 남김 | 고객 2,000 · 주문 30,000 기준 ±5% | 2-1의 문제(건수 ±40%) + 2-2 현실적인 오류 + 2-3 미탐지 오류 + 2-4 정상 처리 값 | `answer_key.json`, `--dry-run` 보고서 |
| `--seed N` | 지정한 값 | 기본과 같음 | 기본과 같음 | 같은 seed 면 파일이 한 글자도 다르지 않음 |
| `--answer-key` | 101 | 고정 | 2-1의 문제를 표의 건수 그대로 | 3절 정답표, 노트북·`sql/` 의 기대값 주석 |

지역 비율, 카테고리와 가격대, 성장 추세·주말·11~12월 성수기, 주문당 라인 수, 주문 상태 비율, 결제 실패 후 재시도 비율은 모든 모드에서 같은 모델로 만듭니다.

상품이 151개뿐이라 상품 인기도를 그냥 뽑으면 평균 주문 금액이 ±40%, 카테고리 매출 비중이 2배까지 흔들립니다. 그래서 무작위 모드는 두 가지를 정답표 데이터에 맞춥니다.

1. 카테고리별 기대 매출 비중
2. 인기도로 가중한 평균 단가 (±5%)

카테고리 안에서 어느 상품이 잘 팔리는지는 실행마다 다릅니다.

seed 1~20으로 확인한 결과는 다음과 같습니다.

- 평균 주문 금액: 정답표 데이터(81,249원) 대비 −4% ~ +7%
- 카테고리 매출 비중: 차이 ±2.5%p 이내
- 매출 인정 주문 비율: 약 90% (정답표 데이터 90.8%)

무작위 데이터는 문제 종류가 더 많아 매출 인정 주문 비율이 조금 낮습니다. 평균 주문 금액의 + 쪽 차이에는 미탐지 오류인 단가 입력 실수(`unit_price_typo`)의 영향도 들어 있습니다.

**Git `main`의 `data/raw`는 정답표 데이터입니다.** 워크스루 노트북은 기본(`landing_source = 'git'`)으로 이 파일을 적재합니다. 무작위 데이터를 적재하면(`'random'`, 또는 무작위 CSV를 커밋·푸시) 다음 차이가 생깁니다.

- 노트북과 `sql/`의 기대값 주석(27,055건 등)은 맞지 않게 됩니다. 수업용 사례 O001~O010의 판정은 어느 모드에서나 같습니다.
- 매일 배치는 기본이 `'random'`입니다. 같은 ID의 고객·주문 내용이 매일 통째로 바뀌므로 SCD2 버전, Fact 변경, 소프트 삭제가 대량으로 생깁니다. 실행마다 새 데이터셋을 만드는 방식의 특성입니다.

`tests/`는 `data/raw`를 읽지 않고 정답표 데이터를 임시 폴더에 새로 만들어 씁니다. 그래서 `data/raw`를 무작위 데이터로 바꿔도 테스트에는 영향이 없습니다.

### answer_key.json

| 필드 | 내용 |
|---|---|
| `mode`, `seed` | `random` 또는 `answer-key`, 그리고 다시 만들 때 쓸 seed |
| `volume`, `row_counts` | 이번에 뽑힌 고객 수·주문 목표 수, 파일별 행 수 (수업용 사례 포함) |
| `types[].name`, `kind` | 문제 이름과 종류. `detected`(현재 규칙이 잡음), `undetected`(규칙을 그대로 통과), `normal`(오류처럼 보이지만 정상 처리) |
| `types[].file`, `keys` | 문제를 심은 파일과 그 파일의 업무 키 목록. 주문 ID가 빠진 행은 키가 `null`입니다 |
| `types[].expected` | `detected`일 때 파이프라인이 남겨야 하는 `error_code`와 `action` |
| `types[].related` | 보조 정보. 탈퇴 고객·단종 상품의 ID, 재가입 계정에 옮긴 주문 ID |

`keys`에는 문제를 직접 심은 행만 들어갑니다. 예를 들어 이름이 빠진 고객(`customers_missing_name`)의 주문이 고객 -1로 FLAGGED되는 연쇄 영향은 넣지 않습니다.

무작위 모드는 주문 단위 문제를 서로 다른 완료 주문에 하나씩만 심습니다. 또 문제가 있는 고객·상품의 주문에는 주문 단위 문제를 심지 않습니다. 그래서 `keys`의 모든 행에서 `expected` 판정이 그대로 나옵니다. `undetected`·`normal` 행에는 이슈가 생기지 않습니다(`EXACT_DUPLICATE`는 예외). 매출 인정 여부도 정해진 대로입니다. 지금 `data/raw`가 정답표대로 판정되는지는 다음 명령으로 확인합니다. 빈 목록 대신 `OK`가 출력되면 통과입니다.

```bash
python -c "import json; from pathlib import Path; from src.pipeline import prepare; from tests.test_generate_data import verify; key = json.loads(Path('data/raw/answer_key.json').read_text(encoding='utf-8')); print(verify(key, prepare('data/raw')) or 'OK')"
```

정답표 모드는 예전 생성기와 같은 파일을 만들기 위해 겹침을 피하지 않습니다. 그래서 한 행에 여러 문제가 겹치거나 상위 오류에 가려진 경우가 있습니다(2-1 아래 설명).

## 1. 파일 규모 (정답표 데이터)

| 파일 | 행 수 | 특징 |
|---|---:|---|
| customers.csv | 2,028 | 지역 17개(인구 비례), 지역 누락 52명(→ Unknown), 이메일 누락 98명 (생성 고객 기준, 수업용 C002 제외) |
| products.csv | 151 | 8개 카테고리, 가격 1,000원 ~ 300,000원 |
| orders.csv | 30,081 | 성장 추세, 주말·11~12월 성수기, 완료 약 92% / 취소 약 5% / 대기 약 2.5% |
| order_items.csv | 66,262 | 주문당 1~5줄(평균 약 2.2), 12% 는 프로모션 단가 |
| payments.csv | 31,096 | 완료 주문의 8% 는 실패 후 성공 |
| 합계 | 129,618 | 약 5MB |

## 2. 심어 둔 품질 문제

괄호 안의 이름은 `answer_key.json`의 `types[].name`입니다.

### 2-1. 모든 모드 (건수는 정답표 데이터 기준)

| 문제 | 정답표 건수 | 파이프라인 판정 (error_code → action) |
|---|---:|---|
| 완전 중복 행: 고객 20 (`customers_exact_duplicate`), 상품 1 (`products_exact_duplicate`), 주문 150 (`orders_exact_duplicate`), 상세 200 (`order_items_exact_duplicate`), 결제 100 (`payments_exact_duplicate`) | 471 (+수업용 사례 2) | EXACT_DUPLICATE → REMOVED |
| 같은 주문 ID, 다른 금액 (`orders_key_conflict`) | 40 | KEY_CONFLICT → QUARANTINED |
| 같은 고객 ID, 다른 지역 (`customers_key_conflict`, 무작위 모드는 이메일이 다른 경우도 있음) | 5 | KEY_CONFLICT → QUARANTINED (그 고객의 주문은 고객 -1 로 적재, DEPENDENCY_ERROR) |
| 주문 ID 누락 (`orders_missing_order_id`) | 15 | INVALID_VALUE → QUARANTINED |
| 주문 금액 "N/A" (`orders_invalid_amount`) / 없는 날짜 (`orders_invalid_date`) / 알 수 없는 상태 (`orders_unknown_status`) | 10 / 10 / 10 | INVALID_VALUE → QUARANTINED |
| 상세 수량 누락 (`items_missing_quantity`) / 수량 0 (`items_zero_quantity`) | 60 / 15 | INVALID_VALUE → QUARANTINED, 주문은 DEPENDENCY_ERROR |
| 결제 시각 누락 (`payments_missing_paid_at`) / 알 수 없는 결제 상태 (`payments_unknown_status`) | 20 / 10 | INVALID_VALUE → QUARANTINED, 주문은 DEPENDENCY_ERROR |
| 없는 고객 참조 (`orders_unknown_customer`) | 80 | INVALID_REFERENCE → FLAGGED (customer_key = -1), 주문은 DEPENDENCY_ERROR |
| 없는 상품 참조 (`items_unknown_product`) | 60 | INVALID_REFERENCE → FLAGGED (product_key = -1), 주문은 DEPENDENCY_ERROR |
| 주문 없는 상세 (`orphan_items`) / 주문 없는 결제 (`orphan_payments`) | 40 / 30 | INVALID_REFERENCE → 상세는 QUARANTINED, 결제는 FLAGGED (has_valid_order = FALSE) |
| 성공 결제 2건 (`double_success_payment`) | 60 | SUCCESS_PAYMENT_COUNT → FLAGGED |
| 완료 주문인데 결제 없음 (`completed_without_payment`) | 40 | SUCCESS_PAYMENT_COUNT → FLAGGED |
| 결제 금액 불일치 (`payment_amount_mismatch`) / 주문 금액 불일치 (`order_amount_mismatch`) | 80 / 60 | AMOUNT_MISMATCH → FLAGGED |
| 완료 주문인데 상세 없음 (`completed_without_items`) | 30 | MISSING_ITEMS → FLAGGED |

정답표 데이터에서 건수는 심은 개수입니다. 한 행에 여러 문제가 겹치거나 상위 오류에 가려진 경우가 있어 3절의 이슈 수와 정확히 같지는 않습니다.
무작위 모드에서는 각 건수가 규모에 비례하고 실행마다 0.6~1.4배로 달라집니다. 주문 없는 상세·결제는 다음 추출에 들어올 주문(마지막 주문 ID 다음 번호)을 가리켜, 주문 헤더가 늦게 도착하는 상황을 흉내 냅니다.

### 2-2. 무작위 모드에만 : 현재 규칙이 잡는 현실적인 오류

기준 건수는 고객 2,000명·주문 30,000건일 때이고 실행마다 0.6~1.4배로 달라집니다. 상품 단위 문제는 실행마다 0~1개입니다.

| 문제 | 예 | 판정 (error_code → action) | 기준 건수 |
|---|---|---|---:|
| 다른 시스템의 주문 상태 표기 (`orders_status_label`) | `Completed`, `COMPLETED`, `완료` | INVALID_VALUE → QUARANTINED | 12 |
| PG사의 결제 상태 표기 (`payments_status_label`) | `Succeeded`, `SUCCESS`, `paid`, `결제완료` | INVALID_VALUE → QUARANTINED | 10 |
| 금액 서식 (`orders_amount_format`) | `12,000`, `12000원`, `12000.0` | INVALID_VALUE → QUARANTINED | 12 |
| 엑셀 저장으로 바뀐 숫자 (`items_number_format`) | 수량 `1.0`, 단가 `4500.00` | INVALID_VALUE → QUARANTINED | 10 |
| 달력에 없는 날짜 (`orders_impossible_date`) | 평년 `2025-02-29`, `2026-04-31` | INVALID_VALUE → QUARANTINED | 8 |
| 기본값으로 채운 금액 (`orders_sentinel_amount`) | `9999999999999` (입력 상한 10^12 초과) | INVALID_VALUE → QUARANTINED | 5 |
| MySQL 0 날짜 (`payments_zero_datetime`) | `0000-00-00 00:00:00` | INVALID_VALUE → QUARANTINED | 8 |
| 부분 환불을 음수 결제로 기록 (`refund_as_negative_payment`) | 성공 결제 `-12000` 추가 | INVALID_VALUE → QUARANTINED, 주문은 DEPENDENCY_ERROR | 8 |
| 분할 결제 (`split_payment`) | 포인트 + 카드, 성공 결제 2건의 합이 주문 금액 | SUCCESS_PAYMENT_COUNT → FLAGGED | 20 |
| 고객 이름 누락 (`customers_missing_name`) | 이름이 빈 값 | INVALID_VALUE → QUARANTINED, 그 고객의 주문은 고객 -1 로 FLAGGED | 4 |
| 탈퇴 고객 삭제 (`customers_withdrawn`) | 고객 마스터에서만 삭제, 주문은 남음 | 그 주문이 INVALID_REFERENCE → FLAGGED | 3명 |
| 단종 상품 삭제 (`products_discontinued`) | 상품 마스터에서만 삭제, 상세는 남음 | 그 상세가 INVALID_REFERENCE → FLAGGED | 0~1개 |
| 카테고리 누락 (`products_missing_category`) | 카테고리가 빈 값 | INVALID_VALUE → QUARANTINED, 그 상품의 상세는 상품 -1 로 FLAGGED | 0~1개 |
| 상품명 변경 중 추출 (`products_key_conflict`) | 같은 상품 ID에 `... (리뉴얼)` 행 | KEY_CONFLICT → QUARANTINED | 0~1개 |

분할 결제는 실제로는 정상 거래입니다. 하지만 지금 규칙은 성공 결제가 정확히 1건일 때만 매출로 인정하므로 매출에서 빠집니다. 규칙의 한계를 보여 주는 사례입니다.
단종 상품과 카테고리 누락은 판매가 적은 상품 30개 중에서 고르지만, 한 상품의 상세가 수십~수백 건이라 DEPENDENCY_ERROR 주문 수가 크게 늘 수 있습니다.

### 2-3. 무작위 모드에만 : 현재 규칙으로 잡지 못하는 오류 (미탐지)

이 오류들은 이슈 없이 MART까지 그대로 들어갑니다. 금액 대사는 맞도록 만들었으므로 17개 품질 검사도 통과합니다. 규칙 추가 실습에 쓸 수 있도록 잡는 방법을 함께 적었습니다.

| 문제 | 영향 | 기준 건수 | 잡으려면 |
|---|---|---:|---|
| 지역 표기 변형 (`region_alias`): `서울특별시`, `Seoul`, `경기도` 등 | 지역별 매출이 여러 값으로 나뉨. `서울`만 보는 지역 행 정책(STEP 9)에서 빠짐 | 40 | 표준 지역 코드 매핑표, 허용 값 검사 |
| 이메일 형식 오류 (`email_malformed`): `a@@b`, `@` 누락, 도메인 불완전 | 연락 불가 고객이 정상으로 적재됨 | 20 | 형식 정규식 검사 (FLAGGED) |
| 재가입 중복 계정 (`duplicate_customer_account`): 이름·이메일이 같은 새 ID | 고객 수가 부풀고 한 사람의 구매가 둘로 나뉨 | 8 | 이름+이메일 중복 검사 |
| 결제가 주문보다 먼저 (`paid_before_order`): 결제 시각이 주문일보다 1~3일 이름 | 결제일 기준 집계와 주문일 기준 집계가 어긋남 | 15 | `paid_at::DATE >= order_date` 검사 |
| 미래 주문일 (`future_order_date`): 추출 기간(~2026-10-31) 뒤 1~45일 | 아직 오지 않은 날짜에 매출이 잡힘 | 10 | 주문일 ≤ 추출일 검사 |
| 단가 0원 (`zero_unit_price`): 2줄 이상 주문의 한 줄 | 상품 매출이 줄어듦 (사은품과 구분 불가) | 10 | 단가 > 0, 사은품 예외 규칙 |
| 단가 입력 실수 (`unit_price_typo`): 10배·100배 | 매출이 크게 부풀어 오름 | 6 | 상품별 정상 가격 범위 검사 |
| 환불 누락 (`cancelled_with_success_payment`): 취소 주문에 성공 결제가 남음 | 매출에서는 빠지지만 이슈로 남지 않아 결제 요약의 성공 금액에 포함됨 | 12 | 취소 주문의 성공 결제를 FLAGGED |

### 2-4. 정상 처리되는 값

| 값 | 처리 | 비율·건수 |
|---|---|---|
| 이메일 누락 (`customers_missing_email`) | 선택값, NULL 유지 | 고객의 약 5% |
| 지역 누락 (`customers_missing_region`) | 선택값, `Unknown`으로 적재 | 고객의 약 3% |
| 앞뒤 공백 (`padded_values`, 무작위 모드만): 주문 상태 ` completed`, 결제의 주문 ID `O123 `, 상세의 상품 ID ` P1001` | TRIM 후 정상 값과 같음. 이슈 없이 매출 인정 | 기준 60건 |

## 3. 정답 — 정답표 데이터(`--answer-key`)의 파이프라인 결과

정답표 데이터라면 Python 로컬 실행(`python -m src.pipeline --dry-run`), Snowflake 노트북, `python -m src.pipeline --load` 모두 같은 값이 나와야 합니다.
`tests/test_core.py`, `tests/test_mart.py` 가 이 표를 검사합니다. 무작위 데이터의 결과는 `--dry-run` 보고서로 확인하세요.

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
