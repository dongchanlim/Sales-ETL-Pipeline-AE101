-- 07_mart_facts.sql
-- STEP 7-2 · Fact MERGE (FACT_SALES_LINE, FACT_PAYMENT, FACT_ORDER_LIFECYCLE) + 소프트 삭제
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step7_2a_fact_sales_line, step7_2b_fact_payment, step7_2c_fact_order_lifecycle). 노트북과 같은 내용을 유지합니다.

-- 7-2. fact_sales_line
MERGE INTO MART.FACT_SALES_LINE AS t
USING (
  SELECT p.order_item_id, p.order_id,
         COALESCE(c.customer_key, -1)      AS customer_key,
         COALESCE(pr.product_key, -1)      AS product_key,
         COALESCE(d.date_key, -1)          AS order_date_key,
         COALESCE(s.order_status_key, -1)  AS order_status_key,
         p.order_date, p.quantity, p.unit_price, p.line_amount, p.is_revenue_eligible, p.exclusion_reason
  FROM CORE.SALES_LINE_PREP p
  LEFT JOIN MART.DIM_CUSTOMER c
         ON c.customer_id = p.customer_id AND c.customer_key <> -1
        AND CAST(p.order_date AS TIMESTAMP_NTZ) >= c.valid_from
        AND CAST(p.order_date AS TIMESTAMP_NTZ) <  COALESCE(c.valid_to, '9999-12-31'::TIMESTAMP_NTZ)
  LEFT JOIN MART.DIM_PRODUCT pr
         ON pr.product_id = p.product_id AND pr.product_key <> -1
        AND CAST(p.order_date AS TIMESTAMP_NTZ) >= pr.valid_from
        AND CAST(p.order_date AS TIMESTAMP_NTZ) <  COALESCE(pr.valid_to, '9999-12-31'::TIMESTAMP_NTZ)
  LEFT JOIN MART.DIM_DATE d          ON d.calendar_date = p.order_date
  LEFT JOIN MART.DIM_ORDER_STATUS s  ON s.status_code = p.order_status
) AS src
ON t.order_item_id = src.order_item_id
WHEN MATCHED THEN UPDATE SET
  order_id = src.order_id, customer_key = src.customer_key, product_key = src.product_key,
  order_date_key = src.order_date_key, order_status_key = src.order_status_key, order_date = src.order_date,
  quantity = src.quantity, unit_price = src.unit_price, line_amount = src.line_amount,
  is_revenue_eligible = src.is_revenue_eligible, exclusion_reason = src.exclusion_reason,
  is_deleted = FALSE, load_id = $load_id, updated_at = $run_ts
WHEN NOT MATCHED THEN INSERT
  (order_item_id, order_id, customer_key, product_key, order_date_key, order_status_key, order_date,
   quantity, unit_price, line_amount, is_revenue_eligible, exclusion_reason, is_deleted, load_id, updated_at)
VALUES
  (src.order_item_id, src.order_id, src.customer_key, src.product_key, src.order_date_key, src.order_status_key, src.order_date,
   src.quantity, src.unit_price, src.line_amount, src.is_revenue_eligible, src.exclusion_reason, FALSE, $load_id, $run_ts);

UPDATE MART.FACT_SALES_LINE SET is_deleted = TRUE, load_id = $load_id, updated_at = $run_ts
WHERE NOT is_deleted AND order_item_id NOT IN (SELECT order_item_id FROM CORE.SALES_LINE_PREP);

-- 7-2. fact_payment
MERGE INTO MART.FACT_PAYMENT AS t
USING (
  SELECT p.payment_id, p.order_id,
         COALESCE(c.customer_key, -1)       AS customer_key,
         COALESCE(d.date_key, -1)           AS paid_date_key,
         COALESCE(s.payment_status_key, -1) AS payment_status_key,
         p.paid_at, p.payment_amount, p.has_valid_order
  FROM CORE.PAYMENT_PREP p
  LEFT JOIN MART.DIM_CUSTOMER c
         ON c.customer_id = p.customer_id AND c.customer_key <> -1
        AND CAST(p.order_date AS TIMESTAMP_NTZ) >= c.valid_from
        AND CAST(p.order_date AS TIMESTAMP_NTZ) <  COALESCE(c.valid_to, '9999-12-31'::TIMESTAMP_NTZ)
  LEFT JOIN MART.DIM_DATE d            ON d.calendar_date = p.paid_date
  LEFT JOIN MART.DIM_PAYMENT_STATUS s  ON s.status_code = p.payment_status
) AS src
ON t.payment_id = src.payment_id
WHEN MATCHED THEN UPDATE SET
  order_id = src.order_id, customer_key = src.customer_key, paid_date_key = src.paid_date_key,
  payment_status_key = src.payment_status_key, paid_at = src.paid_at, payment_amount = src.payment_amount,
  has_valid_order = src.has_valid_order, is_deleted = FALSE, load_id = $load_id, updated_at = $run_ts
