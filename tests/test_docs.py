"""docs/data_rules.md 의 품질 검사 설명이 sql/08 · src/mart.py 와 맞는지 확인합니다."""
import re
import unittest

from src.config import ROOT


def sql_check_names():
    text = (ROOT / "sql" / "08_mart_dq_checks.sql").read_text(encoding="utf-8")
    return re.findall(r"SELECT '(\w+)'", text)


def python_check_names():
    text = (ROOT / "src" / "mart.py").read_text(encoding="utf-8")
    body = text[text.index("def dq_checks"):text.index("def run_pipeline")]
    return re.findall(r'\(\s*"(\w+)",', body)


class DataRulesDocTests(unittest.TestCase):
    def test_sql_and_python_define_the_same_checks(self):
        self.assertEqual(len(sql_check_names()), 17)
        self.assertEqual(sql_check_names(), python_check_names())

    def test_every_check_is_documented(self):
        doc = (ROOT / "docs" / "data_rules.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| (\d+) \| `(\w+)` \|", doc, re.M)
        self.assertEqual([name for _, name in rows], sql_check_names(), "docs/data_rules.md 검사 표를 sql/08 순서에 맞추세요")
        self.assertEqual([int(n) for n, _ in rows], list(range(1, len(rows) + 1)))


if __name__ == "__main__":
    unittest.main()
