-- 02_load_raw_from_git.sql
-- STEP 3 · RAW 적재 (Git 저장소 data/raw → 스테이지 @RAW.LANDING/current/ → RAW 새 배치). Python --load 는 이 파일 대신 로컬 CSV 를 같은 형태로 적재합니다.
-- 원본: notebooks/ae101_enterprise_walkthrough.ipynb (셀 step0_fetch, step3_0_landing, step3). 노트북과 같은 내용을 유지합니다.
-- 새 무작위 데이터를 쓰려면 3-0a 다음에 CALL RAW.GENERATE_LANDING_FILES('random', 0); 을 실행하세요 (노트북은 step3_0_generate 셀이 대신함).

USE ROLE ACCOUNTADMIN;
ALTER GIT REPOSITORY AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE FETCH;

-- 3-0a. Git 저장소의 data/raw 를 스테이지 @RAW.LANDING/current/ 로 복사합니다 (같은 이름의 파일은 덮어씀).
--       STEP 1 을 이 단계가 생기기 전에 실행했다면 스테이지가 없으므로 여기서도 만듭니다 (이미 있으면 그대로).
CREATE STAGE IF NOT EXISTS RAW.LANDING
  COMMENT = 'STEP 3 원본 파일: current/ = 이번 배치, batches/<load_id>/ = 배치별 answer_key.json';

COPY FILES INTO @RAW.LANDING/current/
  FROM @AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE/branches/main/data/raw/
  FILES = ('customers.csv', 'products.csv', 'orders.csv', 'order_items.csv', 'payments.csv', 'answer_key.json');

INSERT INTO RAW.CUSTOMERS (load_id, loaded_at, src_file, src_row, customer_id, customer_name, email, region)
SELECT $load_id, $run_ts, 'customers.csv', ROW_NUMBER() OVER (ORDER BY METADATA$FILE_ROW_NUMBER) + 1, $1, $2, $3, $4
FROM @RAW.LANDING/current/customers.csv (FILE_FORMAT => 'AE101_SALES_ENT.RAW.CSV_FORMAT');

INSERT INTO RAW.PRODUCTS (load_id, loaded_at, src_file, src_row, product_id, product_name, category)
SELECT $load_id, $run_ts, 'products.csv', ROW_NUMBER() OVER (ORDER BY METADATA$FILE_ROW_NUMBER) + 1, $1, $2, $3
FROM @RAW.LANDING/current/products.csv (FILE_FORMAT => 'AE101_SALES_ENT.RAW.CSV_FORMAT');

INSERT INTO RAW.ORDERS (load_id, loaded_at, src_file, src_row, order_id, customer_id, order_date, order_status, order_amount)
SELECT $load_id, $run_ts, 'orders.csv', ROW_NUMBER() OVER (ORDER BY METADATA$FILE_ROW_NUMBER) + 1, $1, $2, $3, $4, $5
FROM @RAW.LANDING/current/orders.csv (FILE_FORMAT => 'AE101_SALES_ENT.RAW.CSV_FORMAT');

INSERT INTO RAW.ORDER_ITEMS (load_id, loaded_at, src_file, src_row, order_item_id, order_id, product_id, quantity, unit_price)
SELECT $load_id, $run_ts, 'order_items.csv', ROW_NUMBER() OVER (ORDER BY METADATA$FILE_ROW_NUMBER) + 1, $1, $2, $3, $4, $5
FROM @RAW.LANDING/current/order_items.csv (FILE_FORMAT => 'AE101_SALES_ENT.RAW.CSV_FORMAT');

INSERT INTO RAW.PAYMENTS (load_id, loaded_at, src_file, src_row, payment_id, order_id, payment_status, payment_amount, paid_at)
SELECT $load_id, $run_ts, 'payments.csv', ROW_NUMBER() OVER (ORDER BY METADATA$FILE_ROW_NUMBER) + 1, $1, $2, $3, $4, $5
FROM @RAW.LANDING/current/payments.csv (FILE_FORMAT => 'AE101_SALES_ENT.RAW.CSV_FORMAT');

-- 확인: 배치별 행 수 (정답표 데이터면 최신 배치 합계 129,618 = 고객 2,028 + 상품 151 + 주문 30,081 + 상세 66,262 + 결제 31,096)
SELECT 'customers' AS file, load_id, COUNT(*) AS row_count FROM RAW.CUSTOMERS GROUP BY load_id
UNION ALL SELECT 'products',    load_id, COUNT(*) FROM RAW.PRODUCTS    GROUP BY load_id
UNION ALL SELECT 'orders',      load_id, COUNT(*) FROM RAW.ORDERS      GROUP BY load_id
UNION ALL SELECT 'order_items', load_id, COUNT(*) FROM RAW.ORDER_ITEMS GROUP BY load_id
UNION ALL SELECT 'payments',    load_id, COUNT(*) FROM RAW.PAYMENTS    GROUP BY load_id;
