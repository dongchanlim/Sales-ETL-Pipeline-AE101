"""python -m src.pipeline --dry-run | --load | --setup

  --dry-run : Snowflake 없이 로컬에서 RAW → CORE → MART 를 계산하고 보고서(JSON)를 씁니다.
              --state 파일을 주면 이전 MART 상태를 이어받아 SCD2 이력·소프트 삭제를 재현합니다.
  --setup   : Snowflake 에 sql/00_setup.sql 을 실행합니다 (DB·스키마·테이블 생성).
  --load    : Snowflake 에 RAW 배치를 적재하고 노트북과 같은 sql/ 파일을 순서대로 실행합니다.
"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from .config import ROOT
from .core import build_core
from .extract import extract
from . import mart, reports


def prepare(folder, state=None, load_id=None, run_ts=None):
    """로컬 1회 실행. 반환: core 결과, 갱신된 MART state, 실행 기록, 품질 검사 결과."""
    raw = extract(folder)
    core_result = build_core(raw)
    load_id = load_id or str(uuid4())
    run_ts = run_ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_state, run, checks = mart.run_pipeline(state or mart.empty_state(), core_result, load_id, run_ts)
    return {"raw": raw, "core": core_result, "state": new_state, "run": run, "checks": checks}


def report(result):
    core, state = result["core"], result["state"]
    return {
        "run": result["run"],
        "summary": core["summary"],
        "issues_by_action": dict(sorted(Counter(f"{i['action']}:{i['error_code']}" for i in core["issues"]).items())),
        "exclusion_reasons": dict(Counter(q["exclusion_reason"] or "(revenue)" for q in core["order_quality"]).most_common()),
        "mart_rows": mart.table_counts(state),
        "dq_checks": dict(result["checks"]),
        "headline": reports.headline(state),
        "revenue_by_category": dict(_by_category(state).most_common()),
        "revenue_by_region_aswas": reports.revenue_by_region_aswas(state),
        "payment_summary": reports.payment_summary(state),
        "issues": core["issues"],
    }


def _by_category(state):
    out = Counter()
    for p in reports.revenue_by_product(state):
        out[p["category"]] += p["revenue"]
    return out


def main():
    parser = argparse.ArgumentParser(description="AE101 Sales ETL : RAW → CORE → MART")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="로컬 실행 (Snowflake 불필요)")
    mode.add_argument("--setup", action="store_true", help="Snowflake 에 sql/00_setup.sql 실행")
    mode.add_argument("--load", action="store_true", help="Snowflake 에 적재 (sql/ 파일 실행)")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--state", type=Path, help="--dry-run 에서 이어받을/저장할 MART 상태 JSON")
    parser.add_argument("--allow-empty", action="store_true", help="매출 인식 주문이 0건이어도 MART 반영")
    args = parser.parse_args()

    if args.setup:
        from .config import connect
        from .load import setup
        conn = connect(use_database=False)
        try:
            setup(conn)
        finally:
            conn.close()
        print(json.dumps({"mode": "setup", "status": "OK"}))
        return

    if args.load:
        from .config import connect
        from .load import load
        raw = extract(args.input)
        summary = build_core(raw)["summary"]
        conn = connect()
        try:
            load_id = load(conn, raw, summary, allow_empty=args.allow_empty)
        finally:
            conn.close()
        print(json.dumps({"mode": "load", "load_id": load_id, **summary}, ensure_ascii=False))
        return

    state = None
    if args.state and args.state.exists():
        state = json.loads(args.state.read_text(encoding="utf-8"))
    result = prepare(args.input, state)
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / f"{result['run']['load_id']}.json"
    path.write_text(json.dumps(report(result), ensure_ascii=False, indent=2), encoding="utf-8")
    if args.state:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(result["state"], ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"mode": "dry-run", "status": result["run"]["status"], **result["core"]["summary"],
                      "mart_rows": mart.table_counts(result["state"]), "report": str(path)}, ensure_ascii=False))
    if result["run"]["status"] != "SUCCESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
