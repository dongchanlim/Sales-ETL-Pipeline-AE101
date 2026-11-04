-- 03_core_clean.sql
-- STEP 4 · CORE 정제 : dq_status (DUPLICATE/CONFLICT/INVALID/OK), 이슈 기록
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step4). 노트북과 같은 내용을 유지합니다.

-- >>> LOGIC START
CREATE OR REPLACE TABLE CORE.ISSUES_WORK (
  source_file VARCHAR, source_row_number NUMBER, record_key VARCHAR,
  error_code VARCHAR, error_detail VARCHAR, order_id VARCHAR, action VARCHAR);

-- ---------- customers (email·region 선택값, region 없으면 'Unknown') ----------
CREATE OR REPLACE TABLE CORE.CUSTOMERS_CHK AS
WITH d AS (
  SELECT r.src_row,
         NULLIF(TRIM(r.customer_id), '')   AS customer_id,
         NULLIF(TRIM(r.customer_name), '') AS customer_name,
         NULLIF(TRIM(r.email), '')         AS email,
         NULLIF(TRIM(r.region), '')        AS region,
         ROW_NUMBER() OVER (PARTITION BY r.customer_id, r.customer_name, r.email, r.region ORDER BY r.src_row) AS rn
  FROM RAW.V_CUSTOMERS_LATEST r),
u AS (
  SELECT d.*, COUNT(*) OVER (PARTITION BY d.customer_id) AS key_cnt,
         CASE WHEN d.customer_id   IS NULL THEN 'customer_id: required value missing'
              WHEN d.customer_name IS NULL THEN 'customer_name: required value missing' END AS err
  FROM d WHERE d.rn = 1)
SELECT src_row, customer_id, customer_name, email, region, 'DUPLICATE' AS dq_status, CAST(NULL AS VARCHAR) AS err FROM d WHERE rn > 1
UNION ALL
SELECT src_row, customer_id, customer_name, email, region,
       CASE WHEN customer_id IS NOT NULL AND key_cnt > 1 THEN 'CONFLICT' WHEN err IS NOT NULL THEN 'INVALID' ELSE 'OK' END, err
FROM u;

INSERT INTO CORE.ISSUES_WORK
SELECT 'customers.csv', src_row, customer_id,
       CASE dq_status WHEN 'DUPLICATE' THEN 'EXACT_DUPLICATE' WHEN 'CONFLICT' THEN 'KEY_CONFLICT' ELSE 'INVALID_VALUE' END,
       CASE dq_status WHEN 'DUPLICATE' THEN 'Identical source row removed' WHEN 'CONFLICT' THEN 'Same business key has conflicting source rows' ELSE err END,
       NULL, CASE dq_status WHEN 'DUPLICATE' THEN 'REMOVED' ELSE 'QUARANTINED' END
FROM CORE.CUSTOMERS_CHK WHERE dq_status <> 'OK';

CREATE OR REPLACE TABLE CORE.CUSTOMERS AS
SELECT customer_id, customer_name, email, COALESCE(region, 'Unknown') AS region,
       MD5(COALESCE(customer_name, '') || '|' || COALESCE(email, '') || '|' || COALESCE(region, 'Unknown')) AS hash_diff,
       src_row
FROM CORE.CUSTOMERS_CHK WHERE dq_status = 'OK';

-- ---------- products ----------
CREATE OR REPLACE TABLE CORE.PRODUCTS_CHK AS
WITH d AS (
  SELECT r.src_row,
         NULLIF(TRIM(r.product_id), '')   AS product_id,
         NULLIF(TRIM(r.product_name), '') AS product_name,
         NULLIF(TRIM(r.category), '')     AS category,
         ROW_NUMBER() OVER (PARTITION BY r.product_id, r.product_name, r.category ORDER BY r.src_row) AS rn
  FROM RAW.V_PRODUCTS_LATEST r),
u AS (
  SELECT d.*, COUNT(*) OVER (PARTITION BY d.product_id) AS key_cnt,
         CASE WHEN d.product_id   IS NULL THEN 'product_id: required value missing'
              WHEN d.product_name IS NULL THEN 'product_name: required value missing'
              WHEN d.category     IS NULL THEN 'category: required value missing' END AS err
  FROM d WHERE d.rn = 1)
SELECT src_row, product_id, product_name, category, 'DUPLICATE' AS dq_status, CAST(NULL AS VARCHAR) AS err FROM d WHERE rn > 1
UNION ALL
SELECT src_row, product_id, product_name, category,
       CASE WHEN product_id IS NOT NULL AND key_cnt > 1 THEN 'CONFLICT' WHEN err IS NOT NULL THEN 'INVALID' ELSE 'OK' END, err
