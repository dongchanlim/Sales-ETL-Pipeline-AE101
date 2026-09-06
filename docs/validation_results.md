# 검증 결과

2026-09-06 로컬 Python 실행 기준입니다. 실제 Snowflake 계정 연결·SQL 실행·Streamlit 배포는 수행하지 않았습니다.

## 합성 파일 실측 결과

| 항목 | 결과 |
|---|---:|
| 전체 원본 행 | 40 |
| 제거된 완전 중복 행 | 2 |
| 오류가 있는 고유 원본 행 | 12 |
| 제외된 식별 가능한 주문 ID | 9 |
| 정상 매출 주문 | 2 |
| 정상 주문 상세 | 3 |
| 총매출 | 45,000원 |
| 평균 주문 금액 | 22,500원 |
| P001 매출 | 20,000원 |
| P002 매출 | 25,000원 |

O001=30,000원, O002=15,000원. O003 필수값 누락, O004 금액 불일치, O005 중복 성공 결제, O006 상품 참조 오류, O007 키 충돌, O008 대기, O009 고객 참조 오류, O010 주문 상세 없음, O404 존재하지 않는 참조 주문입니다. 주문 ID가 없는 원본 행은 오류로 기록하지만 식별 가능한 제외 주문 수에는 포함하지 않습니다.

## 자동 테스트

```bash
python -m unittest discover -s tests -v
```

로컬 테스트 10개 통과, Snowflake 통합 테스트 1개는 명시적 계정 설정이 없어 건너뜁니다.
행 순서 변경·중복 추가 불변성, 오류 주문 전체 제외, 숫자 파싱, 필수 헤더, 트랜잭션 제어 흐름, 빈 스냅샷 방어를 확인합니다.
트랜잭션 제어 테스트는 가짜 커서 기반으로 COMMIT/ROLLBACK 호출 순서를 확인하며 Snowflake SQL 실행 증명은 아닙니다.

## 실제 Snowflake 재실행 테스트

학습 DB와 별개로 이름이 `_TEST`로 끝나는 폐기 가능한 전용 DB를 생성하고 SQL 01·02·06으로 초기화합니다. 테스트는 이 DB의 DW 전체 스냅샷을 변경합니다.

```bash
# macOS / Linux
export AE101_DATABASE=AE101_SALES_TEST
export AE101_RUN_SNOWFLAKE_TESTS=1
python -m unittest tests.test_rerun.SnowflakeRerunTests -v
```

Windows PowerShell에서는 `$env:AE101_DATABASE="AE101_SALES_TEST"`와 `$env:AE101_RUN_SNOWFLAKE_TESTS="1"`로 지정합니다.
연결 설정은 README를 따릅니다. 통합 테스트는 실제 적재를 두 번 수행하고 DW 전체 업무 값을 비교합니다.
완료 후 환경변수를 해제하고 아래 검증 기록을 작성하세요.

| 클라우드 검증 | 상태 |
|---|---|
| SQL DDL/뷰 생성 | 미실행 |
| 실제 MERGE 및 SQL 05 검사 | 미실행 |
| 동일 입력 2회 적재 | 미실행 |
| Streamlit 필터·매출·실행 상태 | 미실행 |
| 계정별 패키지·권한 확인 | 미실행 |
