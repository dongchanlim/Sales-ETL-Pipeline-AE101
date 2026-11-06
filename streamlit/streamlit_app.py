"""AE101 매출 대시보드 (Streamlit in Snowflake).

데이터 원천은 MART 스키마의 뷰뿐입니다 (sql/10_report_views.sql).
  매출        V_SALES_LINE      매출 인식 + 미삭제 라인, 지역 = 주문 당시 (SCD2)
  주문 품질   V_ORDER_QUALITY   모든 주문의 매출 인식 여부와 제외 사유
  결제        V_PAYMENT_DAILY   결제일·지역·상태별 시도
  운영        V_RUN_HISTORY, V_DQ_RESULTS, V_DATA_ISSUE_SUMMARY
뷰는 DIM_CUSTOMER 와 조인하므로 행 접근 정책(sql/11_security.sql)이 그대로 적용됩니다.
Streamlit in Snowflake 는 앱 소유 역할 권한으로 실행되므로, 보이는 지역 범위는 앱 소유 역할이 정합니다.
배포 설정은 같은 폴더의 snowflake.yml / pyproject.toml 을 참고하세요.
"""
from datetime import date, timedelta
import inspect

import altair as alt
import pandas as pd
import streamlit as st

DATABASE = "AE101_SALES_ENT"
CACHE_TTL_SEC = 600
STALE_AFTER_HOURS = 24
GRAINS = {"일": "day", "주": "week", "월": "month"}
PRESETS = ("최근 30일", "최근 90일", "최근 12개월", "올해 누적", "전체 기간", "직접 선택")
COMPARE_MODES = ("이전 동일 기간", "전년 동기", "비교 안 함")
PRIMARY, MUTED = "#2563EB", "#9CA3AF"

# Streamlit 1.4x 후반부터 use_container_width 대신 width="stretch" 를 씁니다. 런타임 버전에 맞춰 고릅니다.
FULL = ({"width": "stretch"} if inspect.signature(st.dataframe).parameters["width"].default == "stretch"
        else {"use_container_width": True})

