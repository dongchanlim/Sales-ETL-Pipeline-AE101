-- daily_schedule.sql
-- 매일 배치 스케줄 설치 : 일일 배치 노트북 배포 + Task Graph (루트 태스크 = 노트북 실행, 파이널라이저 = 실패 정리)
-- 매일 실행되는 것은 이 파일이 아니라 아래에서 만드는 태스크와 노트북입니다. 이 파일은 처음 한 번, 그리고 노트북을 고칠 때마다 다시 실행합니다.
--
-- 사전 조건
--   1) 워크스루 STEP 1(DDL)과 STEP 8(리포트 뷰)을 한 번 실행했다. (매일 다시 실행할 필요 없음: docs/scheduling.md 참고)
--      STEP 1 에는 스테이지 RAW.LANDING 과 생성 프로시저 RAW.GENERATE_LANDING_FILES 가 있습니다. 매일 배치는 기본으로 이 프로시저로 새 데이터를 만듭니다.
--   2) Git 저장소 객체 AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE 이 있고, main 브랜치에 notebooks/ae101_daily_batch.ipynb 가 있다.
--   3) 이 파일을 실행하는 역할이 파이프라인 객체(AE101_SALES_ENT)를 소유한 역할과 같다. 교육용 기본값은 ACCOUNTADMIN 입니다.
--
-- 바꿀 값
--   COMPUTE_WH (3곳)  : SHOW WAREHOUSES; 로 확인한 실제 웨어하우스 이름
--   스케줄 시간대     : 기본 매일 06:00 Asia/Seoul. 미국 서부는 America/Los_Angeles

USE ROLE ACCOUNTADMIN;
USE DATABASE AE101_SALES_ENT;
CREATE SCHEMA IF NOT EXISTS OPS;          -- 스케줄러 객체(노트북·태스크·알림)는 데이터와 분리해 OPS 스키마에 둡니다
USE SCHEMA OPS;

SET CURRENT_WH = (SELECT CURRENT_WAREHOUSE());

-- 1. 이미 설치된 스케줄이 있으면 먼저 멈춥니다. (태스크를 바꾸려면 루트 태스크가 멈춰 있어야 합니다)
ALTER TASK IF EXISTS OPS.T_DAILY_BATCH SUSPEND;

-- 2. 일일 배치 노트북 배포 : Git main 의 notebooks/ae101_daily_batch.ipynb 를 노트북 객체로 복사합니다.
--    노트북 객체는 만든 시점의 사본입니다. 저장소의 노트북을 고친 뒤에는 이 단계를 다시 실행해야 다음 배치에 반영됩니다.
ALTER GIT REPOSITORY AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE FETCH;

CREATE OR REPLACE NOTEBOOK OPS.AE101_DAILY_BATCH
  FROM '@AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE/branches/main/notebooks/'
  MAIN_FILE = 'ae101_daily_batch.ipynb'
  QUERY_WAREHOUSE = $CURRENT_WH
  COMMENT = 'AE101 daily batch (walkthrough STEP 2-7). Deployed by orchestration/daily_schedule.sql';

-- SQL 로 만든 노트북에는 실행 가능한 버전(live version)이 없어 EXECUTE NOTEBOOK 이 실패합니다. 마지막 버전을 live 로 지정합니다.
ALTER NOTEBOOK OPS.AE101_DAILY_BATCH ADD LIVE VERSION FROM LAST;

-- 3. 루트 태스크 : 매일 06:00 에 노트북을 실행합니다.
--    한 번에 하나의 실행만 허용(기본 NO_OVERLAP)되므로, 전날 배치가 끝나지 않았으면 그날 실행은 건너뜁니다.
CREATE OR REPLACE TASK OPS.T_DAILY_BATCH
  WAREHOUSE = $CURRENT_WH
  SCHEDULE = 'USING CRON 0 6 * * * Asia/Seoul'
  USER_TASK_TIMEOUT_MS = 3600000            -- 1시간 넘게 걸리면 실패 처리 (보통 몇 분)
  SUSPEND_TASK_AFTER_NUM_FAILURES = 3       -- 3번 연속 실패하면 자동 정지: 원인을 고치기 전까지 RAW 배치가 쌓이지 않게
  TASK_AUTO_RETRY_ATTEMPTS = 0              -- 품질 검사 실패는 다시 돌려도 같으므로 자동 재시도하지 않습니다
  COMMENT = 'AE101 daily batch: runs OPS.AE101_DAILY_BATCH notebook'
AS
  EXECUTE NOTEBOOK AE101_SALES_ENT.OPS.AE101_DAILY_BATCH();

-- 4. 파이널라이저 : 루트 태스크가 성공하든 실패하든 마지막에 한 번 실행됩니다.
--    노트북이 중간 셀에서 멈춰 이번 실행이 RUNNING 으로 남았다면 FAILED 로 닫아, 대시보드와 V_RUN_HISTORY 에 실패가 보이게 합니다.
--    정상 종료(SUCCESS / FAILED 확정)된 실행은 조건에 걸리지 않아 아무것도 바꾸지 않습니다.
CREATE OR REPLACE TASK OPS.T_DAILY_BATCH_FINALIZER
  WAREHOUSE = $CURRENT_WH
  FINALIZE = OPS.T_DAILY_BATCH
  COMMENT = 'AE101 daily batch finalizer: closes a run left RUNNING'
AS
  UPDATE AE101_SALES_ENT.AUDIT.PIPELINE_RUNS
     SET status = 'FAILED',
         finished_at = CURRENT_TIMESTAMP()::TIMESTAMP_NTZ,
         message = 'Scheduled run stopped before finalize. Check OPS task history and the notebook run history.'
   WHERE status = 'RUNNING'
     AND load_id = (SELECT load_id FROM AE101_SALES_ENT.CORE.RUN_CTX);

-- 5. 켜기 : 파이널라이저를 먼저, 루트 태스크를 마지막에 RESUME 합니다. (새로 만든 태스크는 멈춘 상태로 만들어집니다)
ALTER TASK OPS.T_DAILY_BATCH_FINALIZER RESUME;
ALTER TASK OPS.T_DAILY_BATCH RESUME;

SHOW TASKS IN SCHEMA AE101_SALES_ENT.OPS;   -- state = started 두 개

-- ---------------------------------------------------------------------------
-- 운영 명령 (필요할 때 한 줄씩 실행)
-- ---------------------------------------------------------------------------
-- 지금 한 번 실행해 보기 (스케줄과 별개로 즉시 실행)
--   EXECUTE TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH;
--
-- 태스크 실행 이력 (최근 20회)
--   SELECT name, state, scheduled_time, completed_time, error_message
--   FROM TABLE(AE101_SALES_ENT.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => 'T_DAILY_BATCH', RESULT_LIMIT => 20))
--   ORDER BY scheduled_time DESC;
--
-- 파이프라인 실행 기록 (대시보드 "데이터 운영" 탭과 같은 내용)
--   SELECT * FROM AE101_SALES_ENT.MART.V_RUN_HISTORY ORDER BY started_at DESC LIMIT 10;
--
-- 잠시 멈추기 / 다시 켜기 (워크스루 노트북을 직접 실습할 때는 멈춰 두세요)
--   ALTER TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH SUSPEND;
--   ALTER TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH RESUME;
--
-- 완전히 제거
--   ALTER TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH SUSPEND;
--   DROP TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH_FINALIZER;
--   DROP TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH;
--   DROP NOTEBOOK AE101_SALES_ENT.OPS.AE101_DAILY_BATCH;