FROM u;

INSERT INTO CORE.ISSUES_WORK
SELECT 'products.csv', src_row, product_id,
       CASE dq_status WHEN 'DUPLICATE' THEN 'EXACT_DUPLICATE' WHEN 'CONFLICT' THEN 'KEY_CONFLICT' ELSE 'INVALID_VALUE' END,
       CASE dq_status WHEN 'DUPLICATE' THEN 'Identical source row removed' WHEN 'CONFLICT' THEN 'Same business key has conflicting source rows' ELSE err END,
       NULL, CASE dq_status WHEN 'DUPLICATE' THEN 'REMOVED' ELSE 'QUARANTINED' END
FROM CORE.PRODUCTS_CHK WHERE dq_status <> 'OK';

CREATE OR REPLACE TABLE CORE.PRODUCTS AS
SELECT product_id, product_name, category,
       MD5(COALESCE(product_name, '') || '|' || COALESCE(category, '')) AS hash_diff,
       src_row
FROM CORE.PRODUCTS_CHK WHERE dq_status = 'OK';

-- ---------- orders ----------
CREATE OR REPLACE TABLE CORE.ORDERS_CHK AS
WITH d AS (
  SELECT r.src_row,
         NULLIF(TRIM(r.order_id), '')     AS order_id,
         NULLIF(TRIM(r.customer_id), '')  AS customer_id,
         NULLIF(TRIM(r.order_date), '')   AS order_date,
         NULLIF(TRIM(r.order_status), '') AS order_status,
         NULLIF(TRIM(r.order_amount), '') AS order_amount,
         ROW_NUMBER() OVER (PARTITION BY r.order_id, r.customer_id, r.order_date, r.order_status, r.order_amount ORDER BY r.src_row) AS rn
  FROM RAW.V_ORDERS_LATEST r),
u AS (
  SELECT d.*, COUNT(*) OVER (PARTITION BY d.order_id) AS key_cnt,
         CASE WHEN d.order_id     IS NULL THEN 'order_id: required value missing'
              WHEN d.customer_id  IS NULL THEN 'customer_id: required value missing'
              WHEN d.order_date   IS NULL THEN 'order_date: required value missing'
              WHEN d.order_status IS NULL THEN 'order_status: required value missing'
              WHEN d.order_amount IS NULL THEN 'order_amount: required value missing'
              WHEN NOT REGEXP_LIKE(d.order_amount, '[0-9]+') THEN 'order_amount: expected non-negative integer KRW/quantity'
              WHEN TRY_TO_NUMBER(d.order_amount) > 1000000000000 THEN 'order_amount: exceeds project input limit'
              WHEN TRY_TO_DATE(d.order_date, 'YYYY-MM-DD') IS NULL THEN 'order_date: invalid date'
              WHEN d.order_status NOT IN ('completed', 'pending', 'cancelled') THEN 'unknown order_status' END AS err
  FROM d WHERE d.rn = 1)
SELECT src_row, order_id, customer_id, order_date, order_status, order_amount, 'DUPLICATE' AS dq_status, CAST(NULL AS VARCHAR) AS err FROM d WHERE rn > 1
UNION ALL
SELECT src_row, order_id, customer_id, order_date, order_status, order_amount,
       CASE WHEN order_id IS NOT NULL AND key_cnt > 1 THEN 'CONFLICT' WHEN err IS NOT NULL THEN 'INVALID' ELSE 'OK' END, err
FROM u;

INSERT INTO CORE.ISSUES_WORK
SELECT 'orders.csv', src_row, order_id,
       CASE dq_status WHEN 'DUPLICATE' THEN 'EXACT_DUPLICATE' WHEN 'CONFLICT' THEN 'KEY_CONFLICT' ELSE 'INVALID_VALUE' END,
       CASE dq_status WHEN 'DUPLICATE' THEN 'Identical source row removed' WHEN 'CONFLICT' THEN 'Same business key has conflicting source rows' ELSE err END,
       order_id, CASE dq_status WHEN 'DUPLICATE' THEN 'REMOVED' ELSE 'QUARANTINED' END
FROM CORE.ORDERS_CHK WHERE dq_status <> 'OK';

CREATE OR REPLACE TABLE CORE.ORDERS AS
SELECT c.order_id, c.customer_id, TO_DATE(c.order_date, 'YYYY-MM-DD') AS order_date, c.order_status,
       TO_NUMBER(c.order_amount) AS order_amount,
       c.customer_id IN (SELECT customer_id FROM CORE.CUSTOMERS) AS has_valid_customer,
       c.src_row
FROM CORE.ORDERS_CHK c WHERE c.dq_status = 'OK';

