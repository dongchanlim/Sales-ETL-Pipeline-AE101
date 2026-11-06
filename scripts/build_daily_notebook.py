"""매일 배치 노트북(notebooks/ae101_daily_batch.ipynb)을 워크스루 노트북에서 만들어 냅니다.

파이프라인 셀(STEP 2 ~ STEP 7)은 워크스루 노트북의 셀을 글자 그대로 복사합니다.
매일 실행에 필요 없는 STEP 0(점검)·1(DDL)·8(리포트 뷰)·9(보안)·10(확인)·11(SCD2 체험)·12(정리)는 넣지 않습니다.
워크스루의 파이프라인 셀을 고친 뒤에는 이 스크립트를 다시 실행하세요. tests/test_notebook_sync.py 가 두 노트북이 같은지 검사합니다.

    python scripts/build_daily_notebook.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "notebooks" / "ae101_enterprise_walkthrough.ipynb"
TARGET = ROOT / "notebooks" / "ae101_daily_batch.ipynb"

# 워크스루에서 그대로 가져오는 셀 (이 순서대로 실행)
PIPELINE_CELLS = (
    "step2", "step3", "step4", "step5", "step6",
    "step7_0_ctx", "step7_0_guard",
    "step7_1a_dim_customer", "step7_1b_dim_product",
    "step7_2a_fact_sales_line", "step7_2b_fact_payment", "step7_2c_fact_order_lifecycle",
    "step7_3_dq", "step7_3_dq_view", "step7_4_finalize",
)

INTRO = """# AE101 매일 배치 노트북 (스케줄 실행용)

이 노트북은 **사람이 아니라 태스크가 매일 실행**합니다. 설치는 `orchestration/daily_schedule.sql` 을 보세요.
워크스루 노트북(`ae101_enterprise_walkthrough.ipynb`)의 STEP 2 ~ STEP 7 셀을 글자 그대로 가져왔습니다. 로직을 바꿀 때는 워크스루를 고치고 `python scripts/build_daily_notebook.py` 로 다시 만드세요.

| 넣은 단계 | 넣지 않은 단계 (한 번만 또는 수동) |
|---|---|
| Git FETCH → STEP 2 실행 시작 → STEP 3 RAW 새 배치 → STEP 4~5 CORE → STEP 6 감사 기록 → STEP 7 MART 반영·품질 검사·상태 확정 | STEP 1 DDL, STEP 8 리포트 뷰, STEP 9 보안, STEP 10 확인 쿼리, STEP 11 SCD2 체험, STEP 12 정리 |

**사전 조건** : 워크스루 STEP 1(DDL)과 STEP 8(리포트 뷰)을 한 번 실행했어야 합니다.

**실패 처리** : 정상 주문이 0건이면 `daily_guard` 가, 품질 검사가 실패하면 `daily_gate` 가 오류를 내 실행을 실패로 끝냅니다. 중간 셀에서 오류가 나 `RUNNING` 으로 남은 실행은 파이널라이저 태스크가 `FAILED` 로 바꿉니다.

