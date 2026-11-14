-- 00_setup.sql
-- STEP 1 · DDL : DB/스키마/RAW/AUDIT/MART 테이블 생성 (한 번만, 다시 실행해도 데이터 유지)
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step1). 노트북과 같은 내용을 유지합니다.

CREATE DATABASE IF NOT EXISTS AE101_SALES_ENT;
USE DATABASE AE101_SALES_ENT;

CREATE SCHEMA IF NOT EXISTS RAW;
CREATE SCHEMA IF NOT EXISTS CORE;
CREATE SCHEMA IF NOT EXISTS MART;
CREATE SCHEMA IF NOT EXISTS AUDIT;
CREATE SCHEMA IF NOT EXISTS SECURITY;

CREATE OR REPLACE FILE FORMAT RAW.CSV_FORMAT
  TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"' ENCODING = 'UTF8';

-- 1-1. RAW : 원본 그대로 + 메타데이터(load_id, loaded_at, src_file, src_row). 추가(append)만 합니다.
CREATE TABLE IF NOT EXISTS RAW.CUSTOMERS (
  load_id VARCHAR, loaded_at TIMESTAMP_NTZ, src_file VARCHAR, src_row NUMBER,
  customer_id VARCHAR, customer_name VARCHAR, email VARCHAR, region VARCHAR);
CREATE TABLE IF NOT EXISTS RAW.PRODUCTS (
  load_id VARCHAR, loaded_at TIMESTAMP_NTZ, src_file VARCHAR, src_row NUMBER,
  product_id VARCHAR, product_name VARCHAR, category VARCHAR);
CREATE TABLE IF NOT EXISTS RAW.ORDERS (
  load_id VARCHAR, loaded_at TIMESTAMP_NTZ, src_file VARCHAR, src_row NUMBER,
  order_id VARCHAR, customer_id VARCHAR, order_date VARCHAR, order_status VARCHAR, order_amount VARCHAR);
CREATE TABLE IF NOT EXISTS RAW.ORDER_ITEMS (
  load_id VARCHAR, loaded_at TIMESTAMP_NTZ, src_file VARCHAR, src_row NUMBER,
  order_item_id VARCHAR, order_id VARCHAR, product_id VARCHAR, quantity VARCHAR, unit_price VARCHAR);
CREATE TABLE IF NOT EXISTS RAW.PAYMENTS (
  load_id VARCHAR, loaded_at TIMESTAMP_NTZ, src_file VARCHAR, src_row NUMBER,
  payment_id VARCHAR, order_id VARCHAR, payment_status VARCHAR, payment_amount VARCHAR, paid_at VARCHAR);

-- 테이블별 "가장 최근 배치"만 보여주는 뷰. CORE 는 항상 이 뷰를 읽습니다.
CREATE OR REPLACE VIEW RAW.V_CUSTOMERS_LATEST   AS SELECT * FROM RAW.CUSTOMERS   QUALIFY loaded_at = MAX(loaded_at) OVER ();
CREATE OR REPLACE VIEW RAW.V_PRODUCTS_LATEST    AS SELECT * FROM RAW.PRODUCTS    QUALIFY loaded_at = MAX(loaded_at) OVER ();
CREATE OR REPLACE VIEW RAW.V_ORDERS_LATEST      AS SELECT * FROM RAW.ORDERS      QUALIFY loaded_at = MAX(loaded_at) OVER ();
CREATE OR REPLACE VIEW RAW.V_ORDER_ITEMS_LATEST AS SELECT * FROM RAW.ORDER_ITEMS QUALIFY loaded_at = MAX(loaded_at) OVER ();
CREATE OR REPLACE VIEW RAW.V_PAYMENTS_LATEST    AS SELECT * FROM RAW.PAYMENTS    QUALIFY loaded_at = MAX(loaded_at) OVER ();

