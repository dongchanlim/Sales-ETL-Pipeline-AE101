# Sales ETL Pipeline · AE101

CSV → **RAW → CORE → MART(스타 스키마)** → Streamlit in Snowflake.
SQL·Python·데이터 모델링·ETL·Git을 배운 학습자를 위한 1주 개인 프로젝트의 실행 가능한 참조 구현입니다.

같은 로직을 세 가지 방법으로 실행할 수 있고, 결과는 모두 같습니다.

| 방법 | 명령 / 파일 | Snowflake 필요 |
|---|---|---|
| Snowflake Notebook (기준) | `notebooks/ae101_enterprise_walkthrough.ipynb` | 예 |
| Python 로컬 | `python -m src.pipeline --dry-run` | 아니요 |
| Python → Snowflake | `python -m src.pipeline --load` | 예 |

## 바로 실행하기 — Snowflake 없이

Python 3.11 이상에서 저장소 루트 기준으로 실행합니다. 로컬 실행은 외부 패키지 없이 동작합니다.

```bash
python -m src.pipeline --dry-run
python -m unittest discover -s tests -v
```

예제 데이터는 2025-01 ~ 2026-10 기간의 원본 129,618행(고객 2,028 · 상품 151 · 주문 30,081 · 주문 상세 66,262 · 결제 31,096)입니다.
행의 약 2~3%에 완전 중복, 키 충돌, 필수값 누락, 참조 오류, 중복 성공 결제, 금액 불일치가 섞여 있습니다.
매출로 인정되는 주문은 **27,055건**, 총매출은 **2,198,198,700원**입니다. 제외된 주문도 사유와 함께 MART에 적재됩니다.
각 파일 맨 앞의 수업용 사례 40행(O001~O010 등)에서는 O001·O002만 매출로 인정됩니다.
데이터 구성과 정답표는 [데이터 생성](docs/data_generation.md)을 참고하세요.

`--dry-run`은 `outputs/<load_id>.json` 보고서를 씁니다. `--state outputs/mart_state.json`을 함께 주면 MART 상태를 저장하고 다음 실행에서 이어받아, SCD2 이력과 소프트 삭제를 로컬에서도 확인할 수 있습니다. `outputs/`는 Git에서 제외됩니다.

## 프로젝트 구조

| 경로 | 역할 |
|---|---|
| `data/raw/*.csv` | 고객·상품·주문·주문 상세·결제 시도 합성 파일 |
| `scripts/generate_data.py` | 합성 데이터 생성기 (seed 고정, 재현 가능) |
| `notebooks/ae101_enterprise_walkthrough.ipynb` | 전체 워크스루 (STEP 0~12). **로직의 기준** |
| `notebooks/ae101_mart_etl.ipynb` | MART만 생성·반영하는 노트북 (CORE 이후) |
| `sql/00_setup.sql` ~ `11_security.sql` | 노트북 셀을 단계별 파일로 나눈 것. 노트북과 글자 그대로 같음 |
| `src/extract.py` | CSV → RAW 형태 (src_file, src_row) |
| `src/core.py` | CORE 정제·매출 판정 (`sql/03`, `04`) |
| `src/mart.py` | SCD2 차원·Fact MERGE·소프트 삭제·품질 검사 (`sql/06` ~ `09`) |
| `src/reports.py` | 리포트 뷰 계산 (`sql/10`) |
| `src/load.py` | Snowflake 적재: RAW INSERT 후 `sql/` 파일 순서대로 실행, 결과 대사 |
| `src/pipeline.py` | CLI (`--dry-run`, `--setup`, `--load`) |
| `streamlit/streamlit_app.py` | 매출·품질 대시보드 (MART.V_* 뷰) |
| `tests/` | 정답값·SCD2·멱등성·노트북 동기화 테스트, 선택적 Snowflake 통합 테스트 |
| `docs/` | ERD·업무 규칙·실행 순서·검증·리뷰 문서 |

## Snowflake 에서 실행 — 노트북

1. [Snowflake Git 저장소](https://docs.snowflake.com/en/developer-guide/git/git-overview)로 이 저장소를 연결합니다. 노트북은 `AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE` 이라는 저장소 객체 이름을 가정합니다.
2. Snowsight → Notebooks → Import .ipynb 로 `notebooks/ae101_enterprise_walkthrough.ipynb`를 가져옵니다.
3. 노트북 설정에서 Query warehouse를 고릅니다. `AE101_DB`는 데이터베이스 이름이라 `USE WAREHOUSE`에 쓸 수 없습니다.
4. 셀을 위에서 아래로 실행합니다. STEP 2~8은 세션 변수를 쓰므로 같은 세션에서 이어서 실행합니다.
5. STEP 9(보안)는 Enterprise Edition 이상에서만 동작합니다.

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

## Streamlit 실행

1. Snowsight에서 Streamlit 앱을 만들고 `AE101_SALES_ENT` DB와 사용 가능한 warehouse를 선택합니다.
2. `streamlit/streamlit_app.py`를 앱 코드로 사용하고 `streamlit`, `snowflake-snowpark-python`, `pandas` 패키지를 추가합니다.
3. 앱 실행 역할은 MART 뷰와 AUDIT 조회 권한이 있어야 합니다. 행 접근 정책을 적용했다면 역할에 허용된 지역만 보입니다.
4. 총매출 2,198,198,700원 · 주문 27,055건 · 평균 약 81,249원을 확인합니다.

이 앱은 Snowflake 활성 세션을 사용하므로 로컬 `streamlit run` 대상이 아닙니다. [공식 Streamlit 안내](https://docs.snowflake.com/en/developer-guide/streamlit/about-streamlit)

## 학습 문서

- [데이터 모델 · ERD](docs/erd.md)
- [파이프라인 실행 순서와 복구](docs/execution_flow.md)
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
