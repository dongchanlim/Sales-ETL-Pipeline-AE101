-- 09_finalize_run.sql
-- STEP 7-4 · 게이트 : 검사 결과로 AUDIT.PIPELINE_RUNS 상태 확정 (SUCCESS / FAILED)
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step7_4_finalize). 노트북과 같은 내용을 유지합니다.

UPDATE AUDIT.PIPELINE_RUNS p
   SET status = IFF(q.fail_cnt = 0, 'SUCCESS', 'FAILED'),
       finished_at = CURRENT_TIMESTAMP()::TIMESTAMP_NTZ,
       message = IFF(q.fail_cnt = 0, NULL, 'DQ failed: ' || q.fail_names),
       input_rows = s.input_rows, duplicate_rows = s.duplicate_rows, quarantined_rows = s.quarantined_rows,
       flagged_issues = s.flagged_issues, revenue_orders = s.revenue_orders, revenue_amount = s.revenue_amount
  FROM CORE.RUN_SUMMARY s,
       (SELECT COALESCE(SUM(failures), 0) AS fail_cnt,
               COALESCE(LISTAGG(CASE WHEN failures > 0 THEN check_name END, ', '), '') AS fail_names
          FROM AUDIT.DQ_RESULTS WHERE load_id = $load_id) q
 WHERE p.load_id = $load_id;

SELECT load_id, status, message, input_rows, revenue_orders, revenue_amount
FROM AUDIT.PIPELINE_RUNS WHERE load_id = $load_id;   -- 기대값: SUCCESS / 27,055 / 2,198,198,700