st.set_page_config(page_title="AE101 매출 대시보드", layout="wide")
st.markdown("""
<style>
div[data-testid="stMetric"] {background: rgba(37,99,235,0.04); border: 1px solid rgba(148,163,184,0.35);
  border-radius: 10px; padding: 12px 16px;}
div[data-testid="stMetricLabel"] p {font-size: 0.85rem;}
.block-container {padding-top: 2rem;}
</style>""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- 데이터 접근
@st.cache_resource(show_spinner=False)
def get_session():
    """웨어하우스 런타임은 get_active_session(), 컨테이너 런타임은 st.connection 을 씁니다."""
    try:
        from snowflake.snowpark.context import get_active_session
        session = get_active_session()
    except Exception:
        session = st.connection("snowflake").session()
    session.use_database(DATABASE)
    return session


@st.cache_data(ttl=CACHE_TTL_SEC, show_spinner=False)
def _query(sql, params):
    df = get_session().sql(sql, params=list(params) if params else None).to_pandas()
    df.columns = [c.upper() for c in df.columns]
    return df


def q(sql, params=(), required=True):
    """쿼리 실행 (10분 캐시). required=False 면 실패해도 화면을 멈추지 않고 None 을 돌려줍니다."""
    try:
        return _query(sql, tuple(params))
    except Exception as exc:
        if not required:
            return None
        st.error(f"데이터를 불러오지 못했습니다 ({type(exc).__name__}). 앱 역할의 MART 뷰 권한과 "
                 "sql/10_report_views.sql 실행 여부를 확인하세요.")
        with st.expander("오류 상세"):
            st.code(str(exc)[:2000])
        st.stop()


def where(start, end, date_col, regions=(), categories=()):
    """필터 조건과 바인딩 값. 목록이 비어 있으면 전체."""
    clauses, params = [f"{date_col} BETWEEN TO_DATE(?) AND TO_DATE(?)"], [start.isoformat(), end.isoformat()]
    if regions:
        clauses.append(f"region IN ({', '.join('?' * len(regions))})")
        params += list(regions)
    if categories:
        clauses.append(f"category IN ({', '.join('?' * len(categories))})")
        params += list(categories)
    return " AND ".join(clauses), params


# --------------------------------------------------------------------------- 표시 도우미
def num(value, default=0):
    """None·NaN(pandas)을 default로 바꿔 숫자로 돌려준다. NaN은 `or 0`으로 걸러지지 않는다."""
    try:
        return default if value is None or pd.isna(value) else value
    except (TypeError, ValueError):
        return default


def krw(value):
    value = float(num(value))
    if abs(value) >= 1e8:
        return f"₩{value / 1e8:,.2f}억"
    if abs(value) >= 1e4:
        return f"₩{value / 1e4:,.0f}만"
    return f"₩{value:,.0f}"


def pct_change(cur, prev):
    if prev is None or pd.isna(prev) or prev == 0:
        return None
    return (cur - prev) / prev * 100


def delta(cur, prev, unit="%"):
    p = pct_change(cur, prev)
    return None if p is None else f"{p:+.1f}{unit}"


def shift_year(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:            # 2/29 → 2/28
        return d.replace(year=d.year + years, day=28)


def period_range(preset, min_d, max_d, custom=None):
    if preset == "최근 30일":
        start = max_d - timedelta(days=29)
    elif preset == "최근 90일":
        start = max_d - timedelta(days=89)
    elif preset == "최근 12개월":
        start = shift_year(max_d, -1) + timedelta(days=1)
    elif preset == "올해 누적":
        start = date(max_d.year, 1, 1)
    elif preset == "직접 선택" and custom:
        return custom
    else:
        start = min_d
    return max(start, min_d), max_d


def comparison_range(start, end, mode):
    if mode == "이전 동일 기간":
        days = (end - start).days + 1
        c_end = start - timedelta(days=1)
        return c_end - timedelta(days=days - 1), c_end
    if mode == "전년 동기":
        return shift_year(start, -1), shift_year(end, -1)
    return None


def default_grain(start, end):
    days = (end - start).days + 1
    return "일" if days <= 62 else ("주" if days <= 370 else "월")


X_FORMAT = {"day": "%m/%d", "week": "%m/%d", "month": "%Y-%m"}


def partial_note(start, end, grain):
    """선택 기간의 첫·마지막 집계 구간이 일부 날짜만 포함하면 안내 문구를 돌려줍니다."""
    if grain == "day":
        return None
    if grain == "week":
        first_partial, last_partial = start.weekday() != 0, end.weekday() != 6
    else:
        first_partial, last_partial = start.day != 1, (end + timedelta(days=1)).day != 1
    parts = [name for name, flag in (("첫", first_partial), ("마지막", last_partial)) if flag]
    unit = "주" if grain == "week" else "월"
    return f"{'·'.join(parts)} {unit}은 선택 기간에 걸친 일부 날짜만 포함합니다." if parts else None


def compare_line(cur, cmp, value_col, title, scale=1.0, fmt=",.0f", x_format="%m/%d"):
    """선택 기간(실선)과 비교 기간(점선)을 같은 x 위치(기간 순번)에 겹쳐 그립니다."""
    cur = cur.reset_index(drop=True).assign(SERIES="선택 기간", X=lambda d: d["PERIOD"])
    frames = [cur]
    if cmp is not None and not cmp.empty:
        cmp = cmp.reset_index(drop=True).head(len(cur))
        cmp = cmp.assign(SERIES="비교 기간", X=cur["PERIOD"].iloc[:len(cmp)].values)
        frames.append(cmp)
    data = pd.concat(frames, ignore_index=True)
    data["VALUE"] = data[value_col].astype(float) / scale
    data["LABEL"] = pd.to_datetime(data["PERIOD"]).dt.strftime("%Y-%m-%d")
    return (alt.Chart(data).mark_line(point=alt.OverlayMarkDef(size=18), strokeWidth=2)
            .encode(x=alt.X("X:T", title=None, axis=alt.Axis(format=x_format, labelAngle=0)),
                    y=alt.Y("VALUE:Q", title=title, axis=alt.Axis(format=fmt)),
                    color=alt.Color("SERIES:N", title=None,
                                    scale=alt.Scale(domain=["선택 기간", "비교 기간"], range=[PRIMARY, MUTED]),
                                    legend=alt.Legend(orient="top")),
                    strokeDash=alt.StrokeDash("SERIES:N", scale=alt.Scale(domain=["선택 기간", "비교 기간"],
                                                                            range=[[1, 0], [5, 4]]), legend=None),
                    tooltip=[alt.Tooltip("SERIES:N", title="구분"), alt.Tooltip("LABEL:N", title="기간 시작"),
                             alt.Tooltip("VALUE:Q", title=title, format=fmt)])
            .properties(height=300))


def hbar(df, cat_col, value_col, title, scale=1.0, fmt=",.0f", color=PRIMARY):
    data = df.assign(VALUE=df[value_col].astype(float) / scale)
    return (alt.Chart(data).mark_bar(color=color, cornerRadiusEnd=3)
            .encode(y=alt.Y(f"{cat_col}:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False, labelLimit=220)),
                    x=alt.X("VALUE:Q", title=title, axis=alt.Axis(format=fmt)),
                    tooltip=[alt.Tooltip(f"{cat_col}:N", title="항목"), alt.Tooltip("VALUE:Q", title=title, format=fmt)])
            .properties(height=max(160, 30 * len(data))))


def csv_button(df, label, filename):
    st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), file_name=filename, mime="text/csv")


def with_growth(cur, cmp, key, value="REVENUE"):
    """현재·비교 기간 표를 키로 합쳐 비중과 증감률을 붙입니다."""
    out = cur.copy()
    total = out[value].sum()
    out["SHARE"] = out[value] / total * 100 if total else 0.0
    if cmp is not None:
        prev = cmp[[key, value]].rename(columns={value: "PREV"})
        out = out.merge(prev, on=key, how="left")
        out["GROWTH"] = [pct_change(c, p) for c, p in zip(out[value], out["PREV"])]
    else:
        out["PREV"], out["GROWTH"] = None, None
    return out.sort_values(value, ascending=False)


MONEY = st.column_config.NumberColumn(format="₩%,d")
COUNT = st.column_config.NumberColumn(format="%,d")
GROWTH = st.column_config.NumberColumn("증감률", format="%+.1f%%")
SHARE = st.column_config.ProgressColumn("비중", format="%.1f%%", min_value=0, max_value=100)


# --------------------------------------------------------------------------- 헤더 · 데이터 신선도
st.title("AE Commerce 매출 대시보드")

last_ok = q("SELECT load_id, finished_at, DATEDIFF('hour', finished_at, CURRENT_TIMESTAMP()::TIMESTAMP_NTZ) AS hours_ago "
            "FROM MART.V_RUN_HISTORY WHERE status = 'SUCCESS' ORDER BY finished_at DESC LIMIT 1", required=False)
latest = q("SELECT load_id, status, started_at, message FROM MART.V_RUN_HISTORY ORDER BY started_at DESC LIMIT 1",
           required=False)
bounds = q("SELECT MIN(order_date) AS MIN_D, MAX(order_date) AS MAX_D FROM MART.V_SALES_LINE")
if bounds.empty or pd.isna(bounds.iloc[0]["MIN_D"]):
    st.info("매출로 인정된 주문이 없습니다. 노트북 또는 `python -m src.pipeline --load` 실행 결과를 확인하세요.")
    st.stop()
min_d, max_d = pd.to_datetime(bounds.iloc[0]["MIN_D"]).date(), pd.to_datetime(bounds.iloc[0]["MAX_D"]).date()

h1, h2, h3 = st.columns([2, 2, 3])
if last_ok is not None and not last_ok.empty:
    ok = last_ok.iloc[0]
    h1.caption(f"데이터 기준 시각 · {pd.to_datetime(ok['FINISHED_AT']):%Y-%m-%d %H:%M}")
    if ok["HOURS_AGO"] is not None and not pd.isna(ok["HOURS_AGO"]) and ok["HOURS_AGO"] > STALE_AFTER_HOURS:
        st.warning(f"마지막 성공 적재 후 {int(ok['HOURS_AGO'])}시간이 지났습니다. 파이프라인 일정을 확인하세요.")
else:
    h1.caption("데이터 기준 시각 · 실행 이력을 볼 수 없습니다")
if latest is not None and not latest.empty:
    lr = latest.iloc[0]
    h2.caption(f"최근 실행 · {lr['STATUS']} ({pd.to_datetime(lr['STARTED_AT']):%m-%d %H:%M})")
    if lr["STATUS"] == "FAILED":
        st.error(f"최근 실행이 실패했습니다: {lr['MESSAGE'] or '메시지 없음'} · 화면의 수치는 이전에 반영된 데이터일 수 있습니다.")
    elif lr["STATUS"] == "RUNNING":
        st.info("파이프라인이 실행 중입니다. 완료 후 수치가 바뀔 수 있습니다.")
h3.caption(f"주문 데이터 범위 · {min_d} ~ {max_d} · KST 주문일 기준 · KRW")


# --------------------------------------------------------------------------- 사이드바 필터
regions_all = q("SELECT DISTINCT region FROM MART.V_SALES_LINE ORDER BY 1")["REGION"].tolist()
categories_all = q("SELECT DISTINCT category FROM MART.V_SALES_LINE ORDER BY 1")["CATEGORY"].tolist()

with st.sidebar:
    st.header("필터")
    preset = st.selectbox("기간", PRESETS, index=1)
    custom = None
    if preset == "직접 선택":
        picked = st.date_input("기간 직접 선택", value=(max_d - timedelta(days=29), max_d),
                               min_value=min_d, max_value=max_d)
        if not isinstance(picked, (tuple, list)) or len(picked) != 2:
            st.info("시작일과 종료일을 모두 선택하세요.")
            st.stop()
        custom = tuple(picked)
    start, end = period_range(preset, min_d, max_d, custom)
    compare_mode = st.radio("비교 기준", COMPARE_MODES, index=0)
    grain_label = st.radio("집계 단위", list(GRAINS), index=list(GRAINS).index(default_grain(start, end)),
                           horizontal=True)
    regions = st.multiselect("지역 (주문 당시)", regions_all, placeholder="전체 지역")
    categories = st.multiselect("카테고리", categories_all, placeholder="전체 카테고리")
    st.divider()
    st.caption(f"선택 기간 · {start} ~ {end} ({(end - start).days + 1}일)")
    cmp_range = comparison_range(start, end, compare_mode)
    if cmp_range:
        st.caption(f"비교 기간 · {cmp_range[0]} ~ {cmp_range[1]}")
    st.caption(f"기간 프리셋은 마지막 주문일({max_d}) 기준입니다. 데이터는 {CACHE_TTL_SEC // 60}분마다 새로 읽습니다.")
    if st.button("캐시 비우고 새로 고침"):
        st.cache_data.clear()
        st.rerun()

grain = GRAINS[grain_label]
cur_where, cur_params = where(start, end, "order_date", regions, categories)
cmp_where, cmp_params = where(*cmp_range, "order_date", regions, categories) if cmp_range else (None, None)


def sales(select, group=None, order=None, comparison=False, limit=None):
    """V_SALES_LINE 집계. comparison=True 면 비교 기간 (비교 안 함이면 None)."""
    if comparison and not cmp_range:
        return None
    w, p = (cmp_where, cmp_params) if comparison else (cur_where, cur_params)
    sql = f"SELECT {select} FROM MART.V_SALES_LINE WHERE {w}"
    sql += f" GROUP BY {group}" if group else ""
    sql += f" ORDER BY {order}" if order else ""
    sql += f" LIMIT {int(limit)}" if limit else ""
    return q(sql, p)


KPI_SQL = ("COALESCE(SUM(revenue), 0) AS REVENUE, COUNT(DISTINCT order_id) AS ORDERS, "
           "COALESCE(SUM(quantity), 0) AS UNITS, COUNT(DISTINCT customer_id) AS CUSTOMERS")
kpi = sales(KPI_SQL).iloc[0].astype(float)
kpi_prev = sales(KPI_SQL, comparison=True)
kpi_prev = kpi_prev.iloc[0].astype(float) if kpi_prev is not None else None
if kpi["ORDERS"] == 0:
    st.info("선택한 조건에 해당하는 매출이 없습니다. 기간이나 필터를 바꿔 보세요.")
    st.stop()
aov = kpi["REVENUE"] / kpi["ORDERS"]
aov_prev = (kpi_prev["REVENUE"] / kpi_prev["ORDERS"]) if kpi_prev is not None and kpi_prev["ORDERS"] else None
if cmp_range and (kpi_prev is None or kpi_prev["ORDERS"] == 0):
    st.caption("비교 기간에 데이터가 없어 증감률을 표시하지 않습니다.")
if categories:
    st.caption("카테고리 필터 적용 중: 주문 수는 해당 카테고리 상품이 포함된 주문, 평균 주문 금액은 해당 카테고리 매출 기준입니다.")

tab_overview, tab_product, tab_region, tab_quality, tab_ops = st.tabs(
    ["개요", "상품 · 카테고리", "지역", "주문 · 결제 품질", "데이터 운영"])

# --------------------------------------------------------------------------- 1. 개요
with tab_overview:
    p = kpi_prev
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("매출", krw(kpi["REVENUE"]), delta(kpi["REVENUE"], p["REVENUE"] if p is not None else None),
              help=f"₩{kpi['REVENUE']:,.0f}" + (f" · 비교 기간 ₩{p['REVENUE']:,.0f}" if p is not None else ""))
    c2.metric("주문 수", f"{kpi['ORDERS']:,.0f}", delta(kpi["ORDERS"], p["ORDERS"] if p is not None else None))
    c3.metric("평균 주문 금액", f"₩{aov:,.0f}", delta(aov, aov_prev))
    c4.metric("판매 수량", f"{kpi['UNITS']:,.0f}", delta(kpi["UNITS"], p["UNITS"] if p is not None else None))
    c5.metric("구매 고객 수", f"{kpi['CUSTOMERS']:,.0f}", delta(kpi["CUSTOMERS"], p["CUSTOMERS"] if p is not None else None))

    trend_sql = (f"DATE_TRUNC('{grain}', order_date) AS PERIOD, SUM(revenue) AS REVENUE, "
                 "COUNT(DISTINCT order_id) AS ORDERS")
    trend = sales(trend_sql, group="1", order="1")
    trend_prev = sales(trend_sql, group="1", order="1", comparison=True)
    st.subheader(f"매출 추이 ({grain_label} 단위)")
    st.altair_chart(compare_line(trend, trend_prev, "REVENUE", "매출 (백만원)", scale=1e6, fmt=",.1f",
                                 x_format=X_FORMAT[grain]), **FULL)
    note = partial_note(start, end, grain)
    if note:
        st.caption(note)

    cat = with_growth(sales("category AS CATEGORY, SUM(revenue) AS REVENUE", group="1"),
                      sales("category AS CATEGORY, SUM(revenue) AS REVENUE", group="1", comparison=True), "CATEGORY")
    reg = with_growth(sales("region AS REGION, SUM(revenue) AS REVENUE", group="1"),
                      sales("region AS REGION, SUM(revenue) AS REVENUE", group="1", comparison=True), "REGION")
    left, right = st.columns(2)
    with left:
        st.subheader("카테고리별 매출")
        st.altair_chart(hbar(cat, "CATEGORY", "REVENUE", "매출 (백만원)", scale=1e6, fmt=",.1f"), **FULL)
    with right:
        st.subheader("지역별 매출 상위 10")
        st.altair_chart(hbar(reg.head(10), "REGION", "REVENUE", "매출 (백만원)", scale=1e6, fmt=",.1f"),
                        **FULL)

    top_cat, top_reg = cat.iloc[0], reg.iloc[0]
    growth_txt = delta(kpi["REVENUE"], p["REVENUE"] if p is not None else None)
    st.info(f"선택 기간 매출은 **{krw(kpi['REVENUE'])}**"
            + (f"로 비교 기간 대비 **{growth_txt}** 입니다. " if growth_txt else "입니다. ")
            + f"매출 비중이 가장 큰 카테고리는 **{top_cat['CATEGORY']}**({top_cat['SHARE']:.1f}%), "
            + f"지역은 **{top_reg['REGION']}**({top_reg['SHARE']:.1f}%) 입니다.")

# --------------------------------------------------------------------------- 2. 상품 · 카테고리
with tab_product:
    cat_sql = ("category AS CATEGORY, SUM(revenue) AS REVENUE, COUNT(DISTINCT order_id) AS ORDERS, "
               "SUM(quantity) AS UNITS")
    cat_tbl = with_growth(sales(cat_sql, group="1"), sales(cat_sql, group="1", comparison=True), "CATEGORY")
    st.subheader("카테고리 성과")
    st.dataframe(cat_tbl[["CATEGORY", "REVENUE", "SHARE", "PREV", "GROWTH", "ORDERS", "UNITS"]], hide_index=True,
                 **FULL,
                 column_config={"CATEGORY": "카테고리", "REVENUE": st.column_config.NumberColumn("매출", format="₩%,d"),
                                "SHARE": SHARE, "PREV": st.column_config.NumberColumn("비교 기간 매출", format="₩%,d"),
                                "GROWTH": GROWTH, "ORDERS": st.column_config.NumberColumn("주문 수", format="%,d"),
                                "UNITS": st.column_config.NumberColumn("판매 수량", format="%,d")})

    st.subheader("카테고리 × 월 매출")
    heat = sales("category AS CATEGORY, year_month AS MONTH, SUM(revenue) AS REVENUE", group="1, 2")
    heat["REVENUE_M"] = heat["REVENUE"].astype(float) / 1e6
    st.altair_chart(alt.Chart(heat).mark_rect().encode(
        x=alt.X("MONTH:O", title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("CATEGORY:N", title=None, axis=alt.Axis(labelOverlap=False)),
        color=alt.Color("REVENUE_M:Q", title="매출 (백만원)", scale=alt.Scale(scheme="blues")),
        tooltip=[alt.Tooltip("CATEGORY:N", title="카테고리"), alt.Tooltip("MONTH:O", title="월"),
                 alt.Tooltip("REVENUE_M:Q", title="매출 (백만원)", format=",.1f")]
    ).properties(height=40 * max(1, heat["CATEGORY"].nunique())), **FULL)

    st.subheader("상품 순위")
    top_n = st.radio("표시 개수", (10, 20, 50), horizontal=True, key="top_n")
    prod_sql = ("product_id AS PRODUCT_ID, product_name AS PRODUCT_NAME, category AS CATEGORY, SUM(revenue) AS REVENUE, "
                "SUM(quantity) AS UNITS, COUNT(DISTINCT order_id) AS ORDERS")
    prod = sales(prod_sql, group="1, 2, 3", order="REVENUE DESC", limit=top_n)
    prod_prev = sales("product_id AS PRODUCT_ID, SUM(revenue) AS REVENUE", group="1", comparison=True)
    prod_tbl = with_growth(prod, prod_prev, "PRODUCT_ID")
    prod_tbl["SHARE"] = prod_tbl["REVENUE"] / kpi["REVENUE"] * 100
    prod_tbl.insert(0, "RANK", range(1, len(prod_tbl) + 1))
    st.dataframe(prod_tbl[["RANK", "PRODUCT_NAME", "CATEGORY", "REVENUE", "SHARE", "GROWTH", "UNITS", "ORDERS"]],
                 hide_index=True, **FULL,
                 column_config={"RANK": "순위", "PRODUCT_NAME": "상품", "CATEGORY": "카테고리",
                                "REVENUE": st.column_config.NumberColumn("매출", format="₩%,d"),
                                "SHARE": st.column_config.ProgressColumn("매출 비중", format="%.1f%%", min_value=0,
                                                                         max_value=max(1.0, float(prod_tbl["SHARE"].max()))),
                                "GROWTH": GROWTH, "UNITS": st.column_config.NumberColumn("판매 수량", format="%,d"),
                                "ORDERS": st.column_config.NumberColumn("주문 수", format="%,d")})
    csv_button(prod_tbl, "상품 순위 CSV 내려받기", f"product_ranking_{start}_{end}.csv")

# --------------------------------------------------------------------------- 3. 지역
with tab_region:
    st.caption("지역은 주문 당시 고객 지역입니다 (SCD2 As-Was). 고객이 이사해도 과거 매출의 지역은 바뀌지 않습니다.")
    reg_sql = ("region AS REGION, SUM(revenue) AS REVENUE, COUNT(DISTINCT order_id) AS ORDERS, "
               "COUNT(DISTINCT customer_id) AS CUSTOMERS")
    reg_tbl = with_growth(sales(reg_sql, group="1"), sales(reg_sql, group="1", comparison=True), "REGION")
    reg_tbl["AOV"] = reg_tbl["REVENUE"] / reg_tbl["ORDERS"]
    left, right = st.columns([3, 2])
    with left:
        st.dataframe(reg_tbl[["REGION", "REVENUE", "SHARE", "GROWTH", "ORDERS", "CUSTOMERS", "AOV"]], hide_index=True,
                     height=35 * (len(reg_tbl) + 1) + 3, **FULL,
                     column_config={"REGION": "지역", "REVENUE": st.column_config.NumberColumn("매출", format="₩%,d"),
                                    "SHARE": SHARE, "GROWTH": GROWTH,
                                    "ORDERS": st.column_config.NumberColumn("주문 수", format="%,d"),
                                    "CUSTOMERS": st.column_config.NumberColumn("구매 고객", format="%,d"),
                                    "AOV": st.column_config.NumberColumn("평균 주문 금액", format="₩%,d")})
        csv_button(reg_tbl, "지역 성과 CSV 내려받기", f"region_{start}_{end}.csv")
    with right:
        st.altair_chart(hbar(reg_tbl, "REGION", "REVENUE", "매출 (백만원)", scale=1e6, fmt=",.1f"),
                        **FULL)

    top5 = reg_tbl["REGION"].head(5).tolist()
    st.subheader(f"상위 5개 지역 매출 추이 ({grain_label} 단위)")
    reg_trend = sales(f"DATE_TRUNC('{grain}', order_date) AS PERIOD, region AS REGION, SUM(revenue) AS REVENUE",
                      group="1, 2", order="1")
    reg_trend = reg_trend[reg_trend["REGION"].isin(top5)].assign(REVENUE_M=lambda d: d["REVENUE"].astype(float) / 1e6)
    st.altair_chart(alt.Chart(reg_trend).mark_line(point=alt.OverlayMarkDef(size=14)).encode(
        x=alt.X("PERIOD:T", title=None, axis=alt.Axis(format=X_FORMAT[grain], labelAngle=0)), y=alt.Y("REVENUE_M:Q", title="매출 (백만원)", axis=alt.Axis(format=",.1f")),
        color=alt.Color("REGION:N", title=None, sort=top5, legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("REGION:N", title="지역"), alt.Tooltip("PERIOD:T", title="기간 시작"),
                 alt.Tooltip("REVENUE_M:Q", title="매출 (백만원)", format=",.1f")]
    ).properties(height=300), **FULL)

# --------------------------------------------------------------------------- 4. 주문 · 결제 품질
with tab_quality:
    if categories:
        st.caption("주문·결제 품질은 주문 단위라 카테고리 필터를 적용하지 않습니다 (기간·지역만 적용).")
    oq_where, oq_params = where(start, end, "order_date", regions)
    oq = q("SELECT order_status AS STATUS, is_revenue_eligible AS ELIGIBLE, "
           "COALESCE(exclusion_reason, '(매출 인식)') AS RESULT, COUNT(*) AS ORDERS, SUM(order_amount) AS AMOUNT "
           f"FROM MART.V_ORDER_QUALITY WHERE {oq_where} GROUP BY 1, 2, 3", oq_params)
    total = int(oq["ORDERS"].sum())
    eligible = int(oq.loc[oq["ELIGIBLE"] == True, "ORDERS"].sum())  # noqa: E712
    completed = oq[oq["STATUS"] == "완료"]
    blocked = completed[completed["ELIGIBLE"] == False]  # noqa: E712
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("전체 주문", f"{total:,}")
    m2.metric("매출 인식 주문", f"{eligible:,}")
    m3.metric("매출 인식률", f"{eligible / total * 100:.1f}%" if total else "-",
              help="매출 인식 주문 / 전체 주문 (대기·취소 포함)")
    m4.metric("검증 실패 완료 주문 금액", krw(blocked["AMOUNT"].sum()),
              help="완료 상태지만 데이터 검증(결제·금액·참조)에 실패해 매출에서 빠진 주문의 주문 금액 합계")

    left, right = st.columns(2)
    with left:
        st.subheader("판정 결과")
        res = oq.groupby("RESULT", as_index=False)[["ORDERS", "AMOUNT"]].sum().sort_values("ORDERS", ascending=False)
        res["SHARE"] = res["ORDERS"] / total * 100 if total else 0.0
        st.dataframe(res, hide_index=True, **FULL,
                     column_config={"RESULT": "결과", "ORDERS": st.column_config.NumberColumn("주문 수", format="%,d"),
                                    "AMOUNT": st.column_config.NumberColumn("주문 금액", format="₩%,d"),
                                    "SHARE": st.column_config.ProgressColumn("비중", format="%.1f%%",
                                                                             min_value=0, max_value=100)})
    with right:
        st.subheader("매출 제외 사유")
        excl = res[res["RESULT"] != "(매출 인식)"]
        if excl.empty:
            st.caption("제외된 주문이 없습니다.")
        else:
            st.altair_chart(hbar(excl, "RESULT", "ORDERS", "주문 수", color="#F59E0B"), **FULL)

    rate = q(f"SELECT DATE_TRUNC('{grain}', order_date) AS PERIOD, COUNT(*) AS TOTAL, "
             "SUM(CASE WHEN is_revenue_eligible THEN 1 ELSE 0 END) AS ELIGIBLE "
             f"FROM MART.V_ORDER_QUALITY WHERE {oq_where} GROUP BY 1 ORDER BY 1", oq_params)
    rate["RATE"] = rate["ELIGIBLE"] / rate["TOTAL"] * 100

    pay_where, pay_params = where(start, end, "paid_date", regions)
    pay = q("SELECT payment_status AS STATUS, SUM(attempts) AS ATTEMPTS, SUM(amount) AS AMOUNT, "
            f"SUM(orphan_payments) AS ORPHANS FROM MART.V_PAYMENT_DAILY WHERE {pay_where} GROUP BY 1", pay_params)
    pay_rate = q(f"SELECT DATE_TRUNC('{grain}', paid_date) AS PERIOD, SUM(attempts) AS TOTAL, "
                 "SUM(CASE WHEN payment_status = '성공' THEN attempts ELSE 0 END) AS OK "
                 f"FROM MART.V_PAYMENT_DAILY WHERE {pay_where} GROUP BY 1 ORDER BY 1", pay_params)
    pay_rate["RATE"] = pay_rate["OK"] / pay_rate["TOTAL"] * 100
    rates = pd.concat([rate.assign(SERIES="매출 인식률")[["PERIOD", "RATE", "SERIES"]],
                       pay_rate.assign(SERIES="결제 성공률")[["PERIOD", "RATE", "SERIES"]]])
    st.subheader(f"매출 인식률 · 결제 성공률 추이 ({grain_label} 단위)")
    st.altair_chart(alt.Chart(rates).mark_line(point=alt.OverlayMarkDef(size=14)).encode(
        x=alt.X("PERIOD:T", title=None, axis=alt.Axis(format=X_FORMAT[grain], labelAngle=0)), y=alt.Y("RATE:Q", title="%", scale=alt.Scale(zero=False)),
        color=alt.Color("SERIES:N", title=None,
                        scale=alt.Scale(domain=["매출 인식률", "결제 성공률"], range=[PRIMARY, "#10B981"]),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("SERIES:N", title="지표"), alt.Tooltip("PERIOD:T", title="기간 시작"),
                 alt.Tooltip("RATE:Q", title="%", format=".1f")]
    ).properties(height=260), **FULL)
    st.caption("최근 구간은 아직 대기 중인 주문·결제가 많아 비율이 낮게 보일 수 있습니다. "
               + (partial_note(start, end, grain) or ""))

    st.subheader("결제 시도")
    attempts = int(pay["ATTEMPTS"].sum())
    ok_attempts = int(pay.loc[pay["STATUS"] == "성공", "ATTEMPTS"].sum())
    p1, p2, p3 = st.columns(3)
    p1.metric("결제 시도", f"{attempts:,}")
    p2.metric("결제 성공률", f"{ok_attempts / attempts * 100:.1f}%" if attempts else "-")
    p3.metric("주문 없는 결제", f"{int(pay['ORPHANS'].sum()):,}", help="결제는 있으나 원천 주문을 찾을 수 없는 시도 (FLAGGED)")
    st.dataframe(pay.sort_values("ATTEMPTS", ascending=False), hide_index=True, **FULL,
                 column_config={"STATUS": "결제 상태", "ATTEMPTS": st.column_config.NumberColumn("시도 수", format="%,d"),
                                "AMOUNT": st.column_config.NumberColumn("금액", format="₩%,d"),
                                "ORPHANS": st.column_config.NumberColumn("주문 없는 결제", format="%,d")})

# --------------------------------------------------------------------------- 5. 데이터 운영
with tab_ops:
    runs = q("SELECT load_id, status, started_at, finished_at, duration_sec, input_rows, duplicate_rows, "
             "quarantined_rows, flagged_issues, revenue_orders, revenue_amount, failed_checks, total_checks, message "
             "FROM MART.V_RUN_HISTORY ORDER BY started_at DESC LIMIT 30", required=False)
    if runs is None or runs.empty:
        st.info("실행 이력을 볼 수 없습니다. MART.V_RUN_HISTORY 권한 또는 실행 기록을 확인하세요.")
    else:
        r0 = runs.iloc[0]
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("최근 실행 상태", r0["STATUS"])
        o2.metric("품질 검사 실패", (f"{int(r0['FAILED_CHECKS'])} / {int(r0['TOTAL_CHECKS'])}"
                                if pd.notna(r0["FAILED_CHECKS"]) and pd.notna(r0["TOTAL_CHECKS"]) else "-"))
        o3.metric("격리 행 (QUARANTINED)", f"{int(num(r0['QUARANTINED_ROWS'])):,}")
        o4.metric("실행 시간", f"{int(r0['DURATION_SEC'])}초" if pd.notna(r0["DURATION_SEC"]) else "-")

        st.subheader("실행 이력 (최근 30회)")
        st.dataframe(runs, hide_index=True, **FULL,
                     column_config={"LOAD_ID": "load_id", "STATUS": "상태", "STARTED_AT": "시작", "FINISHED_AT": "종료",
                                    "DURATION_SEC": st.column_config.NumberColumn("소요(초)", format="%,d"),
                                    "INPUT_ROWS": st.column_config.NumberColumn("입력 행", format="%,d"),
                                    "DUPLICATE_ROWS": st.column_config.NumberColumn("중복 제거", format="%,d"),
                                    "QUARANTINED_ROWS": st.column_config.NumberColumn("격리", format="%,d"),
                                    "FLAGGED_ISSUES": st.column_config.NumberColumn("표시", format="%,d"),
                                    "REVENUE_ORDERS": st.column_config.NumberColumn("매출 주문", format="%,d"),
                                    "REVENUE_AMOUNT": st.column_config.NumberColumn("매출", format="₩%,d"),
                                    "FAILED_CHECKS": "검사 실패", "TOTAL_CHECKS": "검사 수", "MESSAGE": "메시지"})

        load_id = st.selectbox("상세를 볼 실행", runs["LOAD_ID"].tolist(),
                               format_func=lambda x: f"{x} · {runs.loc[runs['LOAD_ID'] == x, 'STATUS'].iloc[0]}")
        left, right = st.columns(2)
        with left:
            st.subheader("MART 품질 검사")
            dq = q("SELECT check_name AS CHECK_NAME, failures AS FAILURES FROM MART.V_DQ_RESULTS WHERE load_id = ? "
                   "ORDER BY failures DESC, check_name", [load_id], required=False)
            if dq is None or dq.empty:
                st.caption("이 실행의 품질 검사 결과가 없습니다 (MART 반영 전 중단).")
            else:
                dq["RESULT"] = dq["FAILURES"].map(lambda n: "통과" if n == 0 else "실패")
                st.dataframe(dq, hide_index=True, **FULL,
                             column_config={"CHECK_NAME": "검사", "FAILURES": "실패 건수", "RESULT": "결과"})
        with right:
            st.subheader("데이터 이슈")
            issues = q("SELECT action AS ACTION, error_code AS ERROR_CODE, source_file AS SOURCE_FILE, events AS EVENTS "
                       "FROM MART.V_DATA_ISSUE_SUMMARY WHERE load_id = ? ORDER BY events DESC", [load_id], required=False)
            if issues is None or issues.empty:
                st.caption("기록된 이슈가 없습니다.")
            else:
                by_code = issues.groupby(["ACTION", "ERROR_CODE"], as_index=False)["EVENTS"].sum()
                st.altair_chart(alt.Chart(by_code).mark_bar().encode(
                    y=alt.Y("ERROR_CODE:N", sort="-x", title=None), x=alt.X("EVENTS:Q", title="건수"),
                    color=alt.Color("ACTION:N", title=None, legend=alt.Legend(orient="top"),
                                    scale=alt.Scale(domain=["REMOVED", "QUARANTINED", "FLAGGED"],
                                                    range=[MUTED, "#EF4444", "#F59E0B"])),
                    tooltip=["ACTION", "ERROR_CODE", alt.Tooltip("EVENTS:Q", format=",")]
                ).properties(height=260), **FULL)
                csv_button(issues, "이슈 요약 CSV 내려받기", f"data_issues_{load_id}.csv")

# --------------------------------------------------------------------------- 지표 정의
with st.expander("지표 정의"):
    st.markdown("""
| 지표 | 정의 |
|---|---|
| 매출 | 매출 인식 주문의 라인 금액 합계 (`is_revenue_eligible AND NOT is_deleted`) |
| 매출 인식 주문 | 완료 + 관련 행 모두 정상 + 성공 결제 정확히 1건 + 주문 금액 = 상세 합계 = 결제 금액 |
| 주문 수 / 평균 주문 금액 | 매출 인식 주문 수 / 매출 ÷ 주문 수 |
| 구매 고객 수 | 기간 내 매출 인식 주문이 있는 고객 수 |
| 지역 | 주문 당시 고객 지역 (SCD2). 지역이 없는 고객은 Unknown |
| 비교 기간 | 이전 동일 기간 = 선택 기간 바로 앞의 같은 일수, 전년 동기 = 1년 전 같은 날짜 |
| 매출 인식률 | 매출 인식 주문 / 전체 주문 (대기·취소 포함) |
| 결제 성공률 | 성공 결제 시도 / 전체 결제 시도 |
""")
    st.caption("상세 규칙: docs/data_rules.md · 데이터 모델: docs/erd.md")
