"""문자열로 원본을 읽고 파일/행 위치를 보존합니다."""
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
    result = {}
    for name, columns in COLUMNS.items():
        path = Path(folder) / f"{name}.csv"
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)) or not set(columns) <= set(headers):
                raise ValueError(f"{path.name}: missing or duplicate headers")
            records = []
            for row in reader:
                if None in row or any(row[c] is None for c in columns):
                    raise ValueError(f"{path.name}:{reader.line_num}: malformed CSV row")
                records.append({**{c: row[c] for c in columns},
                                "_file": path.name, "_row": reader.line_num})
            result[name] = records
    return result
