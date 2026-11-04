-- 06_mart_dimensions.sql
-- STEP 7-0 ~ 7-1 · 실행 컨텍스트 복원·가드 → SCD2 차원 (DIM_CUSTOMER, DIM_PRODUCT)
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step7_0_ctx, step7_0_guard, step7_1a_dim_customer, step7_1b_dim_product). 노트북과 같은 내용을 유지합니다.

-- 새 세션(노트북 재시작 등)이면 변수가 사라집니다. CORE.RUN_CTX 에서 다시 읽어 옵니다.
SET load_id = (SELECT load_id FROM CORE.RUN_CTX);
SET run_ts  = (SELECT run_ts  FROM CORE.RUN_CTX);
SELECT $load_id AS load_id, $run_ts AS run_ts;

-- 이번 배치에 정상 주문이 있어야 MART 를 갱신합니다. 0 이면 아래 7-1 이후 셀을 실행하지 마세요.
SELECT $load_id AS load_id, $run_ts AS run_ts,
       (SELECT COUNT(*) FROM CORE.ORDERS) AS accepted_orders,
       IFF((SELECT COUNT(*) FROM CORE.ORDERS) = 0, '중단: 정상 주문 0건', 'OK') AS guard;

-- 7-1. SCD2 : dim_customer
UPDATE MART.DIM_CUSTOMER
   SET valid_to = $run_ts, is_current = FALSE
  FROM CORE.CUSTOMERS s
 WHERE MART.DIM_CUSTOMER.customer_id = s.customer_id
   AND MART.DIM_CUSTOMER.is_current
   AND MART.DIM_CUSTOMER.customer_key <> -1
   AND MART.DIM_CUSTOMER.hash_diff <> s.hash_diff;

INSERT INTO MART.DIM_CUSTOMER (customer_id, customer_name, email, region, valid_from, valid_to, is_current, hash_diff, load_id)
SELECT s.customer_id, s.customer_name, s.email, s.region,
       CASE WHEN h.customer_id IS NULL THEN '1900-01-01'::TIMESTAMP_NTZ ELSE $run_ts END,  -- 처음 보는 고객은 과거 전체에 유효
       NULL, TRUE, s.hash_diff, $load_id
FROM CORE.CUSTOMERS s
LEFT JOIN (SELECT DISTINCT customer_id FROM MART.DIM_CUSTOMER) h ON h.customer_id = s.customer_id
WHERE NOT EXISTS (SELECT 1 FROM MART.DIM_CUSTOMER d WHERE d.customer_id = s.customer_id AND d.is_current);

-- 7-1. SCD2 : dim_product
UPDATE MART.DIM_PRODUCT
   SET valid_to = $run_ts, is_current = FALSE
  FROM CORE.PRODUCTS s
 WHERE MART.DIM_PRODUCT.product_id = s.product_id
   AND MART.DIM_PRODUCT.is_current
   AND MART.DIM_PRODUCT.product_key <> -1
   AND MART.DIM_PRODUCT.hash_diff <> s.hash_diff;

INSERT INTO MART.DIM_PRODUCT (product_id, product_name, category, valid_from, valid_to, is_current, hash_diff, load_id)
SELECT s.product_id, s.product_name, s.category,
       CASE WHEN h.product_id IS NULL THEN '1900-01-01'::TIMESTAMP_NTZ ELSE $run_ts END,
       NULL, TRUE, s.hash_diff, $load_id
FROM CORE.PRODUCTS s
LEFT JOIN (SELECT DISTINCT product_id FROM MART.DIM_PRODUCT) h ON h.product_id = s.product_id
WHERE NOT EXISTS (SELECT 1 FROM MART.DIM_PRODUCT d WHERE d.product_id = s.product_id AND d.is_current);
