import csv
import os
from pathlib import Path
import random
import tempfile
import unittest
from uuid import uuid4
from src.config import ROOT
from src.pipeline import prepare

def canonical(dw):
    return {t:sorted((tuple(sorted(r.items())) for r in rows),key=repr) for t,rows in dw.items()}

class RerunTests(unittest.TestCase):
    def test_identical_input_same_business_values(self):
        self.assertEqual(canonical(prepare(ROOT / "data/raw")["dw"]), canonical(prepare(ROOT / "data/raw")["dw"]))

    def test_reorder_and_duplicate_source_rows(self):
        baseline = prepare(ROOT / "data/raw")
        with tempfile.TemporaryDirectory() as folder:
            for path in (ROOT / "data/raw").glob("*.csv"):
                with path.open(newline="",encoding="utf-8") as f:
                    rows = list(csv.reader(f))
                body = rows[1:] * 2
                random.Random(42).shuffle(body)
                with Path(folder,path.name).open("w",newline="",encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows([rows[0], *body])
            repeat = prepare(folder)
        self.assertEqual(canonical(baseline["dw"]), canonical(repeat["dw"]))
        self.assertGreater(repeat["summary"]["duplicate_rows"], baseline["summary"]["duplicate_rows"])

@unittest.skipUnless(os.getenv("AE101_RUN_SNOWFLAKE_TESTS") == "1", "Explicit opt-in and dedicated Snowflake test database required")
class SnowflakeRerunTests(unittest.TestCase):
    def test_live_merge_rerun(self):
        from src.config import connect, DATABASE
        from src.load import load, COLUMNS
        from src.audit import start
        if not DATABASE.upper().endswith("_TEST"):
            self.fail("Use an initialized, disposable database ending in _TEST")
        conn = connect()
        try:
            result = prepare(ROOT / "data/raw")
            snapshots = []
            for _ in range(2):
                run_id = str(uuid4())
                start(conn,run_id)
                load(conn,run_id,result)
                with conn.cursor() as cur:
                    snapshots.append({t:cur.execute(f"SELECT * FROM DW.{t} ORDER BY {cols[0]}").fetchall() for t,cols in COLUMNS.items()})
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(len(snapshots[0]["fact_orders"]), 27055)
        finally:
            conn.close()
