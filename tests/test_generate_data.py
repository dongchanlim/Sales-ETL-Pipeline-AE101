"""scripts/generate_data.py : 실행마다 다른 데이터, 같은 seed 재현, 정답표 데이터 고정, 심은 문제의 판정."""
from collections import Counter, defaultdict
import contextlib
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.config import ROOT
from src.pipeline import _by_category, prepare
from tests.helpers import GENERATOR, RAW, first_run

# 정답표 데이터(--answer-key)의 파일 해시. 바뀌면 docs/data_generation.md 3절·노트북·tests 의 기대값이 모두 틀어집니다.
ANSWER_KEY_SHA256 = {
    "customers.csv": "d2e768651ece40e0ba306bbe8506c6010a49344fb5d948d283a7cd3cac535f2c",
    "products.csv": "df0df5ffca0f46a4ac66f99fe9fbe5adbaf49e420817394faf824fec83097649",
    "orders.csv": "7861a7abe8e9ffd4373b14afd730a7bb100e4def50468c00b2e8f4765db92fbb",
    "order_items.csv": "8a0a2e51b6b17e931fddcbed6e793f5c5e638fc2a1be0e92bfafa5f7eff3a715",
    "payments.csv": "3baa112428eee06c7c0c5685e8bc5ed262f4080825859f3664094ebfc809aa4a",
}
SEEDS = (7, 20261113)          # 무작위 모드 검사용 고정 seed (실패를 재현할 수 있게)
REMOVED = ("EXACT_DUPLICATE", "REMOVED")


@lru_cache(maxsize=None)
def random_run(seed):
    folder = Path(tempfile.mkdtemp(prefix=f"ae101_seed{seed}_"))
    key = GENERATOR.generate(folder, seed=seed)
    return folder, key, prepare(folder, None, "R1", "2026-11-04 10:00:00")


def verify(key, result):
    """answer_key.json 과 파이프라인 결과가 맞지 않는 곳을 문자열 목록으로 돌려줍니다 (빈 목록이면 통과)."""
    problems = []
    found = defaultdict(set)
    for i in result["core"]["issues"]:
        found[(i["source_file"], i["record_key"])].add((i["error_code"], i["action"]))
    quality = {q["order_id"]: q for q in result["core"]["order_quality"]}
    if result["run"]["status"] != "SUCCESS":
        problems.append(f"run {result['run']['status']}: {result['run'].get('message')}")
    problems += [f"DQ {name} = {n}" for name, n in result["checks"] if n]
    for t in key["types"]:
        orders = t["keys"] if t["file"] == "orders.csv" else []
        for k in t["keys"]:
            got = found.get((t["file"], k), set())
            if t["kind"] == "detected":
                want = (t["expected"]["error_code"], t["expected"]["action"])
                if want not in got:
                    problems.append(f"{t['name']} {k}: expected {want}, got {sorted(got)}")
            elif got - {REMOVED}:
                problems.append(f"{t['name']} {k}: {t['kind']} but flagged {sorted(got - {REMOVED})}")
        if t["kind"] != "detected":
            want_reason = "NOT_COMPLETED" if t["name"] == "cancelled_with_success_payment" else None
            for oid in orders + t.get("related", []):
                reason = quality[oid]["exclusion_reason"] if oid in quality else "(not loaded)"
                if reason != want_reason:
                    problems.append(f"{t['name']} {oid}: exclusion_reason {reason}, expected {want_reason}")
    return problems


def profile(folder):
    """분포 비교용 요약: 지역 비율, 주문 상태 비율, 주문당 라인 수, 월별 주문 비율, 행 수."""
    import csv
    rows = {}
    for t in ("customers", "orders", "order_items"):
        with open(Path(folder) / f"{t}.csv", encoding="utf-8", newline="") as f:
            rows[t] = list(csv.DictReader(f))[40:]          # 수업용 사례(앞부분)는 무시해도 비율에 영향 없음
    regions = Counter(c["region"] for c in rows["customers"] if c["region"])
    statuses = Counter(o["order_status"] for o in rows["orders"])
    months = Counter(o["order_date"][:7] for o in rows["orders"] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", o["order_date"]))
    n_orders = len(rows["orders"])
    return {"seoul": regions["서울"] / sum(regions.values()), "gyeonggi": regions["경기"] / sum(regions.values()),
            "completed": statuses["completed"] / n_orders, "lines_per_order": len(rows["order_items"]) / n_orders,
            "months": {m: n / n_orders for m, n in months.items() if "2025-01" <= m <= "2026-10"}, "orders": n_orders}


class AnswerKeyDataTests(unittest.TestCase):
    def test_answer_key_mode_is_fixed(self):
        for name, digest in ANSWER_KEY_SHA256.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((RAW / name).read_bytes()).hexdigest(), digest)

    def test_answer_key_mode_has_no_random_only_problems(self):
        key = json.loads((RAW / "answer_key.json").read_text(encoding="utf-8"))
        self.assertEqual((key["mode"], key["seed"]), ("answer-key", 101))
        self.assertNotIn("undetected", {t["kind"] for t in key["types"]})
        counts = {t["name"]: t["count"] for t in key["types"]}
        for name, n in GENERATOR.ANSWER_KEY_COUNTS.items():
            self.assertEqual(counts[name], n, name)
        self.assertEqual(key["row_counts"], {"customers": 2028, "products": 151, "orders": 30081,
                                             "order_items": 66262, "payments": 31096})


