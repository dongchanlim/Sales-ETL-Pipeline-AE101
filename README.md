# Sales ETL Pipeline · AE101

CSV → Python 정제·검증 → Snowflake DW → Streamlit in Snowflake.
SQL·Python·데이터 모델링·ETL·Git을 배운 학습자를 위한 1주 개인 프로젝트의 실행 가능한 참조 구현입니다.

## 바로 실행하기 — Snowflake 없이

Python 3.11 이상에서 저장소 루트 기준으로 실행합니다. 로컬 검증은 외부 패키지 없이 동작합니다.

```bash
python -m src.pipeline --dry-run
python -m unittest discover -s tests -v
```

예제 데이터는 2025-01 ~ 2026-10 기간의 원본 129,618행(고객 2,028 · 상품 151 · 주문 30,081 · 주문 상세 66,262 · 결제 31,096)입니다.
행의 약 2~3%에 완전 중복, 키 충돌, 필수값 누락, 참조 오류, 중복 성공 결제, 금액 불일치가 섞여 있습니다.
정상 주문은 **27,055건**, 총매출은 **2,198,198,700원**, 주문 상세는 **59,921행**입니다.
각 파일 맨 앞의 수업용 사례 40행(O001~O010 등)에서는 O001·O002만 매출로 인정됩니다.
데이터 구성과 심어 둔 문제 목록은 [데이터 생성](docs/data_generation.md)을 참고하세요.
실행별 JSON 보고서는 `outputs/<run_id>.json`에 생성됩니다. 이 디렉터리는 Git에서 제외됩니다.

## 프로젝트 구조

| 경로 | 역할 |
|---|---|
| `data/raw/*.csv` | 고객·상품·주문·주문 상세·결제 시도 합성 파일 |
| `scripts/generate_data.py` | 합성 데이터 생성기 (seed 고정, 재현 가능) |
| `src/config.py` | 이름 기반 Snowflake 연결·DB 설정 |
| `src/extract.py` | CSV 읽기·파일과 컬럼 검사 |
| `src/transform.py` | 중복·누락·형식 처리 |
| `src/validate.py` | 관계·주문·결제 금액 검증과 DW 데이터 구성 |
| `src/load.py` | 실행별 STG 적재·트랜잭션·MERGE·검증 |
| `src/audit.py` | 실행·오류·제외 주문·검증 기록 |
| `src/pipeline.py` | CLI·실행 순서·실패 처리 |
| `sql/01_create_schemas.sql` | STG·DW·MART·AUDIT 생성 |
| `sql/02_create_tables.sql` | 테이블 생성 |
| `sql/03_merge_dimensions.sql` | 고객·상품·날짜 반영 |
| `sql/04_merge_facts.sql` | 주문·주문 상세 반영 |
| `sql/05_validate_dw.sql` | DW 무결성·금액 검사 |
| `sql/06_create_mart_views.sql` | 매출·상품·실행 상태 뷰 |
| `streamlit/streamlit_app.py` | 매출·품질 대시보드 |
| `tests/` | 로컬 테스트 및 선택적 Snowflake 통합 테스트 |
| `docs/` | ERD·업무 규칙·실행 방법·검증·리뷰 문서 |

## Snowflake 환경 준비

학습 전용 데이터베이스와 warehouse를 사용합니다. 이 파이프라인은 전체 스냅샷을 반영하므로 `DW`에서 이번 입력에 없는 키를 제거합니다. 운영 데이터베이스나 부분 증분 파일에 사용하지 마세요.

1. 사용할 역할에 전용 DB/스키마·테이블·뷰 생성 권한과 warehouse 사용 권한을 준비합니다.
2. Snowsight SQL Worksheet에서 전용 DB를 생성하고 선택합니다. warehouse는 계정에서 승인된 것을 선택합니다.

```sql
CREATE DATABASE IF NOT EXISTS AE101_SALES;
USE DATABASE AE101_SALES;
```

3. 같은 DB 컨텍스트에서 `sql/01_create_schemas.sql`, `02_create_tables.sql`, `06_create_mart_views.sql`을 순서대로 실행합니다. `03`·`04`는 Python이 run_id를 바인딩하므로 Worksheet에서 그대로 실행하지 않습니다.
4. 로컬 가상환경을 만들고 패키지를 설치합니다.

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`requirements.txt`는 지원 범위이며 잠금 파일이 아닙니다. 클라우드 패키지 호환성과 실제 연결은 자신의 계정에서 확인하고, 성공한 버전을 별도로 기록하세요.