INSERT INTO CORE.ISSUES_WORK
SELECT 'orders.csv', src_row, order_id, 'INVALID_REFERENCE', 'Unknown customer: loaded with customer_key = -1', order_id, 'FLAGGED'
FROM CORE.ORDERS WHERE NOT has_valid_customer;

-- ---------- order_items ----------
CREATE OR REPLACE TABLE CORE.ORDER_ITEMS_CHK AS
WITH d AS (
  SELECT r.src_row,
         NULLIF(TRIM(r.order_item_id), '') AS order_item_id,
         NULLIF(TRIM(r.order_id), '')      AS order_id,
         NULLIF(TRIM(r.product_id), '')    AS product_id,
         NULLIF(TRIM(r.quantity), '')      AS quantity,
         NULLIF(TRIM(r.unit_price), '')    AS unit_price,
         ROW_NUMBER() OVER (PARTITION BY r.order_item_id, r.order_id, r.product_id, r.quantity, r.unit_price ORDER BY r.src_row) AS rn
  FROM RAW.V_ORDER_ITEMS_LATEST r),
u AS (
  SELECT d.*, COUNT(*) OVER (PARTITION BY d.order_item_id) AS key_cnt,
         CASE WHEN d.order_item_id IS NULL THEN 'order_item_id: required value missing'
              WHEN d.order_id      IS NULL THEN 'order_id: required value missing'
              WHEN d.product_id    IS NULL THEN 'product_id: required value missing'
              WHEN d.quantity      IS NULL THEN 'quantity: required value missing'
              WHEN d.unit_price    IS NULL THEN 'unit_price: required value missing'
              WHEN NOT REGEXP_LIKE(d.quantity, '[0-9]+') THEN 'quantity: expected non-negative integer KRW/quantity'
              WHEN TRY_TO_NUMBER(d.quantity) > 1000000000000 THEN 'quantity: exceeds project input limit'
              WHEN NOT REGEXP_LIKE(d.unit_price, '[0-9]+') THEN 'unit_price: expected non-negative integer KRW/quantity'
              WHEN TRY_TO_NUMBER(d.unit_price) > 1000000000000 THEN 'unit_price: exceeds project input limit'
              WHEN TRY_TO_NUMBER(d.quantity) = 0 THEN 'quantity must be positive' END AS err
  FROM d WHERE d.rn = 1)
SELECT src_row, order_item_id, order_id, product_id, quantity, unit_price, 'DUPLICATE' AS dq_status, CAST(NULL AS VARCHAR) AS err FROM d WHERE rn > 1
UNION ALL
SELECT src_row, order_item_id, order_id, product_id, quantity, unit_price,
       CASE WHEN order_item_id IS NOT NULL AND key_cnt > 1 THEN 'CONFLICT' WHEN err IS NOT NULL THEN 'INVALID' ELSE 'OK' END, err
FROM u;

INSERT INTO CORE.ISSUES_WORK
SELECT 'order_items.csv', src_row, order_item_id,
       CASE dq_status WHEN 'DUPLICATE' THEN 'EXACT_DUPLICATE' WHEN 'CONFLICT' THEN 'KEY_CONFLICT' ELSE 'INVALID_VALUE' END,
       CASE dq_status WHEN 'DUPLICATE' THEN 'Identical source row removed' WHEN 'CONFLICT' THEN 'Same business key has conflicting source rows' ELSE err END,
       order_id, CASE dq_status WHEN 'DUPLICATE' THEN 'REMOVED' ELSE 'QUARANTINED' END
FROM CORE.ORDER_ITEMS_CHK WHERE dq_status <> 'OK';

-- 주문이 없는 상세는 날짜·고객을 알 수 없으므로 격리
INSERT INTO CORE.ISSUES_WORK
SELECT 'order_items.csv', src_row, order_item_id, 'INVALID_REFERENCE', 'Parent order not found: quarantined', order_id, 'QUARANTINED'
FROM CORE.ORDER_ITEMS_CHK
WHERE dq_status = 'OK' AND order_id NOT IN (SELECT order_id FROM CORE.ORDERS);

CREATE OR REPLACE TABLE CORE.ORDER_ITEMS AS
SELECT c.order_item_id, c.order_id, c.product_id,
       TO_NUMBER(c.quantity) AS quantity, TO_NUMBER(c.unit_price) AS unit_price,
       c.product_id IN (SELECT product_id FROM CORE.PRODUCTS) AS has_valid_product,
       c.src_row
FROM CORE.ORDER_ITEMS_CHK c
WHERE c.dq_status = 'OK' AND c.order_id IN (SELECT order_id FROM CORE.ORDERS);

