"""STEP 3 스테이지 경로 : Git data/raw 또는 생성기 → @RAW.LANDING/current/ → RAW.

Snowflake 없이 확인할 수 있는 것만 봅니다.
  - 생성 프로시저 핸들러(generate_data.land_to_stage)가 스테이지에 올리는 파일
  - 노트북 step3_0_generate 셀의 분기 (가짜 Snowpark 세션)
  - 프로시저 DDL · COPY FILES · INSERT 가 가리키는 경로와 파일 이름이 서로 맞는지
  - 스테이지에 올라간 파일을 그대로 파이프라인에 넣으면 정답표대로 판정되는지
"""
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

from src.config import ROOT
from src.pipeline import prepare
from tests.helpers import GENERATOR, RAW
from tests.test_generate_data import verify

PROCEDURE = "AE101_SALES_ENT.RAW.GENERATE_LANDING_FILES"


def cells(notebook):
    nb = json.loads((ROOT / "notebooks" / notebook).read_text(encoding="utf-8"))
    return {c["metadata"]["name"]: "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"}


class FakeStage:
    """session.file.put_stream 이 올린 파일을 {스테이지 경로: bytes} 로 모읍니다."""

    def __init__(self):
        self.files, self.options = {}, set()

    def put_stream(self, stream, location, auto_compress=True, overwrite=False):
        self.files[location] = stream.read()
        self.options.add((auto_compress, overwrite))


class FakeSession:
    """노트북 셀이 쓰는 Snowpark 세션의 일부: sql().collect(), call(), file.put_stream()."""

    def __init__(self, source, seed=0, load_id="L-TEST-1"):
        self.source, self.seed, self.load_id = source, seed, load_id
        self.file, self.statements, self.calls = FakeStage(), [], []

    def sql(self, query):
        self.statements.append(" ".join(query.split()))
        if "$landing_source" in query:
            rows = [(self.source, self.seed)]
        elif "CORE.RUN_CTX" in query:
            rows = [(self.load_id,)]
        else:
            rows = []
        return types.SimpleNamespace(collect=lambda: rows)

    def call(self, name, *args):
        self.calls.append((name, *args))
        return json.dumps(GENERATOR.land_to_stage(self, *args))   # 프로시저 대신 핸들러를 직접 실행


def run_generate_cell(session):
    """step3_0_generate 셀을 가짜 snowflake.snowpark.context 로 실행합니다."""
    context = types.ModuleType("snowflake.snowpark.context")
    context.get_active_session = lambda: session
    fake = {"snowflake": types.ModuleType("snowflake"), "snowflake.snowpark": types.ModuleType("snowflake.snowpark"),
            "snowflake.snowpark.context": context}
    saved = {name: sys.modules.get(name) for name in fake}
    sys.modules.update(fake)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(cells("ae101_enterprise_walkthrough.ipynb")["step3_0_generate"], "<step3_0_generate>", "exec"), {})
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class HandlerTests(unittest.TestCase):
    def test_answer_key_upload_matches_repository_data(self):
        session = FakeSession("answer-key")
        result = GENERATOR.land_to_stage(session, "answer-key", None)
        self.assertEqual(list(session.file.files), [GENERATOR.LANDING_STAGE + n for n in GENERATOR.FILE_NAMES])
        self.assertEqual(session.file.options, {(False, True)})          # 압축하지 않고 덮어씀
        for location, content in session.file.files.items():
            self.assertEqual(content, (RAW / location.rsplit("/", 1)[1]).read_bytes(), location)
        self.assertEqual((result["mode"], result["seed"]), ("answer-key", 101))
        json.dumps(result)                                               # VARIANT 로 돌려줄 수 있어야 함

    def test_random_seed_zero_draws_new_data_and_seed_reproduces(self):
        first, second, again = FakeSession("random"), FakeSession("random"), FakeSession("random")
        a = GENERATOR.land_to_stage(first, "random", 0)
        GENERATOR.land_to_stage(second, "random", 0)
        GENERATOR.land_to_stage(again, "random", a["seed"])
        self.assertNotEqual(first.file.files, second.file.files)
        self.assertEqual(first.file.files, again.file.files)

    def test_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            GENERATOR.land_to_stage(FakeSession("git"), "git", 0)