-- 1-1b. 착륙장(landing) : STEP 3 이 읽을 원본 파일을 두는 내부 스테이지와, 새 데이터를 만들어 올리는 프로시저
--   @RAW.LANDING/current/            이번 배치가 읽을 CSV 5개 + answer_key.json (STEP 3-0 이 매번 채움)
--   @RAW.LANDING/batches/<load_id>/  배치마다 쓴 answer_key.json 사본 (어떤 데이터를 적재했는지 기록)
CREATE STAGE IF NOT EXISTS RAW.LANDING
  COMMENT = 'STEP 3 원본 파일: current/ = 이번 배치, batches/<load_id>/ = 배치별 answer_key.json';

-- 생성기(scripts/generate_data.py)를 Git 저장소에서 불러와 Snowflake 안에서 실행합니다. 파일은 메모리에서 만들어 스테이지에 바로 올립니다.
-- 생성기를 고친 뒤에는 STEP 0 의 FETCH 다음에 이 문장을 다시 실행하세요.
CREATE OR REPLACE PROCEDURE RAW.GENERATE_LANDING_FILES(SOURCE VARCHAR, SEED NUMBER)
  RETURNS VARIANT
  LANGUAGE PYTHON
  RUNTIME_VERSION = '3.11'
  PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE/branches/main/scripts/generate_data.py')
  HANDLER = 'generate_data.land_to_stage'
  COMMENT = 'AE101 합성 데이터를 만들어 @RAW.LANDING/current/ 에 올림. SOURCE = random | answer-key, SEED = 0 이면 새로 뽑음';

-- 1-2. AUDIT
CREATE TABLE IF NOT EXISTS AUDIT.PIPELINE_RUNS (
  load_id VARCHAR NOT NULL, status VARCHAR NOT NULL, started_at TIMESTAMP_NTZ NOT NULL, finished_at TIMESTAMP_NTZ,
  input_rows NUMBER, duplicate_rows NUMBER, quarantined_rows NUMBER, flagged_issues NUMBER,
  revenue_orders NUMBER, revenue_amount NUMBER(38,0), message VARCHAR);
CREATE TABLE IF NOT EXISTS AUDIT.DATA_ISSUES (
  load_id VARCHAR NOT NULL, source_file VARCHAR, source_row_number NUMBER, record_key VARCHAR,
  error_code VARCHAR, error_detail VARCHAR, order_id VARCHAR,
  action VARCHAR);   -- REMOVED(완전 중복 제거) / QUARANTINED(격리, 미적재) / FLAGGED(적재하되 표시)
CREATE TABLE IF NOT EXISTS AUDIT.DQ_RESULTS (
  load_id VARCHAR NOT NULL, check_name VARCHAR NOT NULL, failures NUMBER NOT NULL);

-- 1-3. MART 차원 (3-2, 3-3) : 대리키 + SCD Type 2
CREATE SEQUENCE IF NOT EXISTS MART.SEQ_CUSTOMER_KEY START = 1 INCREMENT = 1;
CREATE SEQUENCE IF NOT EXISTS MART.SEQ_PRODUCT_KEY  START = 1 INCREMENT = 1;

CREATE TABLE IF NOT EXISTS MART.DIM_CUSTOMER (
  customer_key   NUMBER DEFAULT MART.SEQ_CUSTOMER_KEY.NEXTVAL NOT NULL,  -- 대리키
  customer_id    VARCHAR NOT NULL,                                       -- 업무 키
  customer_name  VARCHAR,
  email          VARCHAR,                                                -- PII: STEP 9 에서 마스킹
  region         VARCHAR,                                                -- STEP 9 행 수준 보안 기준
  valid_from     TIMESTAMP_NTZ NOT NULL,
  valid_to       TIMESTAMP_NTZ,                                          -- NULL = 현재 유효
  is_current     BOOLEAN NOT NULL,
  hash_diff      VARCHAR,                                                -- 변경 감지용 해시
  load_id        VARCHAR,
  CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY (customer_key));

