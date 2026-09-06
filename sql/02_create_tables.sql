CREATE TABLE IF NOT EXISTS DW.dim_customer (
    customer_id VARCHAR NOT NULL,
    customer_name VARCHAR NOT NULL,
    region VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS STG.dim_customer (
    run_id VARCHAR NOT NULL,
    customer_id VARCHAR NOT NULL,
    customer_name VARCHAR NOT NULL,
    region VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS DW.dim_product (
    product_id VARCHAR NOT NULL,
    product_name VARCHAR NOT NULL,
    category VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS STG.dim_product (
    run_id VARCHAR NOT NULL,
    product_id VARCHAR NOT NULL,
    product_name VARCHAR NOT NULL,
    category VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS DW.dim_date (
    date_key NUMBER(8,0) NOT NULL,
    calendar_date DATE NOT NULL,
    year NUMBER(4,0) NOT NULL,
    month NUMBER(2,0) NOT NULL,
    year_month VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS STG.dim_date (
    run_id VARCHAR NOT NULL,
    date_key NUMBER(8,0) NOT NULL,
    calendar_date DATE NOT NULL,
    year NUMBER(4,0) NOT NULL,
    month NUMBER(2,0) NOT NULL,
    year_month VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS DW.fact_orders (
    order_id VARCHAR NOT NULL,
    customer_id VARCHAR NOT NULL,
    date_key NUMBER(8,0) NOT NULL,
    order_amount NUMBER(38,0) NOT NULL
);

CREATE TABLE IF NOT EXISTS STG.fact_orders (
    run_id VARCHAR NOT NULL,
    order_id VARCHAR NOT NULL,
    customer_id VARCHAR NOT NULL,
    date_key NUMBER(8,0) NOT NULL,
    order_amount NUMBER(38,0) NOT NULL
);

CREATE TABLE IF NOT EXISTS DW.fact_order_items (
    order_item_id VARCHAR NOT NULL,
    order_id VARCHAR NOT NULL,
    product_id VARCHAR NOT NULL,
    quantity NUMBER(38,0) NOT NULL,
    unit_price NUMBER(38,0) NOT NULL,
    line_amount NUMBER(38,0) NOT NULL
);

CREATE TABLE IF NOT EXISTS STG.fact_order_items (
    run_id VARCHAR NOT NULL,
    order_item_id VARCHAR NOT NULL,
    order_id VARCHAR NOT NULL,
    product_id VARCHAR NOT NULL,
    quantity NUMBER(38,0) NOT NULL,
    unit_price NUMBER(38,0) NOT NULL,
    line_amount NUMBER(38,0) NOT NULL
);

CREATE TABLE IF NOT EXISTS AUDIT.PIPELINE_RUNS (
run_id VARCHAR NOT NULL, status VARCHAR NOT NULL,
started_at TIMESTAMP_LTZ NOT NULL, finished_at TIMESTAMP_LTZ,
input_rows NUMBER, duplicate_rows NUMBER, error_rows NUMBER,
excluded_orders NUMBER, sales_orders NUMBER, sales_amount NUMBER(38,0), message VARCHAR
);

CREATE TABLE IF NOT EXISTS AUDIT.DATA_ISSUES (
run_id VARCHAR NOT NULL, source_file VARCHAR, source_row_number NUMBER,
record_key VARCHAR, error_code VARCHAR, error_detail VARCHAR, order_id VARCHAR
);

CREATE TABLE IF NOT EXISTS AUDIT.EXCLUDED_ORDERS (
run_id VARCHAR NOT NULL, order_id VARCHAR, reason VARCHAR
);

CREATE TABLE IF NOT EXISTS AUDIT.VALIDATION_RESULTS (
run_id VARCHAR NOT NULL, check_name VARCHAR NOT NULL, failures NUMBER NOT NULL
);
