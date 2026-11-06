-- daily_alert.sql  (선택)
-- 매일 배치 실패·지연 알림 : 매일 07:30 에 확인해, 최근 실행이 SUCCESS 가 아니거나 마지막 성공이 26시간보다 오래됐으면 메일을 보냅니다.
-- daily_schedule.sql 을 설치한 뒤 실행합니다.
--
-- 바꿀 값
--   you@example.com (3곳) : 받는 주소. 이 Snowflake 계정에서 이메일 인증을 마친 사용자의 주소여야 합니다.
--   COMPUTE_WH             : 실제 웨어하우스 이름
--   07:30                  : 배치(06:00)가 끝난 뒤의 시각. 배치가 RUNNING 인 동안 확인하면 알림이 갑니다.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE SNOWFLAKE_LEARNING_WH;
SET CURRENT_WH = (SELECT CURRENT_WAREHOUSE());

CREATE NOTIFICATION INTEGRATION IF NOT EXISTS AE101_EMAIL_INT
  TYPE = EMAIL
  ENABLED = TRUE
  ALLOWED_RECIPIENTS = ('dchanlim@gmail.com');

CREATE OR REPLACE ALERT AE101_SALES_ENT.OPS.ALERT_DAILY_BATCH
  WAREHOUSE = $CURRENT_WH
  SCHEDULE = 'USING CRON 30 14 * * * America/Los_Angeles'
  IF (EXISTS (
    SELECT 1
    FROM (SELECT MAX_BY(status, started_at)                     AS last_status,
                 MAX(IFF(status = 'SUCCESS', finished_at, NULL)) AS last_success
            FROM AE101_SALES_ENT.AUDIT.PIPELINE_RUNS)
    WHERE last_status <> 'SUCCESS'
       OR last_success IS NULL
       OR last_success < DATEADD('hour', -26, CURRENT_TIMESTAMP()::TIMESTAMP_NTZ)))
  THEN
    CALL SYSTEM$SEND_EMAIL(
      'AE101_EMAIL_INT',
      'dchanlim@gmail.com',
      '[AE101] 일일 배치 확인 필요',
      '최근 배치가 SUCCESS 가 아니거나 26시간 넘게 성공 기록이 없습니다. AE101_SALES_ENT.MART.V_RUN_HISTORY 를 확인하세요.');

-- 새 알림은 멈춘 상태로 만들어집니다.
ALTER ALERT AE101_SALES_ENT.OPS.ALERT_DAILY_BATCH RESUME;

-- 알림 확인 이력
--   SELECT name, state, scheduled_time, completed_time, sql_error_message
--   FROM TABLE(AE101_SALES_ENT.INFORMATION_SCHEMA.ALERT_HISTORY(SCHEDULED_TIME_RANGE_START => DATEADD('day', -7, CURRENT_TIMESTAMP())))
--   ORDER BY scheduled_time DESC;
--
-- 메일 연결만 먼저 시험하기
--   CALL SYSTEM$SEND_EMAIL('AE101_EMAIL_INT', 'you@example.com', '[AE101] 테스트', '알림 연결 확인');
