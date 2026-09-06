MERGE INTO DW.dim_customer AS target
USING (SELECT customer_id, customer_name, region FROM STG.dim_customer WHERE run_id = %s) AS source
ON target.customer_id = source.customer_id
WHEN MATCHED THEN UPDATE SET target.customer_name = source.customer_name, target.region = source.region
WHEN NOT MATCHED THEN INSERT (customer_id, customer_name, region)
VALUES (source.customer_id, source.customer_name, source.region);

MERGE INTO DW.dim_product AS target
USING (SELECT product_id, product_name, category FROM STG.dim_product WHERE run_id = %s) AS source
ON target.product_id = source.product_id
WHEN MATCHED THEN UPDATE SET target.product_name = source.product_name, target.category = source.category
WHEN NOT MATCHED THEN INSERT (product_id, product_name, category)
VALUES (source.product_id, source.product_name, source.category);

MERGE INTO DW.dim_date AS target
USING (SELECT date_key, calendar_date, year, month, year_month FROM STG.dim_date WHERE run_id = %s) AS source
ON target.date_key = source.date_key
WHEN MATCHED THEN UPDATE SET target.calendar_date = source.calendar_date, target.year = source.year, target.month = source.month, target.year_month = source.year_month
WHEN NOT MATCHED THEN INSERT (date_key, calendar_date, year, month, year_month)
VALUES (source.date_key, source.calendar_date, source.year, source.month, source.year_month);