CREATE TABLE IF NOT EXISTS MART.DIM_PRODUCT (
  product_key    NUMBER DEFAULT MART.SEQ_PRODUCT_KEY.NEXTVAL NOT NULL,
  product_id     VARCHAR NOT NULL,
  product_name   VARCHAR,
  category       VARCHAR,
  valid_from     TIMESTAMP_NTZ NOT NULL,
  valid_to       TIMESTAMP_NTZ,
  is_current     BOOLEAN NOT NULL,
  hash_diff      VARCHAR,
  load_id        VARCHAR,
  CONSTRAINT PK_DIM_PRODUCT PRIMARY KEY (product_key));

-- Unknown 멤버(-1): 참조 대상이 없는 Fact 도 버리지 않고 적재하기 위한 자리
INSERT INTO MART.DIM_CUSTOMER (customer_key, customer_id, customer_name, email, region, valid_from, valid_to, is_current, hash_diff, load_id)
SELECT -1, '-1', 'Unknown', NULL, 'Unknown', '1900-01-01'::TIMESTAMP_NTZ, NULL, TRUE, NULL, 'SEED'
WHERE NOT EXISTS (SELECT 1 FROM MART.DIM_CUSTOMER WHERE customer_key = -1);

INSERT INTO MART.DIM_PRODUCT (product_key, product_id, product_name, category, valid_from, valid_to, is_current, hash_diff, load_id)
SELECT -1, '-1', 'Unknown', 'Unknown', '1900-01-01'::TIMESTAMP_NTZ, NULL, TRUE, NULL, 'SEED'
WHERE NOT EXISTS (SELECT 1 FROM MART.DIM_PRODUCT WHERE product_key = -1);

-- 전체 달력 2020-01-01 ~ 2030-12-31 (4,018일) + Unknown(-1)
CREATE OR REPLACE TABLE MART.DIM_DATE AS
WITH days AS (
  SELECT DATEADD(day, ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1, '2020-01-01'::DATE) AS d
  FROM TABLE(GENERATOR(ROWCOUNT => 4018)))
SELECT YEAR(d) * 10000 + MONTH(d) * 100 + DAY(d)       AS date_key,
       d                                               AS calendar_date,
       YEAR(d)                                         AS year,
       QUARTER(d)                                      AS quarter,
       MONTH(d)                                        AS month,
       TO_CHAR(d, 'YYYY-MM')                           AS year_month,
       DAY(d)                                          AS day_of_month,
       DAYOFWEEKISO(d)                                 AS day_of_week,     -- 1=월 ... 7=일
       DAYNAME(d)                                      AS day_name,
       DAYOFWEEKISO(d) IN (6, 7)                       AS is_weekend
FROM days
UNION ALL
SELECT -1, '1900-01-01'::DATE, 1900, 1, 1, 'Unknown', 1, 1, 'Unk', FALSE;

CREATE OR REPLACE TABLE MART.DIM_ORDER_STATUS AS
SELECT * FROM (VALUES
  ( 1, 'completed', '완료', TRUE),
  ( 2, 'pending',   '대기', FALSE),
  ( 3, 'cancelled', '취소', TRUE),
  (-1, 'unknown',   '알 수 없음', FALSE)
) AS v(order_status_key, status_code, status_name, is_final);

CREATE OR REPLACE TABLE MART.DIM_PAYMENT_STATUS AS
SELECT * FROM (VALUES
  ( 1, 'succeeded', '성공', TRUE),
  ( 2, 'failed',    '실패', FALSE),
  ( 3, 'pending',   '대기', FALSE),
  (-1, 'unknown',   '알 수 없음', FALSE)
) AS v(payment_status_key, status_code, status_name, is_success);
-- 참고: 원본 payments.csv 에는 결제 수단 컬럼이 없어 dim_payment_method 대신 결제 상태 차원을 둡니다.

