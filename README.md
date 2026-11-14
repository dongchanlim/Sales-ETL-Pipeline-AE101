# Sales ETL Pipeline · AE101

CSV → **RAW → CORE → MART(스타 스키마)** → Streamlit in Snowflake.
SQL·Python·데이터 모델링·ETL·Git을 배운 학습자를 위한 1주 개인 프로젝트의 실행 가능한 참조 구현입니다.

같은 로직을 세 가지 방법으로 실행할 수 있고, 결과는 모두 같습니다.

| 방법 | 명령 / 파일 | Snowflake 필요 |
|---|---|---|
| Snowflake Notebook (기준) | `notebooks/ae101_enterprise_walkthrough.ipynb` | 예 |
| Python 로컬 | `python -m src.pipeline --dry-run` | 아니요 |
| Python → Snowflake | `python -m src.pipeline --load` | 예 |
| 매일 자동 실행 (Task Graph) | `orchestration/daily_schedule.sql` → `notebooks/ae101_daily_batch.ipynb` | 예 |

## 바로 실행하기 — Snowflake 없이

Python 3.11 이상에서 저장소 루트 기준으로 실행합니다. 로컬 실행은 외부 패키지 없이 동작합니다.

```bash
python -m src.pipeline --dry-run
python -m unittest discover -s tests -v
```

저장소에 들어 있는 예제 데이터(정답표 데이터)는 2025-01 ~ 2026-10 기간의 원본 129,618행(고객 2,028 · 상품 151 · 주문 30,081 · 주문 상세 66,262 · 결제 31,096)입니다.
행의 약 2~3%에 완전 중복, 키 충돌, 필수값 누락, 참조 오류, 중복 성공 결제, 금액 불일치가 섞여 있습니다.
매출로 인정되는 주문은 **27,055건**, 총매출은 **2,198,198,700원**입니다. 제외된 주문도 사유와 함께 MART에 적재됩니다.
각 파일 맨 앞의 수업용 사례 40행(O001~O010 등)에서는 O001·O002만 매출로 인정됩니다.
`python scripts/generate_data.py`를 실행하면 같은 분포로 만든 새 무작위 데이터가 `data/raw`에 생깁니다. 현실적인 오류와 현재 규칙으로 잡지 못하는 오류도 섞여 들어가고, 정답은 `answer_key.json`에 기록됩니다. 위 숫자는 정답표 데이터 기준입니다. 정답표 데이터로 되돌리려면 `--answer-key`를 붙여 실행합니다.
데이터 구성과 정답표는 [데이터 생성](docs/data_generation.md)을 참고하세요.

`--dry-run`은 `outputs/<load_id>.json` 보고서를 씁니다. `--state outputs/mart_state.json`을 함께 주면 MART 상태를 저장하고 다음 실행에서 이어받아, SCD2 이력과 소프트 삭제를 로컬에서도 확인할 수 있습니다. `outputs/`는 Git에서 제외됩니다.

## 프로젝트 구조

| 경로 | 역할 |
|---|---|
| `data/raw/*.csv`, `answer_key.json` | 고객·상품·주문·주문 상세·결제 시도 합성 파일과 심은 문제의 정답 |
| `scripts/generate_data.py` | 합성 데이터 생성기 (기본: 실행마다 새 무작위 데이터, `--seed` 재현, `--answer-key` 정답표 데이터) |
| `notebooks/ae101_enterprise_walkthrough.ipynb` | 전체 워크스루 (STEP 0~12). **로직의 기준** |
| `notebooks/ae101_mart_etl.ipynb` | MART만 생성·반영하는 노트북 (CORE 이후) |
| `notebooks/ae101_daily_batch.ipynb` | 매일 배치 노트북 (워크스루 STEP 2~7 셀 + 가드·게이트). `scripts/build_daily_notebook.py` 로 생성 |
| `orchestration/` | 매일 배치 스케줄 설치(`daily_schedule.sql`)와 실패·지연 알림(`daily_alert.sql`, 선택) |
| `sql/00_setup.sql` ~ `11_security.sql` | 노트북 셀을 단계별 파일로 나눈 것. 노트북과 글자 그대로 같음 |
| `src/extract.py` | CSV → RAW 형태 (src_file, src_row) |
| `src/core.py` | CORE 정제·매출 판정 (`sql/03`, `04`) |
| `src/mart.py` | SCD2 차원·Fact MERGE·소프트 삭제·품질 검사 (`sql/06` ~ `09`) |
| `src/reports.py` | 리포트 뷰 계산 (`sql/10`) |
| `src/load.py` | Snowflake 적재: RAW INSERT 후 `sql/` 파일 순서대로 실행, 결과 대사 |
| `src/pipeline.py` | CLI (`--dry-run`, `--setup`, `--load`) |
| `streamlit/` | 매출·품질 대시보드 (`streamlit_app.py`, 배포 설정 `snowflake.yml`, `pyproject.toml`) |
| `tests/` | 정답값·SCD2·멱등성·노트북 동기화·데이터 생성기 테스트, 선택적 Snowflake 통합 테스트. 정답표 데이터를 임시 폴더에 만들어 쓰므로 `data/raw`와 무관 |
| `docs/` | ERD·업무 규칙·실행 순서·검증·리뷰 문서 |