5. 저장소 밖 `~/.snowflake/connections.toml`에 이름이 `ae101`인 연결을 만듭니다. 아래 값은 자리표시자이며 실제 계정·사용자·역할·warehouse로 바꿉니다. 인증 방식은 계정 정책에 맞추며 예시는 브라우저 인증입니다.

```toml
[ae101]
account = "YOUR_ORG-YOUR_ACCOUNT"
user = "YOUR_USER"
authenticator = "externalbrowser"
role = "YOUR_PROJECT_ROLE"
warehouse = "YOUR_WAREHOUSE"
database = "AE101_SALES"
schema = "STG"
```

`~/.snowflake`가 없을 때의 OS별 설정 경로 및 인증 방식은 [공식 연결 문서](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect)를 참고하세요. 인증 파일은 저장소에 넣지 않습니다.

6. 적재를 실행합니다.

```bash
python -m src.pipeline --load
python -m src.pipeline --load
```

연결 이름은 `SNOWFLAKE_CONNECTION_NAME`, DB는 `AE101_DATABASE` 환경변수로 변경할 수 있습니다. `--input`은 5개 CSV가 모두 있는 전체 스냅샷 디렉터리, `--output`은 로컬 결과 디렉터리를 받습니다.
유효한 매출 주문이 0건이면 기본적으로 게시를 중단합니다. 의도적으로 빈 스냅샷을 게시할 때만 `--allow-empty`를 지정합니다.

## Streamlit 실행

1. Snowsight에서 Streamlit 앱을 만들고 파이프라인과 같은 DB 및 사용 가능한 warehouse를 선택합니다.
2. `streamlit/streamlit_app.py`를 앱 코드로 사용합니다.
3. 앱 환경에서 `streamlit`, `snowflake-snowpark-python`, `pandas` 패키지를 사용할 수 있게 설정합니다.
4. 앱 실행 역할은 MART 뷰와 해당 AUDIT 조회에 필요한 권한을 가져야 합니다. 학습 전용 역할로 먼저 확인하세요.
5. 총매출 2,198,198,700원·주문 27,055건·평균 약 81,249원 및 상품별 합계를 확인합니다.

이 앱은 Snowflake 활성 세션을 사용하므로 로컬 `streamlit run` 대상이 아닙니다. [공식 Streamlit 안내](https://docs.snowflake.com/en/developer-guide/streamlit/about-streamlit)

## 학습 문서

- [원천·DW ERD](docs/erd.md)
- [파이프라인 실행 순서와 복구](docs/execution_flow.md)
- [데이터 사전](docs/data_dictionary.md)
- [처리 규칙·지표 정의](docs/data_rules.md)
- [실측 검증 결과와 클라우드 검증 방법](docs/validation_results.md)
- [AI 활용·리뷰 기록](docs/ai_review_log.md)
- [데이터 생성과 정답표](docs/data_generation.md)

## 범위와 한계

- 작은 교육용 데이터의 메모리 기반 ETL이며, 대규모 파일·오케스트레이터·동시 실행은 범위 밖입니다. **같은 DB에는 한 번에 하나의 실행만** 허용합니다.
- 원본은 고정된 전체 스냅샷입니다. 삭제·매출 제외의 반영을 위해 DW에서 이번 스냅샷에 없는 키를 제거합니다. 점진적 증분/CDC·이력 모델이 아닙니다.
- 고객·상품은 현재값만 유지합니다. 환불·수수료·정산·다중 통화는 프로젝트 2에서 확장합니다.
- STG와 AUDIT는 실행별로 누적됩니다. 교육 종료 후 전용 DB 정리 또는 운영자가 정한 보관 정책이 필요합니다.
- 실행이 강제 종료되면 RUNNING 로그가 남을 수 있습니다. 연결 종료 후 DW 트랜잭션 상태와 로그를 확인하고 재실행합니다.
- 로컬 테스트 통과는 실제 Snowflake SQL·권한·앱 배포 성공을 의미하지 않습니다. [검증 상태](docs/validation_results.md)를 확인하세요.