WHEN NOT MATCHED THEN INSERT
  (payment_id, order_id, customer_key, paid_date_key, payment_status_key, paid_at, payment_amount, has_valid_order, is_deleted, load_id, updated_at)
VALUES
  (src.payment_id, src.order_id, src.customer_key, src.paid_date_key, src.payment_status_key, src.paid_at, src.payment_amount,
   src.has_valid_order, FALSE, $load_id, $run_ts);

UPDATE MART.FACT_PAYMENT SET is_deleted = TRUE, load_id = $load_id, updated_at = $run_ts
WHERE NOT is_deleted AND payment_id NOT IN (SELECT payment_id FROM CORE.PAYMENT_PREP);

-- 7-2. fact_order_lifecycle
MERGE INTO MART.FACT_ORDER_LIFECYCLE AS t
USING (
  SELECT q.order_id,
         COALESCE(c.customer_key, -1)      AS customer_key,
         COALESCE(d.date_key, -1)          AS order_date_key,
         COALESCE(pd.date_key, -1)         AS first_success_paid_date_key,
         COALESCE(s.order_status_key, -1)  AS order_status_key,
         q.order_date, q.first_success_paid_at, q.order_amount, q.line_count, q.line_amount_total,
         q.success_payment_count, q.success_payment_amount,
         DATEDIFF('day', q.order_date, CAST(q.first_success_paid_at AS DATE)) AS days_to_first_success_payment,
         q.is_revenue_eligible, q.exclusion_reason
  FROM CORE.ORDER_QUALITY q
  LEFT JOIN MART.DIM_CUSTOMER c
         ON c.customer_id = q.customer_id AND c.customer_key <> -1
        AND CAST(q.order_date AS TIMESTAMP_NTZ) >= c.valid_from
        AND CAST(q.order_date AS TIMESTAMP_NTZ) <  COALESCE(c.valid_to, '9999-12-31'::TIMESTAMP_NTZ)
  LEFT JOIN MART.DIM_DATE d          ON d.calendar_date  = q.order_date
  LEFT JOIN MART.DIM_DATE pd         ON pd.calendar_date = CAST(q.first_success_paid_at AS DATE)
  LEFT JOIN MART.DIM_ORDER_STATUS s  ON s.status_code    = q.order_status
) AS src
ON t.order_id = src.order_id
WHEN MATCHED THEN UPDATE SET
  customer_key = src.customer_key, order_date_key = src.order_date_key,
  first_success_paid_date_key = src.first_success_paid_date_key, order_status_key = src.order_status_key,
  order_date = src.order_date, first_success_paid_at = src.first_success_paid_at, order_amount = src.order_amount,
  line_count = src.line_count, line_amount_total = src.line_amount_total,
  success_payment_count = src.success_payment_count, success_payment_amount = src.success_payment_amount,
  days_to_first_success_payment = src.days_to_first_success_payment,
  is_revenue_eligible = src.is_revenue_eligible, exclusion_reason = src.exclusion_reason,
  is_deleted = FALSE, load_id = $load_id, updated_at = $run_ts
WHEN NOT MATCHED THEN INSERT
  (order_id, customer_key, order_date_key, first_success_paid_date_key, order_status_key, order_date, first_success_paid_at,
   order_amount, line_count, line_amount_total, success_payment_count, success_payment_amount, days_to_first_success_payment,
   is_revenue_eligible, exclusion_reason, is_deleted, load_id, updated_at)
VALUES
  (src.order_id, src.customer_key, src.order_date_key, src.first_success_paid_date_key, src.order_status_key, src.order_date,
   src.first_success_paid_at, src.order_amount, src.line_count, src.line_amount_total, src.success_payment_count,
   src.success_payment_amount, src.days_to_first_success_payment, src.is_revenue_eligible, src.exclusion_reason,
   FALSE, $load_id, $run_ts);

UPDATE MART.FACT_ORDER_LIFECYCLE SET is_deleted = TRUE, load_id = $load_id, updated_at = $run_ts
WHERE NOT is_deleted AND order_id NOT IN (SELECT order_id FROM CORE.ORDER_QUALITY);