class NotebookCellTests(unittest.TestCase):
    def test_git_source_does_not_call_the_generator(self):
        session = FakeSession("git")
        run_generate_cell(session)
        self.assertEqual(session.calls, [])
        self.assertEqual(session.file.files, {})
        self.assertIn("COPY FILES INTO @AE101_SALES_ENT.RAW.LANDING/batches/L-TEST-1/ FROM @AE101_SALES_ENT.RAW.LANDING/current/ "
                      "FILES = ('answer_key.json')", session.statements)

    def test_random_source_calls_the_generator_then_archives_answer_key(self):
        session = FakeSession("random", seed=7)
        run_generate_cell(session)
        self.assertEqual(session.calls, [(PROCEDURE, "random", 7)])
        self.assertEqual(len(session.file.files), 6)
        self.assertTrue(session.statements[-1].startswith("COPY FILES INTO @AE101_SALES_ENT.RAW.LANDING/batches/L-TEST-1/"))

    def test_unknown_source_stops_before_archiving(self):
        session = FakeSession("randon")
        with self.assertRaises(ValueError):
            run_generate_cell(session)
        self.assertFalse(any(s.startswith("COPY FILES") for s in session.statements))

    def test_staged_files_go_through_the_pipeline_as_the_answer_key_says(self):
        session = FakeSession("random", seed=11)
        run_generate_cell(session)
        folder = Path(tempfile.mkdtemp())                                # STEP 3 이 스테이지에서 읽는 것과 같은 파일
        for location, content in session.file.files.items():
            (folder / location.rsplit("/", 1)[1]).write_bytes(content)
        key = json.loads((folder / "answer_key.json").read_text(encoding="utf-8"))
        self.assertEqual(key["seed"], 11)
        self.assertEqual(verify(key, prepare(folder, None, "L-TEST-1", "2026-11-04 10:00:00")), [])


class PathConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.walk = cells("ae101_enterprise_walkthrough.ipynb")
        self.daily = cells("ae101_daily_batch.ipynb")

    def test_procedure_ddl_points_at_the_handler_in_this_repository(self):
        ddl = self.walk["step1"]
        imports = re.search(r"IMPORTS = \('@AE101_DB\.GIT_REPOS\.SALES_ETL_PIPELINE/branches/main/(.+?)'\)", ddl).group(1)
        self.assertTrue((ROOT / imports).is_file(), imports)
        module, function = re.search(r"HANDLER = '(\w+)\.(\w+)'", ddl).groups()
        self.assertEqual(module, Path(imports).stem)
        self.assertTrue(callable(getattr(GENERATOR, function)))
        self.assertIn("CREATE OR REPLACE PROCEDURE RAW.GENERATE_LANDING_FILES(SOURCE VARCHAR, SEED NUMBER)", ddl)
        self.assertIn(PROCEDURE, self.walk["step3_0_generate"])

    def test_copy_insert_and_generator_use_the_same_files_and_stage(self):
        landing, load = self.walk["step3_0_landing"], self.walk["step3"]
        copied = re.findall(r"'([\w.]+)'", re.search(r"FILES = \((.+?)\);", landing).group(1))
        self.assertEqual(tuple(copied), GENERATOR.FILE_NAMES)
        self.assertIn("COPY FILES INTO @RAW.LANDING/current/", landing)
        read = re.findall(r"FROM @RAW\.LANDING/current/(\w+\.csv) \(FILE_FORMAT", load)
        self.assertEqual(tuple(read), GENERATOR.FILE_NAMES[:5])
        self.assertNotIn("GIT_REPOS", load)                              # STEP 3 은 스테이지에서만 읽음
        self.assertTrue(GENERATOR.LANDING_STAGE.endswith("RAW.LANDING/current/"))

    def test_walkthrough_uses_git_and_daily_batch_generates_new_data(self):
        self.assertIn("SET (landing_source, landing_seed) = ('git', 0);", self.walk["step3_0_source"])
        self.assertIn("SET (landing_source, landing_seed) = ('random', 0);", self.daily["daily_source"])
        self.assertNotIn("step3_0_source", self.daily)
        order = list(self.daily)
        self.assertLess(order.index("step2"), order.index("daily_source"))
        self.assertLess(order.index("daily_source"), order.index("step3_0_landing"))
        self.assertLess(order.index("step3_0_landing"), order.index("step3_0_generate"))
        self.assertLess(order.index("step3_0_generate"), order.index("step3"))


if __name__ == "__main__":
    unittest.main()
