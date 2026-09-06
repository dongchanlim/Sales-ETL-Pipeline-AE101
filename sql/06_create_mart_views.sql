CREATE OR REPLACE VIEW MART.DAILY_SALES AS
SELECT d.calendar_date AS order_date, COUNT(*) AS order_count,
       SUM(o.order_amount) AS sales_amount
FROM DW.fact_orders o JOIN DW.dim_date d ON o.date_key=d.date_key
GROUP BY d.calendar_date;

CREATE OR REPLACE VIEW MART.PRODUCT_SALES AS
SELECT d.calendar_date AS order_date, p.product_id, p.product_name, p.category,
       SUM(i.quantity) AS quantity, SUM(i.line_amount) AS sales_amount
FROM DW.fact_order_items i
JOIN DW.fact_orders o ON i.order_id=o.order_id
JOIN DW.dim_date d ON o.date_key=d.date_key
JOIN DW.dim_product p ON i.product_id=p.product_id
GROUP BY d.calendar_date,p.product_id,p.product_name,p.category;

CREATE OR REPLACE VIEW MART.LATEST_RUN AS
SELECT * FROM AUDIT.PIPELINE_RUNS
QUALIFY ROW_NUMBER() OVER (ORDER BY started_at DESC, run_id DESC)=1;

CREATE OR REPLACE VIEW MART.LAST_SUCCESSFUL_RUN AS
SELECT * FROM AUDIT.PIPELINE_RUNS WHERE status='SUCCESS'
QUALIFY ROW_NUMBER() OVER (ORDER BY finished_at DESC,run_id DESC)=1;
