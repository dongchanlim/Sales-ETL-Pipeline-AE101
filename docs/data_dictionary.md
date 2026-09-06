# 데이터 사전

UTF-8 CSV, 한국 시간 기준, KRW 정수이며 모든 값은 교육용 합성 데이터입니다.

| 파일 | 한 행의 의미 | 키 | 컬럼 |
|---|---|---|---|
| customers.csv | 고객 | customer_id | customer_name: 이름, email: 선택 이메일, region: 선택 지역 |
| products.csv | 상품 | product_id | product_name: 이름, category: 분류 |
| orders.csv | 주문 | order_id | customer_id: 고객, order_date: 주문일, order_status: 상태, order_amount: 주문 금액 |
| order_items.csv | 주문 상품 항목 | order_item_id | order_id: 주문, product_id: 상품, quantity: 수량, unit_price: 거래 시점 단가 |
| payments.csv | 결제 시도 | payment_id | order_id: 주문, payment_status: 결제 상태, payment_amount: 시도 금액, paid_at: 시도 일시 |

`paid_at`은 실패 시도에서도 필수인 **결제 시도 일시**로 정의합니다. 성공 시 정산 일시를 뜻하지 않습니다.

| 허용값 | 정의 |
|---|---|
| completed / pending / cancelled | 완료 / 대기 / 취소 주문 |
| succeeded / failed / pending | 성공 / 실패 / 대기 결제 시도 |
| order_date | ISO 날짜 YYYY-MM-DD |
| paid_at | 시간대 오프셋 없는 ISO 날짜·시각; KST로 해석 |
| 금액 | 0 이상 정수, 입력 상한 10^12 KRW |
| quantity | 1 이상 정수, 입력 상한 10^12 |

선택값은 고객 email/region뿐입니다. 나머지 누락은 오류입니다. 각 원본 행에는 처리 중 `_file`, `_row` 메타데이터를 붙여 오류 위치를 보존합니다.
`date_key`는 YYYYMMDD 정수, `line_amount`는 quantity × unit_price입니다.
