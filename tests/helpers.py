"""테스트 공용: 같은 입력의 로컬 실행 결과를 한 번만 계산해 재사용합니다."""
import csv
from functools import lru_cache
from pathlib import Path
import shutil
import tempfile

from src.config import ROOT
from src.pipeline import prepare

RAW = ROOT / "data/raw"
RUN1 = ("L1", "2026-11-04 10:00:00")


@lru_cache(maxsize=None)
def first_run():
    return prepare(RAW, None, *RUN1)


def copy_raw(edit=None):
    """data/raw 를 임시 폴더로 복사하고, edit(table, rows) 로 CSV 를 고칩니다. rows[0] 은 헤더."""
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
