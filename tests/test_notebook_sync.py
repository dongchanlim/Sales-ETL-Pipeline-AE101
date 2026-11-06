"""notebooks/ 의 SQL 셀과 sql/ 파일이 같은 내용인지 확인합니다. 한쪽만 고치면 실패합니다."""
import importlib.util
import json
import unittest

from src.config import ROOT


def code_cells(name):
    nb = json.loads((ROOT / "notebooks" / name).read_text(encoding="utf-8"))
    return {c["metadata"]["name"]: "".join(c["source"]).strip("\n") for c in nb["cells"] if c["cell_type"] == "code"}


class NotebookSyncTests(unittest.TestCase):
    def test_every_sql_file_matches_its_notebook_cells(self):
        cells = code_cells("ae101_enterprise_walkthrough.ipynb")
        for path in sorted((ROOT / "sql").glob("*.sql")):
            text = path.read_text(encoding="utf-8")
            names = text.splitlines()[2].split("(셀 ")[1].split(")")[0].split(", ")
            body = text.split("\n\n", 1)[1].strip("\n")
            with self.subTest(file=path.name):
                self.assertEqual(body, "\n\n".join(cells[n] for n in names))

    def test_mart_notebook_uses_same_etl_cells(self):
        main, mart = code_cells("ae101_enterprise_walkthrough.ipynb"), code_cells("ae101_mart_etl.ipynb")
        for name, body in mart.items():
            if name.startswith("step7"):
                with self.subTest(cell=name):
                    self.assertEqual(body, main[name])

    def test_daily_notebook_is_built_from_walkthrough(self):
        """매일 배치 노트북은 워크스루 셀로 다시 만든 결과와 같아야 합니다 (scripts/build_daily_notebook.py)."""
        spec = importlib.util.spec_from_file_location("build_daily", ROOT / "scripts" / "build_daily_notebook.py")
        build_daily = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_daily)
        on_disk = json.loads((ROOT / "notebooks" / "ae101_daily_batch.ipynb").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, build_daily.build(), "python scripts/build_daily_notebook.py 로 다시 만드세요")

    def test_daily_notebook_runs_only_pipeline_steps(self):
        nb = json.loads((ROOT / "notebooks" / "ae101_daily_batch.ipynb").read_text(encoding="utf-8"))
        order = [c["metadata"]["name"] for c in nb["cells"] if c["cell_type"] == "code"]
        self.assertEqual(order[0], "daily_prepare")
        self.assertEqual(order[-1], "daily_gate")
        self.assertLess(order.index("daily_guard"), order.index("step7_1a_dim_customer"))
        self.assertLess(order.index("step2"), order.index("step3"))
        self.assertLess(order.index("step6"), order.index("step7_0_ctx"))
        for once_only in ("step0_fetch", "step1", "step8", "step9", "step10", "step11", "step12"):
            self.assertNotIn(once_only, order)
        main = code_cells("ae101_enterprise_walkthrough.ipynb")
        for name, body in code_cells("ae101_daily_batch.ipynb").items():
            if name.startswith("step"):
                with self.subTest(cell=name):
                    self.assertEqual(body, main[name])

    def test_schedule_deploys_daily_notebook_from_main(self):
        sql = (ROOT / "orchestration" / "daily_schedule.sql").read_text(encoding="utf-8")
        self.assertIn("MAIN_FILE = 'ae101_daily_batch.ipynb'", sql)
        self.assertIn("/branches/main/notebooks/", sql)
        self.assertIn("EXECUTE NOTEBOOK AE101_SALES_ENT.OPS.AE101_DAILY_BATCH()", sql)
        self.assertIn("FINALIZE = OPS.T_DAILY_BATCH", sql)


if __name__ == "__main__":
    unittest.main()
