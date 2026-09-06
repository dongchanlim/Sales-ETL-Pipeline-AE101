SELECT 'dim_customer_duplicate_key' AS check_name, COUNT(*) AS failures FROM (SELECT customer_id FROM DW.dim_customer GROUP BY customer_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'dim_customer_required', COUNT(*) FROM DW.dim_customer WHERE customer_id IS NULL OR customer_name IS NULL OR region IS NULL
UNION ALL
SELECT 'dim_product_duplicate_key' AS check_name, COUNT(*) AS failures FROM (SELECT product_id FROM DW.dim_product GROUP BY product_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'dim_product_required', COUNT(*) FROM DW.dim_product WHERE product_id IS NULL OR product_name IS NULL OR category IS NULL
UNION ALL
SELECT 'dim_date_duplicate_key' AS check_name, COUNT(*) AS failures FROM (SELECT date_key FROM DW.dim_date GROUP BY date_key HAVING COUNT(*) > 1)
UNION ALL
SELECT 'dim_date_required', COUNT(*) FROM DW.dim_date WHERE date_key IS NULL OR calendar_date IS NULL OR year IS NULL OR month IS NULL OR year_month IS NULL
UNION ALL
SELECT 'fact_orders_duplicate_key' AS check_name, COUNT(*) AS failures FROM (SELECT order_id FROM DW.fact_orders GROUP BY order_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'fact_orders_required', COUNT(*) FROM DW.fact_orders WHERE order_id IS NULL OR customer_id IS NULL OR date_key IS NULL OR order_amount IS NULL
UNION ALL
SELECT 'fact_order_items_duplicate_key' AS check_name, COUNT(*) AS failures FROM (SELECT order_item_id FROM DW.fact_order_items GROUP BY order_item_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'fact_order_items_required', COUNT(*) FROM DW.fact_order_items WHERE order_item_id IS NULL OR order_id IS NULL OR product_id IS NULL OR quantity IS NULL OR unit_price IS NULL OR line_amount IS NULL
UNION ALL
SELECT 'order_customer_reference', COUNT(*) FROM DW.fact_orders o LEFT JOIN DW.dim_customer c ON o.customer_id=c.customer_id WHERE c.customer_id IS NULL
UNION ALL
SELECT 'order_date_reference', COUNT(*) FROM DW.fact_orders o LEFT JOIN DW.dim_date d ON o.date_key=d.date_key WHERE d.date_key IS NULL
UNION ALL
SELECT 'item_product_reference', COUNT(*) FROM DW.fact_order_items i LEFT JOIN DW.dim_product p ON i.product_id=p.product_id WHERE p.product_id IS NULL
UNION ALL
SELECT 'item_order_reference', COUNT(*) FROM DW.fact_order_items i LEFT JOIN DW.fact_orders o ON i.order_id=o.order_id WHERE o.order_id IS NULL
UNION ALL
SELECT 'order_amount_reconciliation', COUNT(*) FROM DW.fact_orders o LEFT JOIN (SELECT order_id, SUM(line_amount) amount FROM DW.fact_order_items GROUP BY order_id) i ON o.order_id=i.order_id WHERE i.order_id IS NULL OR o.order_amount<>i.amount
UNION ALL
SELECT 'line_amount_calculation', COUNT(*) FROM DW.fact_order_items WHERE quantity<=0 OR unit_price<0 OR line_amount<>quantity*unit_price;
