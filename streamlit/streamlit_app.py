"""Streamlit in Snowflake 앱. 앱의 데이터베이스는 AE101_SALES_ENT 로 선택하세요.

매출 화면은 MART.V_* 리포트 뷰(sql/10_report_views.sql)만 읽습니다.
뷰는 DIM_CUSTOMER 와 조인하므로, 행 접근 정책(sql/11_security.sql)을 적용하면 앱 실행 역할에 허용된 지역만 보입니다.
"""
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="AE101 Sales", layout="wide")
session = get_active_session()
st.title("AE Commerce · 매출 및 데이터 품질")
st.caption("한국 시간 주문일 기준 · KRW · 매출 = 완료 주문 중 관련 행이 모두 정상이고 성공 결제 1건, 금액이 일치하는 주문")

latest = session.sql("SELECT * FROM MART.V_LATEST_RUN").to_pandas()
success = session.sql(
    "SELECT * FROM AUDIT.PIPELINE_RUNS WHERE status = 'SUCCESS' "
    "QUALIFY ROW_NUMBER() OVER (ORDER BY finished_at DESC) = 1").to_pandas()
if not latest.empty:
    row = latest.iloc[0]
    st.write("최근 실행 상태:", row["STATUS"])
    if row["STATUS"] != "SUCCESS":
        st.warning("최근 실행이 성공하지 않았습니다. 메시지와 품질 검사 결과를 확인하세요.")
    st.dataframe(latest, hide_index=True)
if success.empty:
    st.info("아직 성공한 실행이 없습니다. 노트북 또는 `python -m src.pipeline --load` 결과를 확인하세요.")
    st.stop()
st.caption(f"마지막 성공 실행: {success.iloc[0]['LOAD_ID']} / {success.iloc[0]['FINISHED_AT']}")

bounds = session.sql("SELECT MIN(order_date), MAX(order_date) FROM MART.V_REVENUE_DAILY").collect()[0]
if bounds[0] is None:
    st.info("매출로 인정된 주문이 없습니다.")
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
daily = session.sql(
    "SELECT * FROM MART.V_REVENUE_DAILY WHERE order_date BETWEEN TO_DATE(?) AND TO_DATE(?) ORDER BY order_date",
    params=params).to_pandas()
revenue = int(daily["REVENUE"].sum())
orders = int(daily["ORDER_COUNT"].sum())
a, b, c = st.columns(3)
a.metric("총매출", f"₩{revenue:,}")
b.metric("주문 수", f"{orders:,}")
c.metric("평균 주문 금액", f"₩{revenue / orders:,.0f}" if orders else "계산 대상 없음")
if not daily.empty:
    st.line_chart(daily.set_index("ORDER_DATE")[["REVENUE"]])

left, right = st.columns(2)
with left:
    st.subheader("상품별 매출 (전체 기간)")
    st.dataframe(session.sql("SELECT product_name, category, quantity, revenue FROM MART.V_REVENUE_BY_PRODUCT "
                             "ORDER BY revenue DESC LIMIT 20").to_pandas(), hide_index=True)
with right:
    st.subheader("지역별 매출 (주문 당시 지역, 전체 기간)")
    st.dataframe(session.sql("SELECT region, order_count, revenue FROM MART.V_REVENUE_BY_REGION_ASWAS "
                             "ORDER BY revenue DESC").to_pandas(), hide_index=True)

st.subheader("데이터 품질 (최근 실행 기준, 주문일 필터와 무관)")
q1, q2 = st.columns(2)
with q1:
    st.caption("매출 판정 결과 (제외된 주문도 MART 에 적재되어 있습니다)")
    st.dataframe(session.sql("SELECT COALESCE(exclusion_reason, '(매출 인식)') AS result, COUNT(*) AS orders "
                             "FROM MART.V_ORDER_QUALITY GROUP BY 1 ORDER BY orders DESC").to_pandas(), hide_index=True)
    st.caption("결제 시도")
    st.dataframe(session.sql("SELECT * FROM MART.V_PAYMENT_SUMMARY ORDER BY payment_status").to_pandas(), hide_index=True)
with q2:
    if not latest.empty:
        load_id = str(latest.iloc[0]["LOAD_ID"])
        st.caption("데이터 이슈 (REMOVED 제거 / QUARANTINED 격리 / FLAGGED 적재 후 표시)")
        st.dataframe(session.sql("SELECT action, error_code, COUNT(*) AS events FROM AUDIT.DATA_ISSUES WHERE load_id = ? "
                                 "GROUP BY action, error_code ORDER BY action, events DESC", params=[load_id]).to_pandas(),
                     hide_index=True)
        st.caption("MART 품질 검사 (모두 0 이어야 정상)")
        st.dataframe(session.sql("SELECT check_name, failures FROM AUDIT.DQ_RESULTS WHERE load_id = ? "
                                 "ORDER BY failures DESC, check_name", params=[load_id]).to_pandas(), hide_index=True)
