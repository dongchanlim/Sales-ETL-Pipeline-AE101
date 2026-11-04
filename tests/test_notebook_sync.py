"""notebooks/ 의 SQL 셀과 sql/ 파일이 같은 내용인지 확인합니다. 한쪽만 고치면 실패합니다."""
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


if __name__ == "__main__":
    unittest.main()
