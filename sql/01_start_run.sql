-- 01_start_run.sql
-- STEP 2 · 실행 시작 : load_id / run_ts 발급 (CORE.RUN_CTX)
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step2). 노트북과 같은 내용을 유지합니다.

-- UUID_STRING() 같은 비결정 함수는 SET 에 바로 쓸 수 없는 환경(노트북 등)이 있어, 먼저 테이블에 발급한 뒤 변수로 읽습니다.
CREATE OR REPLACE TABLE CORE.RUN_CTX AS
  SELECT UUID_STRING() AS load_id, CURRENT_TIMESTAMP()::TIMESTAMP_NTZ AS run_ts;
SET load_id = (SELECT load_id FROM CORE.RUN_CTX);
SET run_ts  = (SELECT run_ts  FROM CORE.RUN_CTX);

INSERT INTO AUDIT.PIPELINE_RUNS (load_id, status, started_at) SELECT $load_id, 'RUNNING', $run_ts;