class RandomModeTests(unittest.TestCase):
    def test_each_run_is_different_and_seed_reproduces(self):
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        key_a, key_b = GENERATOR.generate(a), GENERATOR.generate(b)
        self.assertNotEqual(key_a["seed"], key_b["seed"])
        self.assertNotEqual((a / "orders.csv").read_bytes(), (b / "orders.csv").read_bytes())
        again = Path(tempfile.mkdtemp())
        GENERATOR.generate(again, seed=key_a["seed"])
        for name in (*ANSWER_KEY_SHA256, "answer_key.json"):
            self.assertEqual((a / name).read_bytes(), (again / name).read_bytes(), name)

    def test_teaching_cases_stay_at_the_top(self):
        folder, _, _ = random_run(SEEDS[0])
        for table, cases in GENERATOR.TEACHING_CASES.items():
            lines = (folder / f"{table}.csv").read_text(encoding="utf-8").splitlines()[1:1 + len(cases)]
            self.assertEqual(lines, [",".join(c) for c in cases], table)

    def test_planted_problems_are_judged_as_the_answer_key_says(self):
        for seed in SEEDS:
            _, key, result = random_run(seed)
            with self.subTest(seed=seed):
                self.assertEqual(verify(key, result), [])
                kinds = {t["kind"] for t in key["types"] if t["count"]}
                self.assertEqual(kinds, {"detected", "undetected", "normal"})

    def test_distribution_is_close_to_answer_key_data(self):
        ref = profile(RAW)
        ref_summary = first_run()["core"]["summary"]
        ref_eligible = ref_summary["revenue_orders"] / len(first_run()["core"]["order_quality"])
        ref_aov = ref_summary["revenue_amount"] / ref_summary["revenue_orders"]
        ref_category = _by_category(first_run()["state"])
        ref_category = {name: amount / sum(ref_category.values()) for name, amount in ref_category.items()}
        for seed in SEEDS:
            folder, _, result = random_run(seed)
            got = profile(folder)
            with self.subTest(seed=seed):
                self.assertAlmostEqual(got["seoul"], ref["seoul"], delta=0.03)
                self.assertAlmostEqual(got["gyeonggi"], ref["gyeonggi"], delta=0.03)
                self.assertAlmostEqual(got["completed"], ref["completed"], delta=0.02)
                self.assertAlmostEqual(got["lines_per_order"], ref["lines_per_order"], delta=0.1)
                self.assertLess(abs(got["orders"] / ref["orders"] - 1), 0.08)
                for month, share in ref["months"].items():
                    self.assertAlmostEqual(got["months"][month], share, delta=0.006, msg=month)
                eligible = result["core"]["summary"]["revenue_orders"] / len(result["core"]["order_quality"])
                self.assertAlmostEqual(eligible, ref_eligible, delta=0.03)
                summary = result["core"]["summary"]
                self.assertLess(abs(summary["revenue_amount"] / summary["revenue_orders"] / ref_aov - 1), 0.10)
                category = _by_category(result["state"])
                for name, share in ref_category.items():
                    self.assertAlmostEqual(category[name] / sum(category.values()), share, delta=0.04, msg=name)

    def test_runs_as_a_notebook_cell(self):
        """노트북 셀·exec() 에는 __file__ 이 없고 sys.argv 에 커널 인자가 들어 있어도 실행돼야 합니다."""
        source = (ROOT / "scripts" / "generate_data.py").read_text(encoding="utf-8")
        before, folder = os.getcwd(), Path(tempfile.mkdtemp())
        os.chdir(folder)
        try:
            with patch.object(sys, "argv", ["ipykernel_launcher.py", "-f", "kernel-1234.json"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                exec(compile(source, "<notebook cell>", "exec"), {"__name__": "__main__"})
        finally:
            os.chdir(before)
        key = json.loads((folder / "data" / "raw" / "answer_key.json").read_text(encoding="utf-8"))
        self.assertEqual(key["mode"], "random")
        self.assertTrue((folder / "data" / "raw" / "orders.csv").exists())

    def test_main_takes_options_as_a_list(self):
        folder = Path(tempfile.mkdtemp())
        with contextlib.redirect_stdout(io.StringIO()):
            GENERATOR.main(["--seed", "5", "--out", str(folder)])
        self.assertEqual(json.loads((folder / "answer_key.json").read_text(encoding="utf-8"))["seed"], 5)

    def test_every_problem_type_is_documented(self):
        doc = (ROOT / "docs" / "data_generation.md").read_text(encoding="utf-8")
        missing = [name for name in GENERATOR.ERROR_TYPES if f"`{name}`" not in doc]
        self.assertEqual(missing, [], "docs/data_generation.md 에 문제 종류를 추가하세요")


if __name__ == "__main__":
    unittest.main()