**주의** : 스케줄이 켜져 있는 동안 워크스루 노트북을 직접 실행하면 두 실행이 같은 `CORE.RUN_CTX` 를 덮어씁니다. 실습 전에 `ALTER TASK AE101_SALES_ENT.OPS.T_DAILY_BATCH SUSPEND;` 로 멈추세요."""

PREPARE_MD = "## 0. 준비 : DB 지정, Git 저장소 최신화"
PREPARE_SQL = """-- 태스크는 노트북 소유 역할로 실행됩니다. USE ROLE 로 역할을 바꾸지 않습니다.
USE DATABASE AE101_SALES_ENT;
ALTER GIT REPOSITORY AE101_DB.GIT_REPOS.SALES_ETL_PIPELINE FETCH;"""

GUARD_MD = "### 7-0. 가드 (매일 배치 전용) : 정상 주문이 0건이면 MART 를 건드리지 않고 실패로 끝냅니다."
GUARD_PY = '''from snowflake.snowpark.context import get_active_session

session = get_active_session()
load_id = session.sql("SELECT load_id FROM AE101_SALES_ENT.CORE.RUN_CTX").collect()[0][0]
accepted = session.sql("SELECT COUNT(*) FROM AE101_SALES_ENT.CORE.ORDERS").collect()[0][0]

if accepted == 0:
    session.sql(
        """UPDATE AE101_SALES_ENT.AUDIT.PIPELINE_RUNS
              SET status = 'FAILED', finished_at = CURRENT_TIMESTAMP()::TIMESTAMP_NTZ,
                  message = 'Guard: no accepted orders. MART not updated.'
            WHERE load_id = ?""",
        params=[load_id],
    ).collect()
    raise RuntimeError(f"[{load_id}] 정상 주문 0건: MART 반영을 중단합니다.")

print(f"[{load_id}] guard OK - 정상 주문 {accepted:,}건")'''

GATE_MD = "### 7-5. 게이트 (매일 배치 전용) : 상태가 SUCCESS 가 아니면 오류를 내 태스크를 실패로 표시합니다."
GATE_PY = '''from snowflake.snowpark.context import get_active_session

session = get_active_session()
load_id = session.sql("SELECT load_id FROM AE101_SALES_ENT.CORE.RUN_CTX").collect()[0][0]
row = session.sql(
    "SELECT status, message, revenue_orders, revenue_amount FROM AE101_SALES_ENT.AUDIT.PIPELINE_RUNS WHERE load_id = ?",
    params=[load_id],
).collect()[0]

if row["STATUS"] != "SUCCESS":
    raise RuntimeError(f"[{load_id}] 배치 상태 {row['STATUS']}: {row['MESSAGE']}")

print(f"[{load_id}] SUCCESS - 매출 인식 주문 {row['REVENUE_ORDERS']:,}건, 매출 {row['REVENUE_AMOUNT']:,}원")'''

HEADINGS = {
    "step2": "## STEP 2. 실행 시작 : load_id / run_ts 발급, RUNNING 기록",
    "step3": "## STEP 3. RAW 적재 : Git 저장소 CSV 를 새 배치로 추가",
    "step4": "## STEP 4. CORE 정제",
    "step5": "## STEP 5. CORE 주문 품질 판정",
    "step6": "## STEP 6. 감사 기록",
    "step7_0_ctx": "## STEP 7. MART 반영\n\n### 7-0. 실행 컨텍스트 복원",
    "step7_1a_dim_customer": "### 7-1a. SCD2 : DIM_CUSTOMER",
    "step7_1b_dim_product": "### 7-1b. SCD2 : DIM_PRODUCT",
    "step7_2a_fact_sales_line": "### 7-2a. FACT_SALES_LINE (MERGE)",
    "step7_2b_fact_payment": "### 7-2b. FACT_PAYMENT (MERGE)",
    "step7_2c_fact_order_lifecycle": "### 7-2c. FACT_ORDER_LIFECYCLE (MERGE)",
    "step7_3_dq": "### 7-3. 품질 검사 (17개)",
    "step7_4_finalize": "### 7-4. 상태 확정 (SUCCESS / FAILED)",
}


def lines(text):
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


def markdown(text):
    return {"cell_type": "markdown", "metadata": {"name": None}, "source": lines(text)}


def code(name, language, text):
    return {"cell_type": "code", "metadata": {"language": language, "name": name},
            "execution_count": None, "outputs": [], "source": lines(text)}


def build():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    cells = {c["metadata"]["name"]: c for c in source["cells"] if c["cell_type"] == "code"}
    out = [markdown(INTRO), markdown(PREPARE_MD), code("daily_prepare", "sql", PREPARE_SQL)]
    for name in PIPELINE_CELLS:
        if name in HEADINGS:
            out.append(markdown(HEADINGS[name]))
        out.append(json.loads(json.dumps(cells[name])))          # 원본 셀 그대로 복사
        if name == "step7_0_guard":
            out += [markdown(GUARD_MD), code("daily_guard", "python", GUARD_PY)]
    out += [markdown(GATE_MD), code("daily_gate", "python", GATE_PY)]
    return {"cells": out, "metadata": source["metadata"], "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    TARGET.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