INSERT INTO CORE.ISSUES_WORK
SELECT 'order_items.csv', src_row, order_item_id, 'INVALID_REFERENCE', 'Unknown product: loaded with product_key = -1', order_id, 'FLAGGED'
FROM CORE.ORDER_ITEMS WHERE NOT has_valid_product;

-- ---------- payments ----------
CREATE OR REPLACE TABLE CORE.PAYMENTS_CHK AS
WITH d AS (
  SELECT r.src_row,
         NULLIF(TRIM(r.payment_id), '')     AS payment_id,
         NULLIF(TRIM(r.order_id), '')       AS order_id,
         NULLIF(TRIM(r.payment_status), '') AS payment_status,
         NULLIF(TRIM(r.payment_amount), '') AS payment_amount,
         NULLIF(TRIM(r.paid_at), '')        AS paid_at,
         ROW_NUMBER() OVER (PARTITION BY r.payment_id, r.order_id, r.payment_status, r.payment_amount, r.paid_at ORDER BY r.src_row) AS rn
  FROM RAW.V_PAYMENTS_LATEST r),
u AS (
  SELECT d.*, COUNT(*) OVER (PARTITION BY d.payment_id) AS key_cnt,
         CASE WHEN d.payment_id     IS NULL THEN 'payment_id: required value missing'
              WHEN d.order_id       IS NULL THEN 'order_id: required value missing'
              WHEN d.payment_status IS NULL THEN 'payment_status: required value missing'
              WHEN d.payment_amount IS NULL THEN 'payment_amount: required value missing'
              WHEN d.paid_at        IS NULL THEN 'paid_at: required value missing'
              WHEN NOT REGEXP_LIKE(d.payment_amount, '[0-9]+') THEN 'payment_amount: expected non-negative integer KRW/quantity'
              WHEN TRY_TO_NUMBER(d.payment_amount) > 1000000000000 THEN 'payment_amount: exceeds project input limit'
              WHEN d.payment_status NOT IN ('succeeded', 'failed', 'pending') THEN 'unknown payment_status'
              WHEN TRY_TO_TIMESTAMP_NTZ(d.paid_at, 'YYYY-MM-DD HH24:MI:SS') IS NULL THEN 'paid_at: invalid timestamp' END AS err
  FROM d WHERE d.rn = 1)
SELECT src_row, payment_id, order_id, payment_status, payment_amount, paid_at, 'DUPLICATE' AS dq_status, CAST(NULL AS VARCHAR) AS err FROM d WHERE rn > 1
UNION ALL
SELECT src_row, payment_id, order_id, payment_status, payment_amount, paid_at,
       CASE WHEN payment_id IS NOT NULL AND key_cnt > 1 THEN 'CONFLICT' WHEN err IS NOT NULL THEN 'INVALID' ELSE 'OK' END, err
FROM u;

INSERT INTO CORE.ISSUES_WORK
SELECT 'payments.csv', src_row, payment_id,
       CASE dq_status WHEN 'DUPLICATE' THEN 'EXACT_DUPLICATE' WHEN 'CONFLICT' THEN 'KEY_CONFLICT' ELSE 'INVALID_VALUE' END,
       CASE dq_status WHEN 'DUPLICATE' THEN 'Identical source row removed' WHEN 'CONFLICT' THEN 'Same business key has conflicting source rows' ELSE err END,
       order_id, CASE dq_status WHEN 'DUPLICATE' THEN 'REMOVED' ELSE 'QUARANTINED' END
FROM CORE.PAYMENTS_CHK WHERE dq_status <> 'OK';

CREATE OR REPLACE TABLE CORE.PAYMENTS AS
SELECT c.payment_id, c.order_id, c.payment_status,
       TO_NUMBER(c.payment_amount) AS payment_amount,
       TO_TIMESTAMP_NTZ(c.paid_at, 'YYYY-MM-DD HH24:MI:SS') AS paid_at,
       c.order_id IN (SELECT order_id FROM CORE.ORDERS) AS has_valid_order,
       c.src_row
FROM CORE.PAYMENTS_CHK c WHERE c.dq_status = 'OK';

INSERT INTO CORE.ISSUES_WORK
SELECT 'payments.csv', src_row, payment_id, 'INVALID_REFERENCE', 'Parent order not found: loaded with customer_key = -1', order_id, 'FLAGGED'
FROM CORE.PAYMENTS WHERE NOT has_valid_order;
-- <<< LOGIC END (정제)

-- 확인 (기대값): REMOVED 473 / QUARANTINED 441 / FLAGGED 286 (STEP 5 이후 559)
SELECT action, error_code, COUNT(*) AS events FROM CORE.ISSUES_WORK GROUP BY action, error_code ORDER BY action, error_code;
