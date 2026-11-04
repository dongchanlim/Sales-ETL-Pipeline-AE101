-- 04_core_order_quality.sql
-- STEP 5 · CORE 주문 품질 판정 : 매출 인식 여부·제외 사유, Fact 준비 테이블, RUN_SUMMARY
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step5). 노트북과 같은 내용을 유지합니다.

-- >>> LOGIC START
CREATE OR REPLACE TABLE CORE.ORDER_QUALITY AS
WITH blocked AS (
  SELECT DISTINCT order_id FROM CORE.ISSUES_WORK
  WHERE action IN ('QUARANTINED', 'FLAGGED') AND order_id IS NOT NULL),
items AS (
  SELECT order_id, COUNT(*) AS line_count, SUM(quantity * unit_price) AS line_amount_total
  FROM CORE.ORDER_ITEMS GROUP BY order_id),
pays AS (
  SELECT order_id,
         SUM(CASE WHEN payment_status = 'succeeded' THEN 1 ELSE 0 END)              AS success_payment_count,
         SUM(CASE WHEN payment_status = 'succeeded' THEN payment_amount ELSE 0 END) AS success_payment_amount,
         MIN(CASE WHEN payment_status = 'succeeded' THEN paid_at END)               AS first_success_paid_at
  FROM CORE.PAYMENTS WHERE has_valid_order GROUP BY order_id),
q AS (
  SELECT o.order_id, o.customer_id, o.order_date, o.order_status, o.order_amount,
         COALESCE(i.line_count, 0)             AS line_count,
         COALESCE(i.line_amount_total, 0)      AS line_amount_total,
         COALESCE(p.success_payment_count, 0)  AS success_payment_count,
         COALESCE(p.success_payment_amount, 0) AS success_payment_amount,
         p.first_success_paid_at,
         CASE
           WHEN b.order_id IS NOT NULL                    THEN 'DEPENDENCY_ERROR'
           WHEN o.order_status <> 'completed'             THEN 'NOT_COMPLETED'
           WHEN COALESCE(p.success_payment_count, 0) <> 1 THEN 'SUCCESS_PAYMENT_COUNT'
           WHEN COALESCE(i.line_count, 0) = 0             THEN 'MISSING_ITEMS'
           WHEN NOT (o.order_amount = i.line_amount_total AND i.line_amount_total = p.success_payment_amount) THEN 'AMOUNT_MISMATCH'
         END AS exclusion_reason
  FROM CORE.ORDERS o
  LEFT JOIN blocked b ON o.order_id = b.order_id
  LEFT JOIN items   i ON o.order_id = i.order_id
  LEFT JOIN pays    p ON o.order_id = p.order_id)
SELECT q.*, q.exclusion_reason IS NULL AS is_revenue_eligible FROM q;

INSERT INTO CORE.ISSUES_WORK
SELECT 'orders.csv', o.src_row, q.order_id, q.exclusion_reason, 'Order excluded from revenue (still loaded)', q.order_id, 'FLAGGED'
FROM CORE.ORDER_QUALITY q JOIN CORE.ORDERS o ON q.order_id = o.order_id
WHERE q.exclusion_reason IN ('SUCCESS_PAYMENT_COUNT', 'MISSING_ITEMS', 'AMOUNT_MISMATCH');

-- Fact 적재 직전 형태 (키는 아직 업무 키. 대리키는 STEP 7 에서 연결)
CREATE OR REPLACE TABLE CORE.SALES_LINE_PREP AS
SELECT i.order_item_id, i.order_id, q.customer_id, i.product_id, q.order_date, q.order_status,
       i.quantity, i.unit_price, i.quantity * i.unit_price AS line_amount,
       q.is_revenue_eligible, q.exclusion_reason
FROM CORE.ORDER_ITEMS i JOIN CORE.ORDER_QUALITY q ON i.order_id = q.order_id;

CREATE OR REPLACE TABLE CORE.PAYMENT_PREP AS
SELECT p.payment_id, p.order_id, o.customer_id, o.order_date, p.paid_at, CAST(p.paid_at AS DATE) AS paid_date,
       p.payment_status, p.payment_amount, p.has_valid_order
FROM CORE.PAYMENTS p LEFT JOIN CORE.ORDERS o ON p.order_id = o.order_id;

CREATE OR REPLACE TABLE CORE.RUN_SUMMARY AS
SELECT (SELECT COUNT(*) FROM RAW.V_CUSTOMERS_LATEST) + (SELECT COUNT(*) FROM RAW.V_PRODUCTS_LATEST)
     + (SELECT COUNT(*) FROM RAW.V_ORDERS_LATEST) + (SELECT COUNT(*) FROM RAW.V_ORDER_ITEMS_LATEST)
     + (SELECT COUNT(*) FROM RAW.V_PAYMENTS_LATEST)                                              AS input_rows,
       (SELECT COUNT(*) FROM CORE.ISSUES_WORK WHERE action = 'REMOVED')                          AS duplicate_rows,
       (SELECT COUNT(DISTINCT source_file || ':' || CAST(source_row_number AS VARCHAR))
          FROM CORE.ISSUES_WORK WHERE action = 'QUARANTINED')                                    AS quarantined_rows,
       (SELECT COUNT(*) FROM CORE.ISSUES_WORK WHERE action = 'FLAGGED')                          AS flagged_issues,
       (SELECT COUNT(*) FROM CORE.ORDER_QUALITY WHERE is_revenue_eligible)                       AS revenue_orders,
       (SELECT COALESCE(SUM(order_amount), 0) FROM CORE.ORDER_QUALITY WHERE is_revenue_eligible) AS revenue_amount;
-- <<< LOGIC END (판정)

-- 확인: 판정 결과 분포 (기대값: 매출 인식 27,055 / NOT_COMPLETED 2,190 / DEPENDENCY_ERROR 284 /
--        AMOUNT_MISMATCH 141 / SUCCESS_PAYMENT_COUNT 101 / MISSING_ITEMS 31). 제외된 주문도 모두 "적재"됩니다.
SELECT COALESCE(exclusion_reason, '(매출 인식)') AS result, COUNT(*) AS orders, SUM(order_amount) AS order_amount
FROM CORE.ORDER_QUALITY GROUP BY 1 ORDER BY orders DESC;

-- 원래 교육용 사례(O001~O010)는 그대로 들어 있습니다: O001·O002 만 매출 인식
SELECT order_id, order_status, order_amount, line_amount_total, success_payment_count, exclusion_reason
FROM CORE.ORDER_QUALITY WHERE order_id BETWEEN 'O001' AND 'O010' ORDER BY order_id;
