"""SQL 연결 없이 트랜잭션 제어 흐름과 빈 입력 방어를 검증합니다."""
import unittest
from src.load import load
from src.pipeline import prepare
from src.config import ROOT

class Cursor:
    def __init__(self, conn): self.conn = conn
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params=None):
        self.conn.calls.append(sql)
        return self
    def executemany(self, sql, rows): self.conn.calls.append(sql)
    def fetchall(self): return [("amount_check", self.conn.failures)]

class Connection:
    def __init__(self, failures=0): self.calls=[]; self.failures=failures
    def cursor(self): return Cursor(self)
    def autocommit(self, value): pass

class LoadTests(unittest.TestCase):
    def test_failed_validation_rolls_back(self):
        conn=Connection(1)
        with self.assertRaises(ValueError): load(conn,"test",prepare(ROOT / "data/raw"))
        self.assertIn("ROLLBACK",conn.calls)
        self.assertNotIn("COMMIT",conn.calls)
        self.assertFalse(any(sql.startswith("UPDATE AUDIT.PIPELINE_RUNS") for sql in conn.calls))

    def test_success_commits_after_checks(self):
        conn=Connection()
        load(conn,"test",prepare(ROOT / "data/raw"))
        self.assertEqual(conn.calls[-1],"COMMIT")
        self.assertNotIn("ROLLBACK",conn.calls)

    def test_empty_snapshot_is_explicit(self):
        conn=Connection()
        result=prepare(ROOT / "data/raw")
        result["dw"]["fact_orders"]=[]
        with self.assertRaises(ValueError): load(conn,"test",result)
        self.assertNotIn("BEGIN",conn.calls)
