"""Snowflake 적재 : 노트북과 같은 sql/ 파일을 같은 순서로 실행합니다.

  01_start_run.sql            load_id / run_ts 발급 (CORE.RUN_CTX), PIPELINE_RUNS = RUNNING
  (Python)                    로컬 CSV → RAW 새 배치   ※ 노트북은 02_load_raw_from_git.sql 로 스테이지 @RAW.LANDING 에서 적재
  03 → 04                     CORE 정제·판정
  (Python)                    Snowflake RUN_SUMMARY 와 로컬 계산(src/core.py) 대사. 다르면 FAILED 로 중단
  05 → 06 → 07 → 08 → 09      감사 기록 → SCD2 차원 → Fact MERGE → 품질 검사 → 상태 확정
  10_report_views.sql         리포트 뷰

노트북과 마찬가지로 MART 단계는 하나의 트랜잭션이 아닙니다. 09 가 FAILED 를 기록하면 예외를 올립니다.
각 파일은 같은 load_id 로 다시 실행해도 결과가 같도록 작성되어 있습니다.
"""
from .config import SQL_DIR, DATABASE
from .extract import COLUMNS

CORE_FILES = ("03_core_clean.sql", "04_core_order_quality.sql")
MART_FILES = ("05_audit_issues.sql", "06_mart_dimensions.sql", "07_mart_facts.sql",
              "08_mart_dq_checks.sql", "09_finalize_run.sql")
VIEW_FILES = ("10_report_views.sql",)
SUMMARY_COLUMNS = ("input_rows", "duplicate_rows", "quarantined_rows", "flagged_issues",
                   "revenue_orders", "revenue_amount")
BATCH = 5000


def sql_text(filename, database=None):
    text = (SQL_DIR / filename).read_text(encoding="utf-8")
    if database and database != "AE101_SALES_ENT":
        text = text.replace("AE101_SALES_ENT", database)
    return text


def run_file(conn, filename):
    """여러 문장이 든 SQL 파일을 같은 세션에서 실행합니다 (세션 변수 $load_id 유지)."""
    for _ in conn.execute_string(sql_text(filename), remove_comments=True):
        pass


def setup(conn):
    """sql/00_setup.sql : DB·스키마·테이블 생성 (AE101_DATABASE 이름으로)."""
    for _ in conn.execute_string(sql_text("00_setup.sql", DATABASE), remove_comments=True):
        pass


def _fail(conn, load_id, message):
    with conn.cursor() as cur:
        cur.execute("UPDATE AUDIT.PIPELINE_RUNS SET status = 'FAILED', finished_at = CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, "
                    "message = %s WHERE load_id = %s AND status = 'RUNNING'", (message[:1000], load_id))


def insert_raw(conn, raw, load_id, run_ts):
    """RAW 테이블에 이번 배치를 추가(append)합니다. 기존 배치는 지우지 않습니다."""
    with conn.cursor() as cur:
        for table, cols in COLUMNS.items():
            names = ("load_id", "loaded_at", "src_file", "src_row", *cols)
            sql = f"INSERT INTO RAW.{table.upper()} ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})"
            rows = [(load_id, run_ts, r["src_file"], r["src_row"], *(r[c] for c in cols)) for r in raw[table]]
            for i in range(0, len(rows), BATCH):
                cur.executemany(sql, rows[i:i + BATCH])


def load(conn, raw, expected_summary, allow_empty=False):
    """한 번의 실행(배치). 성공하면 load_id, 실패하면 예외."""
    run_file(conn, "01_start_run.sql")
    with conn.cursor() as cur:
        load_id, run_ts = cur.execute("SELECT load_id, TO_VARCHAR(run_ts, 'YYYY-MM-DD HH24:MI:SS.FF3') FROM CORE.RUN_CTX").fetchone()
    try:
        insert_raw(conn, raw, load_id, run_ts)
        for f in CORE_FILES:
            run_file(conn, f)
        with conn.cursor() as cur:
            row = cur.execute(f"SELECT {', '.join(SUMMARY_COLUMNS)} FROM CORE.RUN_SUMMARY").fetchone()
        actual = {k: int(v) for k, v in zip(SUMMARY_COLUMNS, row)}
        if actual != expected_summary:
            raise ValueError(f"CORE summary differs from local calculation: snowflake={actual} local={expected_summary}")
        if actual["revenue_orders"] == 0 and not allow_empty:
            raise ValueError("Zero revenue orders: inspect the report, or explicitly use --allow-empty")
        for f in MART_FILES:
            run_file(conn, f)
        with conn.cursor() as cur:
            status, message = cur.execute("SELECT status, message FROM AUDIT.PIPELINE_RUNS WHERE load_id = %s",
                                          (load_id,)).fetchone()
        if status != "SUCCESS":
            raise ValueError(f"Pipeline finished with {status}: {message}")
        for f in VIEW_FILES:
            run_file(conn, f)
        return load_id
    except Exception as exc:
        try:
            _fail(conn, load_id, f"Pipeline failed: {type(exc).__name__}")
        except Exception:
            pass
        raise
