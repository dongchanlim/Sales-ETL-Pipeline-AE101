"""완전 중복은 제거하고, 같은 키의 서로 다른 원본은 모두 분리합니다."""
from collections import defaultdict
from datetime import date, datetime
import re
from .extract import COLUMNS, KEYS

def issue(table, row, code, detail):
    return {"source_file": row["_file"], "source_row_number": row["_row"],
            "record_key": row.get(KEYS[table], ""), "error_code": code,
            "error_detail": detail,
            "order_id": row.get("order_id") if table in ("orders", "order_items", "payments") else None}

def transform(raw):
    clean, errors, duplicates = {}, [], []
    for table, rows in raw.items():
        unique, seen = [], set()
        for row in rows:
            signature = tuple(row[c] for c in COLUMNS[table])
            if signature in seen:
                duplicates.append(issue(table, row, "EXACT_DUPLICATE", "Identical source row removed"))
            else:
                seen.add(signature)
                unique.append(row)
        groups = defaultdict(list)
        for row in unique:
            row = {k: (v.strip() or None) if k in COLUMNS[table] else v for k, v in row.items()}
            groups[row[KEYS[table]]].append(row)
        accepted = []
        for key, group in groups.items():
            if key is not None and len(group) > 1:
                errors.extend(issue(table, row, "KEY_CONFLICT", "Same business key has conflicting source rows") for row in group)
                continue
            for original in group:
                row = dict(original)
                try:
                    optional = {"email", "region"} if table == "customers" else set()
                    for col in COLUMNS[table]:
                        if col not in optional and row[col] is None:
                            raise ValueError(f"{col}: required value missing")
                    for col in ("quantity", "unit_price", "order_amount", "payment_amount"):
                        if col in row:
                            if not re.fullmatch(r"[0-9]+", row[col]):
                                raise ValueError(f"{col}: expected non-negative integer KRW/quantity")
                            row[col] = int(row[col])
                            if row[col] > 10**12:
                                raise ValueError(f"{col}: exceeds project input limit")
                    if table == "order_items" and row["quantity"] == 0:
                        raise ValueError("quantity must be positive")
                    if table == "orders":
                        row["order_date"] = date.fromisoformat(row["order_date"]).isoformat()
                        if row["order_status"] not in {"completed", "pending", "cancelled"}:
                            raise ValueError("unknown order_status")
                    if table == "payments":
                        if row["payment_status"] not in {"succeeded", "failed", "pending"}:
                            raise ValueError("unknown payment_status")
                        dt = datetime.fromisoformat(row["paid_at"])
                        if dt.tzinfo is not None:
                            raise ValueError("paid_at must be timezone-naive KST")
                        row["paid_at"] = dt.isoformat(sep=" ")
                    if table == "customers":
                        row["region"] = row["region"] or "Unknown"
                    accepted.append(row)
                except ValueError as exc:
                    errors.append(issue(table, original, "INVALID_VALUE", str(exc)))
        clean[table] = accepted
    return clean, errors, duplicates
