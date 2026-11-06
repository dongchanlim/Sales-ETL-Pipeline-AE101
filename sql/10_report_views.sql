-- 10_report_views.sql
-- STEP 8 · 리포트 뷰 (MART.V_*)
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step8). 노트북과 같은 내용을 유지합니다.

-- >>> LOGIC START
CREATE OR REPLACE VIEW MART.V_REVENUE_DAILY AS
SELECT d.calendar_date AS order_date, d.day_name,
       COUNT(DISTINCT f.order_id) AS order_count,
       SUM(f.quantity)            AS quantity,
       SUM(f.line_amount)         AS revenue
FROM MART.FACT_SALES_LINE f
JOIN MART.DIM_DATE d     ON f.order_date_key = d.date_key
JOIN MART.DIM_CUSTOMER c ON f.customer_key = c.customer_key
WHERE f.is_revenue_eligible AND NOT f.is_deleted
GROUP BY d.calendar_date, d.day_name;

-- 전체 달력 활용: 매출이 없는 날도 0으로 보임
CREATE OR REPLACE VIEW MART.V_REVENUE_CALENDAR AS
WITH bounds AS (SELECT MIN(order_date) AS s, MAX(order_date) AS e FROM MART.FACT_ORDER_LIFECYCLE WHERE NOT is_deleted)
SELECT d.calendar_date, d.day_name, d.is_weekend,
       COALESCE(r.order_count, 0) AS order_count,
       COALESCE(r.revenue, 0)     AS revenue
FROM MART.DIM_DATE d
CROSS JOIN bounds b
LEFT JOIN MART.V_REVENUE_DAILY r ON r.order_date = d.calendar_date
WHERE d.calendar_date BETWEEN b.s AND b.e;

CREATE OR REPLACE VIEW MART.V_REVENUE_BY_PRODUCT AS
SELECT p.product_id, p.product_name, p.category,
       SUM(f.quantity) AS quantity, SUM(f.line_amount) AS revenue
FROM MART.FACT_SALES_LINE f
JOIN MART.DIM_PRODUCT p  ON f.product_key = p.product_key
JOIN MART.DIM_CUSTOMER c ON f.customer_key = c.customer_key
WHERE f.is_revenue_eligible AND NOT f.is_deleted
GROUP BY p.product_id, p.product_name, p.category;

-- SCD2 효과 1: 주문 "당시" 고객 지역 기준 (As-Was)
CREATE OR REPLACE VIEW MART.V_REVENUE_BY_REGION_ASWAS AS
SELECT c.region, COUNT(DISTINCT f.order_id) AS order_count, SUM(f.line_amount) AS revenue
FROM MART.FACT_SALES_LINE f
JOIN MART.DIM_CUSTOMER c ON f.customer_key = c.customer_key
WHERE f.is_revenue_eligible AND NOT f.is_deleted
GROUP BY c.region;

-- SCD2 효과 2: 고객의 "현재" 지역 기준 (As-Is)
CREATE OR REPLACE VIEW MART.V_REVENUE_BY_REGION_ASIS AS
SELECT cur.region, COUNT(DISTINCT f.order_id) AS order_count, SUM(f.line_amount) AS revenue
FROM MART.FACT_SALES_LINE f
JOIN MART.DIM_CUSTOMER c   ON f.customer_key = c.customer_key
JOIN MART.DIM_CUSTOMER cur ON cur.customer_id = c.customer_id AND cur.is_current
WHERE f.is_revenue_eligible AND NOT f.is_deleted
GROUP BY cur.region;

-- 매출에서 빠진 주문도 사유와 함께 조회 (기존 EXCLUDED_ORDERS 테이블 역할)
CREATE OR REPLACE VIEW MART.V_ORDER_QUALITY AS
SELECT o.order_id, o.order_date, s.status_name AS order_status, c.customer_id, c.region,
       o.order_amount, o.line_amount_total, o.success_payment_count, o.success_payment_amount,
       o.days_to_first_success_payment, o.is_revenue_eligible, o.exclusion_reason
FROM MART.FACT_ORDER_LIFECYCLE o
JOIN MART.DIM_ORDER_STATUS s ON o.order_status_key = s.order_status_key
JOIN MART.DIM_CUSTOMER c     ON o.customer_key = c.customer_key
WHERE NOT o.is_deleted;

