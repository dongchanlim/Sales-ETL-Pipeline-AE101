"""python -m src.pipeline --dry-run / --load"""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from .config import ROOT
from .extract import extract
from .transform import transform
from .validate import validate, build_dw

def prepare(folder):
    raw = extract(folder)
    clean, errors, duplicates = transform(raw)
    orders, items, errors, exclusions = validate(clean, errors)
    dw = build_dw(clean, orders, items)
    return {"dw": dw, "errors": errors, "duplicates": duplicates, "exclusions": exclusions,
            "summary": {"input_rows": sum(map(len, raw.values())), "duplicate_rows": len(duplicates),
                        "error_rows": len({(e["source_file"], e["source_row_number"]) for e in errors}),
                        "excluded_orders": len(exclusions), "sales_orders": len(orders),
                        "sales_amount": sum(r["order_amount"] for r in orders)}}

def main():
    parser = argparse.ArgumentParser(description="AE101 full-snapshot Sales ETL")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--load", action="store_true")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--allow-empty", action="store_true", help="Allow replacing DW with zero sales orders")
    args = parser.parse_args()
    run_id = str(uuid4())
    conn = None
    try:
        if args.load:
            from .config import connect
            from .audit import start, finish
            conn = connect()
            start(conn, run_id)
        result = prepare(args.input)
        args.output.mkdir(parents=True, exist_ok=True)
        path = args.output / f"{run_id}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if conn:
            from .load import load
            load(conn, run_id, result, allow_empty=args.allow_empty)
        print(json.dumps({"run_id": run_id, "mode": "load" if args.load else "dry-run", **result["summary"], "report": str(path)}, ensure_ascii=False))
    except Exception:
        if conn:
            # Connector errors may contain connection details; keep the remote summary generic.
            from .audit import finish
            try:
                finish(conn, run_id, "FAILED", message="Pipeline failed; inspect local exception and validation results")
            except Exception:
                pass
        raise
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
