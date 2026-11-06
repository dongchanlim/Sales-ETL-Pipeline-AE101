# 검증 결과

2026-11-05 기준입니다. 로컬 Python 실행과 SQL 로직 대조는 완료했고, 실제 Snowflake 계정 실행·Streamlit 배포는 아직 하지 않았습니다.

## 로컬 실측 결과 (`python -m src.pipeline --dry-run`)

| 항목 | 결과 |
|---|---:|
| 전체 원본 행 | 129,618 |
| 제거된 완전 중복 (REMOVED) | 473 |
| 격리된 고유 원본 행 (QUARANTINED) | 441 |
| 표시만 한 이슈 (FLAGGED) | 559 |
| 매출 인식 주문 | 27,055 |
| 총매출 | 2,198,198,700원 |
| 평균 주문 금액 | 약 81,249원 |
| MART 행 수 (DIM_CUSTOMER / DIM_PRODUCT / DIM_DATE) | 1,998 / 151 / 4,019 |
| MART 행 수 (FACT_SALES_LINE / FACT_PAYMENT / FACT_ORDER_LIFECYCLE) | 65,789 / 30,966 / 29,802 |
| 품질 검사 17개 | 모두 0 |

전체 정답표는 [데이터 생성과 정답표](data_generation.md)에 있습니다.

## Python ↔ SQL 로직 대조

`src/`(Python)와 `sql/`(= 노트북 셀)이 같은 결과를 내는지, `sql/03`·`04`·`06`·`07`·`08`·`10`을 DuckDB로 실행해 행 단위로 비교했습니다. 비교에 쓴 DuckDB는 Snowflake 함수 일부(`TRY_TO_NUMBER`, `TO_DATE` 등)를 같은 의미로 바꿔 실행한 것이므로 Snowflake 실행 증명은 아닙니다.

| 실행 | 입력 | 결과 |
|---|---|---|
| 1회차 | `data/raw` 그대로 | 요약 6개 지표, 이슈 1,473건, 차원 2개, Fact 3개, 품질 검사 17개, 리포트 뷰 9개 모두 일치 |
| 2회차 | C002 지역을 부산으로 변경 | SCD2 버전(닫힌 Unknown 버전 + 새 부산 버전), As-Was / As-Is 지역 매출 일치 |
| 3회차 | 주문 상세 1행 삭제 | 해당 행 `is_deleted = TRUE` 소프트 삭제 및 나머지 결과 일치 |

## 자동 테스트

```bash
python -m unittest discover -s tests -v
```

로컬 테스트 23개 통과, Snowflake 통합 테스트 1개는 명시적 설정이 없어 건너뜁니다.

| 파일 | 확인 내용 |
|---|---|
| `test_core.py` | RUN_SUMMARY, 이슈 action·코드별 건수, 제외 사유, 수업용 사례 O001~O010, 숫자 파싱, 필수 헤더 |
| `test_mart.py` | MART 행 수, 품질 검사 17개, Unknown 연결, 리포트·대시보드 뷰 값, 같은 입력 재실행 멱등성, SCD2, 소프트 삭제 |
| `test_rerun.py` | 행 순서 변경·전체 중복에도 결과 불변, (선택) Snowflake 2회 적재 |
| `test_load.py` | 가짜 연결로 `sql/` 파일 실행 순서, CORE 대사 불일치·품질 검사 실패·매출 0건 처리 |
| `test_notebook_sync.py` | `sql/` 파일과 노트북 셀이 글자 그대로 같은지 |

`test_load.py`는 호출 순서만 확인하며 Snowflake SQL 실행 증명은 아닙니다.

## 대시보드 로컬 점검

`streamlit/streamlit_app.py` 를 DuckDB 로 만든 같은 MART 뷰에 연결해(가짜 Snowpark 세션) Streamlit AppTest 와 브라우저로 실행했습니다.
5개 탭, 기간 프리셋 6종, 비교 기준 3종, 집계 단위 3종, 지역·카테고리 필터 조합에서 예외 없이 렌더링되었고, 전체 기간 매출 2,198,198,700원 · 주문 27,055건, 서울 필터 매출 420,094,900원이 정답표와 같았습니다.
Snowflake 런타임(권한, 패키지, 컨테이너 런타임)에서의 동작은 별도로 확인해야 합니다.

`streamlit/snowflake.yml` 은 Snowflake CLI 3.32 의 프로젝트 정의 로더로 읽어 확인했습니다. 앱 식별자 `AE101_SALES_ENT.MART.AE101_SALES_DASHBOARD`, 올릴 파일 3개, `query_warehouse` 기본값(`COMPUTE_WH`)과 `AE101_WAREHOUSE` 환경변수 덮어쓰기가 의도대로 해석되었습니다. 실제 `snow streamlit deploy` 는 실행하지 않았습니다.

## 실제 Snowflake 재실행 테스트

학습 DB와 별개로 이름이 `_TEST`로 끝나는 폐기 가능한 DB를 만들어 실행합니다.

```bash
# macOS / Linux
export AE101_DATABASE=AE101_SALES_ENT_TEST
python -m src.pipeline --setup
export AE101_RUN_SNOWFLAKE_TESTS=1
python -m unittest tests.test_rerun.SnowflakeRerunTests -v
```

Windows PowerShell에서는 `$env:AE101_DATABASE="AE101_SALES_ENT_TEST"`, `$env:AE101_RUN_SNOWFLAKE_TESTS="1"`로 지정합니다.
테스트는 실제 적재를 두 번 수행하고 FACT_SALES_LINE 업무 값을 비교합니다. 끝나면 환경변수를 해제하고 아래 표를 채우세요.

| 클라우드 검증 | 상태 |
|---|---|
| `sql/00_setup.sql` DDL | 미실행 |
| 노트북 전체 실행 (STEP 0~11) | 미실행 |
| `python -m src.pipeline --load` 2회 | 미실행 |
| 보안 정책 (`sql/11_security.sql`, Enterprise) | 미실행 |
| Streamlit 대시보드 (Snowflake 배포) | 미실행 |