CREATE OR REPLACE VIEW MART.V_PAYMENT_SUMMARY AS
SELECT s.status_name AS payment_status, COUNT(*) AS attempts, SUM(f.payment_amount) AS amount,
       SUM(CASE WHEN f.has_valid_order THEN 0 ELSE 1 END) AS orphan_payments
FROM MART.FACT_PAYMENT f
JOIN MART.DIM_PAYMENT_STATUS s ON f.payment_status_key = s.payment_status_key
JOIN MART.DIM_CUSTOMER c       ON f.customer_key = c.customer_key
WHERE NOT f.is_deleted
GROUP BY s.status_name;
-- 대시보드용 라인 단위 매출 : 기간·지역·카테고리 필터를 한 뷰에서 처리 (지역 = 주문 당시)
CREATE OR REPLACE VIEW MART.V_SALES_LINE AS
SELECT f.order_id, f.order_item_id, d.calendar_date AS order_date, d.year_month, d.is_weekend,
       c.customer_id, c.region, p.product_id, p.product_name, p.category,
       f.quantity, f.unit_price, f.line_amount AS revenue
FROM MART.FACT_SALES_LINE f
JOIN MART.DIM_DATE d     ON f.order_date_key = d.date_key
JOIN MART.DIM_CUSTOMER c ON f.customer_key = c.customer_key
JOIN MART.DIM_PRODUCT p  ON f.product_key = p.product_key
WHERE f.is_revenue_eligible AND NOT f.is_deleted;

-- 결제 시도 일별·지역별·상태별 (성공률 추이용)
CREATE OR REPLACE VIEW MART.V_PAYMENT_DAILY AS
SELECT d.calendar_date AS paid_date, c.region, s.status_name AS payment_status,
       COUNT(*) AS attempts, SUM(f.payment_amount) AS amount,
       SUM(CASE WHEN f.has_valid_order THEN 0 ELSE 1 END) AS orphan_payments
FROM MART.FACT_PAYMENT f
JOIN MART.DIM_DATE d           ON f.paid_date_key = d.date_key
JOIN MART.DIM_PAYMENT_STATUS s ON f.payment_status_key = s.payment_status_key
JOIN MART.DIM_CUSTOMER c       ON f.customer_key = c.customer_key
WHERE NOT f.is_deleted
GROUP BY d.calendar_date, c.region, s.status_name;
-- <<< LOGIC END (뷰)

CREATE OR REPLACE VIEW MART.V_LATEST_RUN AS
SELECT * FROM AUDIT.PIPELINE_RUNS QUALIFY ROW_NUMBER() OVER (ORDER BY started_at DESC) = 1;

-- 운영 뷰 : 대시보드가 AUDIT 테이블 권한 없이 실행 이력·품질 결과를 보도록 요약만 공개합니다 (개별 행·키 값 없음)
CREATE OR REPLACE VIEW MART.V_RUN_HISTORY AS
SELECT r.load_id, r.status, r.started_at, r.finished_at,
       DATEDIFF('second', r.started_at, r.finished_at) AS duration_sec,
       r.input_rows, r.duplicate_rows, r.quarantined_rows, r.flagged_issues,
       r.revenue_orders, r.revenue_amount, r.message,
       COALESCE(q.failed_checks, 0) AS failed_checks, COALESCE(q.total_checks, 0) AS total_checks
FROM AUDIT.PIPELINE_RUNS r
LEFT JOIN (SELECT load_id, SUM(CASE WHEN failures > 0 THEN 1 ELSE 0 END) AS failed_checks, COUNT(*) AS total_checks
           FROM AUDIT.DQ_RESULTS GROUP BY load_id) q ON q.load_id = r.load_id;

CREATE OR REPLACE VIEW MART.V_DQ_RESULTS AS
SELECT load_id, check_name, failures FROM AUDIT.DQ_RESULTS;

CREATE OR REPLACE VIEW MART.V_DATA_ISSUE_SUMMARY AS
SELECT load_id, action, error_code, source_file, COUNT(*) AS events
FROM AUDIT.DATA_ISSUES
GROUP BY load_id, action, error_code, source_file;
