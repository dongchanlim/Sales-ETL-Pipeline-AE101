MERGE INTO DW.fact_orders AS target
USING (SELECT order_id, customer_id, date_key, order_amount FROM STG.fact_orders WHERE run_id = %s) AS source
ON target.order_id = source.order_id
WHEN MATCHED THEN UPDATE SET target.customer_id = source.customer_id, target.date_key = source.date_key, target.order_amount = source.order_amount
WHEN NOT MATCHED THEN INSERT (order_id, customer_id, date_key, order_amount)
VALUES (source.order_id, source.customer_id, source.date_key, source.order_amount);

MERGE INTO DW.fact_order_items AS target
USING (SELECT order_item_id, order_id, product_id, quantity, unit_price, line_amount FROM STG.fact_order_items WHERE run_id = %s) AS source
ON target.order_item_id = source.order_item_id
WHEN MATCHED THEN UPDATE SET target.order_id = source.order_id, target.product_id = source.product_id, target.quantity = source.quantity, target.unit_price = source.unit_price, target.line_amount = source.line_amount
WHEN NOT MATCHED THEN INSERT (order_item_id, order_id, product_id, quantity, unit_price, line_amount)
VALUES (source.order_item_id, source.order_id, source.product_id, source.quantity, source.unit_price, source.line_amount);
