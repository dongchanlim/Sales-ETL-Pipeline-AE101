"""RAW : CSV 를 문자열 그대로 읽고 파일명·행 위치(src_file, src_row)를 붙입니다.

Snowflake 의 sql/02_load_raw_from_git.sql 과 같은 형태입니다.
src_row 는 헤더를 1행으로 센 파일 행 번호(첫 데이터 행 = 2)입니다.
"""
import csv
from pathlib import Path

COLUMNS = {
    "customers": ("customer_id", "customer_name", "email", "region"),
    "products": ("product_id", "product_name", "category"),
    "orders": ("order_id", "customer_id", "order_date", "order_status", "order_amount"),
    "order_items": ("order_item_id", "order_id", "product_id", "quantity", "unit_price"),
    "payments": ("payment_id", "order_id", "payment_status", "payment_amount", "paid_at"),
}
KEYS = {name: cols[0] for name, cols in COLUMNS.items()}


def extract(folder):
    """{table: [ {src_file, src_row, <columns...>} ]} 를 돌려줍니다. 헤더 이상은 즉시 실패."""
    result = {}
    for name, columns in COLUMNS.items():
        path = Path(folder) / f"{name}.csv"
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)) or not set(columns) <= set(headers):
                raise ValueError(f"{path.name}: missing or duplicate headers")
            records = []
            for i, row in enumerate(reader):
                if None in row or any(row[c] is None for c in columns):
                    raise ValueError(f"{path.name}:{reader.line_num}: malformed CSV row")
                records.append({"src_file": path.name, "src_row": i + 2, **{c: row[c] for c in columns}})
            result[name] = records
    return result
