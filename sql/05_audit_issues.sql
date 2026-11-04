-- 05_audit_issues.sql
-- STEP 6 · 감사 기록 : CORE.ISSUES_WORK → AUDIT.DATA_ISSUES
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step6). 노트북과 같은 내용을 유지합니다.

INSERT INTO AUDIT.DATA_ISSUES (load_id, source_file, source_row_number, record_key, error_code, error_detail, order_id, action)
SELECT $load_id, source_file, source_row_number, record_key, error_code, error_detail, order_id, action
FROM CORE.ISSUES_WORK;

SELECT * FROM CORE.RUN_SUMMARY;   -- 기대값: 129,618 / 473 / 441 / 559 / 27,055 / 2,198,198,700
