"""Deploy in Streamlit in Snowflake with the AE101 database selected."""
from datetime import date
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="AE101 Sales", layout="wide")
session = get_active_session()
st.title("AE Commerce · 매출 및 데이터 품질")
st.caption("한국 시간의 주문일 기준 · KRW · 검증된 completed 주문과 단일 성공 결제만 포함")
latest = session.sql("SELECT * FROM MART.LATEST_RUN").to_pandas()
success = session.sql("SELECT * FROM MART.LAST_SUCCESSFUL_RUN").to_pandas()
if not latest.empty:
    row = latest.iloc[0]
    st.write("최근 실행 상태:", row["STATUS"])
    if row["STATUS"] != "SUCCESS":
        st.warning("최근 실행이 성공하지 않았습니다. 아래 매출은 마지막으로 확정된 DW 데이터입니다.")
    st.dataframe(latest, hide_index=True)
if success.empty:
    st.info("아직 성공한 적재가 없습니다. 파이프라인 실행 결과를 확인하세요.")
    st.stop()
st.caption(f"데이터 확정 실행: {success.iloc[0]['RUN_ID']} / {success.iloc[0]['FINISHED_AT']}")
bounds = session.sql("SELECT MIN(order_date),MAX(order_date) FROM MART.DAILY_SALES").collect()[0]
if bounds[0] is None:
    st.info("확정된 매출 대상 주문이 없습니다.")
    st.stop()
period = st.date_input("주문일 범위", value=(bounds[0], bounds[1]))
if len(period) != 2:
    st.info("시작일과 종료일을 선택하세요.")
    st.stop()
start, end = period
if start > end:
    st.error("종료일은 시작일 이후여야 합니다.")
    st.stop()
params = [start.isoformat(), end.isoformat()]
daily = session.sql("SELECT * FROM MART.DAILY_SALES WHERE order_date BETWEEN TO_DATE(?) AND TO_DATE(?) ORDER BY order_date", params=params).to_pandas()
products = session.sql("SELECT product_id,product_name,SUM(quantity) AS quantity,SUM(sales_amount) AS sales_amount FROM MART.PRODUCT_SALES WHERE order_date BETWEEN TO_DATE(?) AND TO_DATE(?) GROUP BY product_id,product_name ORDER BY sales_amount DESC,product_id", params=params).to_pandas()
amount = int(daily["SALES_AMOUNT"].sum())
count = int(daily["ORDER_COUNT"].sum())
a,b,c = st.columns(3)
a.metric("총매출", f"₩{amount:,}")
b.metric("주문 수", f"{count:,}")
c.metric("평균 주문 금액", f"₩{amount/count:,.0f}" if count else "계산 대상 없음")
if not daily.empty:
    st.line_chart(daily.set_index("ORDER_DATE")[["SALES_AMOUNT"]])
st.dataframe(products, hide_index=True)
st.caption("품질 지표는 전체 파일의 최근 실행 기준이며, 주문일 필터와 독립적입니다. 오류 행 수와 제외 주문 수는 다릅니다.")
issues = session.sql("SELECT error_code, COUNT(*) AS event_count FROM AUDIT.DATA_ISSUES WHERE run_id=? GROUP BY error_code ORDER BY event_count DESC", params=[str(latest.iloc[0]["RUN_ID"])]).to_pandas() if not latest.empty else None
if issues is not None:
    st.dataframe(issues, hide_index=True)
