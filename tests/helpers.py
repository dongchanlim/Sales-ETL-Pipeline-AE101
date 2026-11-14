"""테스트 공용: 정답표 데이터를 만들고, 같은 입력의 로컬 실행 결과를 한 번만 계산해 재사용합니다.

data/raw 는 생성기를 실행할 때마다 바뀌므로 테스트는 data/raw 를 읽지 않습니다.
대신 `scripts/generate_data.py --answer-key` 와 같은 데이터(seed 101)를 임시 폴더에 만들어 RAW 로 씁니다.
"""
import csv
from functools import lru_cache
import importlib.util
from pathlib import Path
import shutil
import tempfile

from src.config import ROOT
from src.pipeline import prepare


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_data", ROOT / "scripts" / "generate_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = _load_generator()
RAW = Path(tempfile.mkdtemp(prefix="ae101_answer_key_"))
GENERATOR.generate(RAW, answer_key=True)
RUN1 = ("L1", "2026-11-04 10:00:00")


@lru_cache(maxsize=None)
def first_run():
    return prepare(RAW, None, *RUN1)


def copy_raw(edit=None):
    """정답표 데이터를 임시 폴더로 복사하고, edit(table, rows) 로 CSV 를 고칩니다. rows[0] 은 헤더."""
    folder = Path(tempfile.mkdtemp())
    for path in RAW.glob("*.csv"):
        shutil.copy(path, folder / path.name)
    if edit:
        for path in folder.glob("*.csv"):
            with path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            rows = edit(path.stem, rows) or rows
            with path.open("w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows(rows)
    return folder
