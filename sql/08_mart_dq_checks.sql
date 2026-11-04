-- 08_mart_dq_checks.sql
-- STEP 7-3 · 품질 검사 17개 → AUDIT.DQ_RESULTS
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step7_3_dq, step7_3_dq_view). 노트북과 같은 내용을 유지합니다.

-- 7-3. 품질 검사 (failures 가 모두 0 이어야 COMMIT)
DELETE FROM AUDIT.DQ_RESULTS WHERE load_id = $load_id;   -- 같은 배치를 다시 실행해도 결과가 중복되지 않게
INSERT INTO AUDIT.DQ_RESULTS (load_id, check_name, failures)
SELECT $load_id, check_name, failures FROM (
  SELECT 'dim_customer_one_current_version' AS check_name, COUNT(*) AS failures
    FROM (SELECT customer_id FROM MART.DIM_CUSTOMER GROUP BY customer_id HAVING SUM(CASE WHEN is_current THEN 1 ELSE 0 END) <> 1) x
  UNION ALL SELECT 'dim_customer_key_unique', COUNT(*)
    FROM (SELECT customer_key FROM MART.DIM_CUSTOMER GROUP BY customer_key HAVING COUNT(*) > 1) x
  UNION ALL SELECT 'dim_customer_valid_range', COUNT(*)
    FROM MART.DIM_CUSTOMER WHERE valid_to IS NOT NULL AND valid_to <= valid_from
  UNION ALL SELECT 'dim_product_one_current_version', COUNT(*)
    FROM (SELECT product_id FROM MART.DIM_PRODUCT GROUP BY product_id HAVING SUM(CASE WHEN is_current THEN 1 ELSE 0 END) <> 1) x
  UNION ALL SELECT 'dim_product_key_unique', COUNT(*)
    FROM (SELECT product_key FROM MART.DIM_PRODUCT GROUP BY product_key HAVING COUNT(*) > 1) x
  UNION ALL SELECT 'fact_sales_line_key_unique', COUNT(*)
    FROM (SELECT order_item_id FROM MART.FACT_SALES_LINE GROUP BY order_item_id HAVING COUNT(*) > 1) x
  UNION ALL SELECT 'fact_sales_line_customer_fk', COUNT(*)
    FROM MART.FACT_SALES_LINE f LEFT JOIN MART.DIM_CUSTOMER c ON f.customer_key = c.customer_key WHERE c.customer_key IS NULL
  UNION ALL SELECT 'fact_sales_line_product_fk', COUNT(*)
    FROM MART.FACT_SALES_LINE f LEFT JOIN MART.DIM_PRODUCT p ON f.product_key = p.product_key WHERE p.product_key IS NULL
  UNION ALL SELECT 'fact_sales_line_date_fk', COUNT(*)
    FROM MART.FACT_SALES_LINE f LEFT JOIN MART.DIM_DATE d ON f.order_date_key = d.date_key WHERE d.date_key IS NULL
  UNION ALL SELECT 'fact_sales_line_status_fk', COUNT(*)
    FROM MART.FACT_SALES_LINE f LEFT JOIN MART.DIM_ORDER_STATUS s ON f.order_status_key = s.order_status_key WHERE s.order_status_key IS NULL
  UNION ALL SELECT 'fact_sales_line_amount_calc', COUNT(*)
    FROM MART.FACT_SALES_LINE WHERE quantity <= 0 OR unit_price < 0 OR line_amount <> quantity * unit_price
  UNION ALL SELECT 'fact_payment_key_unique', COUNT(*)
    FROM (SELECT payment_id FROM MART.FACT_PAYMENT GROUP BY payment_id HAVING COUNT(*) > 1) x
  UNION ALL SELECT 'fact_payment_status_fk', COUNT(*)
    FROM MART.FACT_PAYMENT f LEFT JOIN MART.DIM_PAYMENT_STATUS s ON f.payment_status_key = s.payment_status_key WHERE s.payment_status_key IS NULL
  UNION ALL SELECT 'fact_order_lifecycle_key_unique', COUNT(*)
    FROM (SELECT order_id FROM MART.FACT_ORDER_LIFECYCLE GROUP BY order_id HAVING COUNT(*) > 1) x
  UNION ALL SELECT 'revenue_order_reconciliation', COUNT(*)
    FROM MART.FACT_ORDER_LIFECYCLE
   WHERE is_revenue_eligible AND NOT is_deleted
     AND (order_amount <> line_amount_total OR order_amount <> success_payment_amount OR success_payment_count <> 1)
  UNION ALL SELECT 'revenue_line_vs_order', COUNT(*)
    FROM MART.FACT_ORDER_LIFECYCLE o
    LEFT JOIN (SELECT order_id, SUM(line_amount) AS amt FROM MART.FACT_SALES_LINE WHERE NOT is_deleted GROUP BY order_id) l
           ON o.order_id = l.order_id
   WHERE o.is_revenue_eligible AND NOT o.is_deleted AND (l.amt IS NULL OR l.amt <> o.order_amount)
  UNION ALL SELECT 'revenue_requires_known_keys', COUNT(*)
    FROM MART.FACT_SALES_LINE
   WHERE is_revenue_eligible AND NOT is_deleted AND (customer_key = -1 OR product_key = -1 OR order_date_key = -1)
) checks;

SELECT check_name, failures FROM AUDIT.DQ_RESULTS WHERE load_id = $load_id ORDER BY failures DESC, check_name;   -- 전부 0