## Snowflake 에서 실행 — 노트북

1. [Snowflake Git 저장소](https://docs.snowflake.com/en/developer-guide/git/git-overview)로 이 저장소를 연결합니다. 노트북은 `AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE` 이라는 저장소 객체 이름을 가정합니다.
   STEP 3은 `@AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE/branches/main/data/raw/` 의 CSV를 스테이지 `@RAW.LANDING/current/` 로 복사한 뒤 읽습니다. STEP 3-0의 `landing_source`를 `'random'`으로 바꾸면 Snowflake 안에서 생성기 프로시저(`RAW.GENERATE_LANDING_FILES`)가 새 무작위 데이터를 만들어 스테이지 파일을 바꿉니다. 매일 배치 노트북은 이것이 기본입니다. 다른 브랜치를 쓰려면 그 경로의 `main`만 바꾸고, 먼저 `ALTER GIT REPOSITORY ... FETCH;`(STEP 0)로 최신 상태를 가져옵니다.
2. Snowsight → Notebooks → Import .ipynb 로 `notebooks/ae101_enterprise_walkthrough.ipynb`를 가져옵니다.
3. 노트북 설정에서 Query warehouse를 고릅니다. `AE101_DB`는 데이터베이스 이름이라 `USE WAREHOUSE`에 쓸 수 없습니다.
4. 셀을 위에서 아래로 실행합니다. STEP 2~8은 세션 변수를 쓰므로 같은 세션에서 이어서 실행합니다.
5. STEP 9(보안)는 Enterprise Edition 이상에서만 동작합니다. STEP 9는 MART 뷰에 `FUTURE VIEWS` 조회 권한도 주므로, 이후 STEP 8을 다시 실행해 뷰가 새로 만들어져도 분석가·관리자 역할 권한이 유지됩니다.

워크시트에서 실행하려면 `sql/` 파일을 번호 순서대로 열어 실행해도 같습니다.

## Snowflake 에서 실행 — Python

1. 로컬 가상환경을 만들고 패키지를 설치합니다.

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`requirements.txt`는 지원 범위이며 잠금 파일이 아닙니다. 실제 연결과 버전은 자신의 계정에서 확인하고 기록하세요.

2. 저장소 밖 `~/.snowflake/connections.toml`에 이름이 `ae101`인 연결을 만듭니다. 아래 값은 자리표시자입니다.

```toml
[ae101]
account = "YOUR_ORG-YOUR_ACCOUNT"
user = "YOUR_USER"
authenticator = "externalbrowser"
role = "YOUR_PROJECT_ROLE"
warehouse = "YOUR_WAREHOUSE"
```

설정 경로와 인증 방식은 [공식 연결 문서](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect)를 참고하세요. 인증 파일은 저장소에 넣지 않습니다.

3. DB를 만들고 적재합니다.

```bash
python -m src.pipeline --setup     # sql/00_setup.sql (한 번)
python -m src.pipeline --load      # RAW 배치 추가 → sql/03 ~ 10 실행
python -m src.pipeline --load      # 같은 입력 재실행: MART 업무 값은 그대로
```

`--load`는 Snowflake의 `CORE.RUN_SUMMARY`가 로컬 계산과 다르면 MART 반영 전에 `FAILED`로 멈춥니다. 품질 검사가 실패해도 `FAILED`를 기록하고 오류로 끝납니다.
연결 이름은 `SNOWFLAKE_CONNECTION_NAME`, DB는 `AE101_DATABASE`(기본 `AE101_SALES_ENT`)로 바꿀 수 있습니다. 매출 인식 주문이 0건이면 기본으로 중단하며, 의도한 경우에만 `--allow-empty`를 씁니다.

## Streamlit 대시보드

`streamlit/streamlit_app.py` 는 MART 뷰만 읽는 매출·품질 대시보드입니다.

| 탭 | 내용 |
|---|---|
| 개요 | 매출·주문 수·평균 주문 금액·판매 수량·구매 고객 수 (비교 기간 대비 증감), 매출 추이(비교 기간 겹쳐 보기), 카테고리·지역 상위, 요약 문장 |
| 상품 · 카테고리 | 카테고리 성과(비중·증감률), 카테고리 × 월 히트맵, 상품 순위 상위 10/20/50 + CSV |
| 지역 | 지역별 매출·비중·증감·구매 고객·평균 주문 금액 (주문 당시 지역), 상위 5개 지역 추이 + CSV |
| 주문 · 결제 품질 | 매출 인식률, 검증 실패로 빠진 완료 주문 금액, 제외 사유, 매출 인식률·결제 성공률 추이, 결제 상태 |
| 데이터 운영 | 최근 실행 상태, 실행 이력 30회, 실행별 품질 검사 17개와 데이터 이슈 요약 + CSV |

사이드바에서 기간(최근 30일/90일/12개월, 올해 누적, 전체, 직접 선택), 비교 기준(이전 동일 기간/전년 동기/없음), 집계 단위(일/주/월), 지역, 카테고리를 고릅니다.
기간 프리셋은 오늘이 아니라 **마지막 주문일** 기준입니다. 상단에는 데이터 기준 시각과 최근 실행 상태가 보이고, 실행이 실패했거나 24시간 넘게 갱신되지 않으면 경고가 뜹니다.
쿼리 결과는 10분 동안 캐시되며, 사이드바의 버튼으로 바로 새로 읽을 수 있습니다.

| 파일 | 역할 |
|---|---|
| `streamlit_app.py` | 대시보드 코드 |
| `snowflake.yml` | 배포 정의 (앱 제목, query warehouse, compute pool, 올릴 파일) |
| `pyproject.toml` | 패키지 (`streamlit[snowflake]` 에 Snowpark·pandas·Altair 포함) |
| `.streamlit/config.toml` | Streamlit 테마 설정 |

배포 순서는 다음과 같습니다.

1. `sql/10_report_views.sql` (노트북 STEP 8) 을 최신으로 실행해 대시보드용 뷰(`V_SALES_LINE`, `V_PAYMENT_DAILY`, `V_RUN_HISTORY`, `V_DQ_RESULTS`, `V_DATA_ISSUE_SUMMARY`)를 만듭니다.
2. `SHOW WAREHOUSES;` 로 실제 웨어하우스 이름을 확인합니다. `snowflake.yml` 의 `query_warehouse` 는 `env.AE101_WAREHOUSE`(기본 `COMPUTE_WH`)를 읽으므로, 기본값을 고치거나 배포할 때 `--env AE101_WAREHOUSE=<웨어하우스>` 또는 같은 이름의 환경변수로 넘깁니다. `AE101_SALES_ENT` 는 데이터베이스 이름이라 쓸 수 없습니다.
3. Snowsight 에서 앱을 만들거나 `streamlit/` 폴더에서 `snow streamlit deploy --replace` 를 실행합니다. CLI로 배포하면 앱은 `AE101_SALES_ENT.MART.AE101_SALES_DASHBOARD` 에 만들어집니다. 웨어하우스 런타임과 컨테이너 런타임 모두 동작하도록 작성했습니다.
4. 앱 소유 역할에는 웨어하우스 사용 권한과 `AE101_SALES_ENT.MART` 뷰 조회 권한이 필요합니다. AUDIT 테이블 권한은 필요 없습니다. ACCOUNTADMIN이 아닌 역할이 앱을 소유한다면 아래처럼 권한을 줍니다.

   ```sql
   GRANT USAGE ON DATABASE AE101_SALES_ENT TO ROLE <APP_ROLE>;
   GRANT USAGE ON SCHEMA AE101_SALES_ENT.MART TO ROLE <APP_ROLE>;
   GRANT SELECT ON ALL VIEWS IN SCHEMA AE101_SALES_ENT.MART TO ROLE <APP_ROLE>;
   GRANT SELECT ON FUTURE VIEWS IN SCHEMA AE101_SALES_ENT.MART TO ROLE <APP_ROLE>;
   GRANT USAGE ON WAREHOUSE <웨어하우스> TO ROLE <APP_ROLE>;
   ```

5. 전체 기간을 고르면 매출 ₩21.98억(2,198,198,700원) · 주문 27,055건 · 평균 ₩81,249 가 나와야 합니다.

Streamlit in Snowflake 는 **앱 소유 역할 권한**으로 실행됩니다. 행 접근 정책을 적용했다면 보이는 지역은 보는 사람이 아니라 앱 소유 역할이 정합니다. 지역별로 다른 화면이 필요하면 지역 역할마다 앱을 따로 배포하세요.
`Object 'AE101_SALES_ENT.MART.V_SALES_LINE' does not exist or not authorized` 가 나오면 1단계(STEP 8)를 이 저장소의 최신 노트북·SQL로 다시 실행했는지 먼저 확인합니다(`SHOW VIEWS IN SCHEMA AE101_SALES_ENT.MART;`).
이 앱은 Snowflake 세션을 사용하므로 로컬 `streamlit run` 대상이 아닙니다. [공식 Streamlit 안내](https://docs.snowflake.com/en/developer-guide/streamlit/about-streamlit)

## 매일 자동 실행

Snowflake Task Graph가 매일 06:00(Asia/Seoul)에 `notebooks/ae101_daily_batch.ipynb` 를 실행합니다. 이 노트북에는 워크스루 STEP 2~7 셀만 들어 있습니다.
STEP 1(DDL), STEP 8(리포트 뷰), STEP 9(보안)는 처음 한 번만 실행하고 매일 다시 실행하지 않습니다. STEP 1을 반복하면 `DIM_DATE` 등이 다시 만들어져 STEP 9의 권한이 사라집니다.

1. 워크스루 STEP 1·8(필요하면 9)을 한 번 실행합니다.
2. `orchestration/daily_schedule.sql` 의 `COMPUTE_WH` 를 실제 웨어하우스 이름으로 바꿔 실행합니다. 노트북 배포, 루트 태스크, 실패 정리용 파이널라이저가 `AE101_SALES_ENT.OPS` 에 만들어집니다.
3. `EXECUTE TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH;` 로 한 번 실행해 `MART.V_RUN_HISTORY` 가 `SUCCESS` 인지 확인합니다.
4. (선택) `orchestration/daily_alert.sql` 로 실패·지연 메일 알림을 켭니다.

스케줄이 켜져 있는 동안 워크스루를 직접 실습하려면 먼저 태스크를 `SUSPEND` 하세요. 스케줄러 비교, 실패 처리, 운영 방법은 [매일 배치 스케줄링](docs/scheduling.md)에 있습니다.

## 학습 문서

- [데이터 모델 · ERD](docs/erd.md)
- [파이프라인 실행 순서와 복구](docs/execution_flow.md)
- [매일 배치 스케줄링](docs/scheduling.md)
- [데이터 사전](docs/data_dictionary.md)
- [처리 규칙·지표 정의](docs/data_rules.md)
- [검증 결과와 클라우드 검증 방법](docs/validation_results.md)
- [AI 활용·리뷰 기록](docs/ai_review_log.md)
- [데이터 생성과 정답표](docs/data_generation.md)

## 범위와 한계

- 작은 교육용 데이터의 메모리 기반 ETL이며, 대규모 파일·오케스트레이터·동시 실행은 범위 밖입니다. **같은 DB에는 한 번에 하나의 실행만** 허용합니다.
- 입력은 매번 전체 스냅샷입니다. 증분 파일만 넣으면 빠진 행이 소프트 삭제됩니다. CDC는 다루지 않습니다.
- MART 반영은 셀(파일) 단위라 품질 검사 실패 시 자동으로 되돌리지 않습니다. 상태를 확인하고 다시 실행하거나 Time Travel로 복구합니다.
- RAW와 AUDIT는 실행마다 누적됩니다. 교육 종료 후 전용 DB를 정리하세요.
- 환불·수수료·정산·다중 통화는 다루지 않습니다.
- 로컬 테스트 통과는 실제 Snowflake SQL·권한·앱 배포 성공을 의미하지 않습니다. [검증 상태](docs/validation_results.md)를 확인하세요.