-- 1-4. MART Fact (3-2)
-- 입도: 주문 상세 1행. 매출 분석의 중심 Fact
CREATE TABLE IF NOT EXISTS MART.FACT_SALES_LINE (
  order_item_id       VARCHAR NOT NULL,      -- degenerate key (입도 식별자)
  order_id            VARCHAR NOT NULL,      -- degenerate dimension
  customer_key        NUMBER  NOT NULL,      -- 주문일 시점의 고객 버전
  product_key         NUMBER  NOT NULL,      -- 주문일 시점의 상품 버전
  order_date_key      NUMBER  NOT NULL,
  order_status_key    NUMBER  NOT NULL,
  order_date          DATE,
  quantity            NUMBER(38,0),
  unit_price          NUMBER(38,0),
  line_amount         NUMBER(38,0),
  is_revenue_eligible BOOLEAN NOT NULL,      -- 매출 인식 여부 (STEP 5 규칙)
  exclusion_reason    VARCHAR,               -- 매출 제외 사유
  is_deleted          BOOLEAN NOT NULL,      -- 소프트 삭제
  load_id             VARCHAR,
  updated_at          TIMESTAMP_NTZ,
  CONSTRAINT PK_FACT_SALES_LINE PRIMARY KEY (order_item_id),
  CONSTRAINT FK_SL_CUSTOMER FOREIGN KEY (customer_key) REFERENCES MART.DIM_CUSTOMER (customer_key),
  CONSTRAINT FK_SL_PRODUCT  FOREIGN KEY (product_key)  REFERENCES MART.DIM_PRODUCT (product_key));

-- 입도: 결제 시도 1건
CREATE TABLE IF NOT EXISTS MART.FACT_PAYMENT (
  payment_id          VARCHAR NOT NULL,
  order_id            VARCHAR,
  customer_key        NUMBER  NOT NULL,
  paid_date_key       NUMBER  NOT NULL,
  payment_status_key  NUMBER  NOT NULL,
  paid_at             TIMESTAMP_NTZ,
  payment_amount      NUMBER(38,0),
  has_valid_order     BOOLEAN NOT NULL,
  is_deleted          BOOLEAN NOT NULL,
  load_id             VARCHAR,
  updated_at          TIMESTAMP_NTZ,
  CONSTRAINT PK_FACT_PAYMENT PRIMARY KEY (payment_id));

-- 입도: 주문 1건 (Accumulating Snapshot). 주문의 진행 단계를 한 행에 누적
CREATE TABLE IF NOT EXISTS MART.FACT_ORDER_LIFECYCLE (
  order_id                     VARCHAR NOT NULL,
  customer_key                 NUMBER  NOT NULL,
  order_date_key               NUMBER  NOT NULL,
  first_success_paid_date_key  NUMBER  NOT NULL,   -- 성공 결제 전이면 -1
  order_status_key             NUMBER  NOT NULL,
  order_date                   DATE,
  first_success_paid_at        TIMESTAMP_NTZ,
  order_amount                 NUMBER(38,0),       -- 헤더 금액은 주문 입도 Fact 에만 둡니다 (이중 집계 방지)
  line_count                   NUMBER,
  line_amount_total            NUMBER(38,0),
  success_payment_count        NUMBER,
  success_payment_amount       NUMBER(38,0),
  days_to_first_success_payment NUMBER,
  is_revenue_eligible          BOOLEAN NOT NULL,
  exclusion_reason             VARCHAR,
  is_deleted                   BOOLEAN NOT NULL,
  load_id                      VARCHAR,
  updated_at                   TIMESTAMP_NTZ,
  CONSTRAINT PK_FACT_ORDER_LIFECYCLE PRIMARY KEY (order_id));
-- 참고: Snowflake 의 PK/FK 는 문서·BI 도구용 "선언"이며 강제되지 않습니다. 그래서 STEP 7 에서 직접 검사합니다.
