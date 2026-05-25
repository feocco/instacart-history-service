from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from instacart_history.repository import HistoryRepository


@dataclass(frozen=True)
class ImportResult:
    files_seen: int = 0
    orders_created: int = 0
    orders_updated: int = 0
    items_created: int = 0
    items_updated: int = 0
    rows_skipped: int = 0

    def add(self, other: "ImportResult") -> "ImportResult":
        return ImportResult(
            files_seen=self.files_seen + other.files_seen,
            orders_created=self.orders_created + other.orders_created,
            orders_updated=self.orders_updated + other.orders_updated,
            items_created=self.items_created + other.items_created,
            items_updated=self.items_updated + other.items_updated,
            rows_skipped=self.rows_skipped + other.rows_skipped,
        )


class InstacartCsvImporter:
    def __init__(self, repo: HistoryRepository) -> None:
        self.repo = repo

    def import_directory(self, data_dir: str | Path) -> ImportResult:
        root = Path(data_dir)
        result = ImportResult()
        for path in sorted(root.rglob("*.csv")):
            if "Instacart" not in path.name and "INSTACART" not in path.name:
                continue
            result = result.add(self.import_file(path, root=root))
        return result

    def import_file(self, path: Path, *, root: Path | None = None) -> ImportResult:
        rows = read_csv_rows(path)
        header_index = find_header_index(rows)
        if header_index is None:
            return ImportResult(files_seen=1, rows_skipped=len(rows))
        header = rows[header_index]
        records = records_from_rows(header, rows[header_index + 1 :])
        account_label = account_label_for(path, root or path.parent)
        if header and header[0] == "Order Type":
            return self._import_orders(records, account_label)
        if header and header[0] == "Product Order Type":
            return self._import_items(records, account_label)
        return ImportResult(files_seen=1, rows_skipped=len(records))

    def _import_orders(self, records: list[dict[str, str]], account_label: str) -> ImportResult:
        created = updated = skipped = 0
        for record in records:
            order_id = clean(record.get("Order ID"))
            if not order_id:
                skipped += 1
                continue
            status = self.repo.upsert_order(
                account_label=account_label,
                order_id=order_id,
                order_date=parse_date(record.get("Order Date")),
                store_name=clean(record.get("Store Name")),
                currency=clean(record.get("Currency")),
                grand_total=parse_float(record.get("Grand Total")),
                raw_payload=record,
            )
            if status == "created":
                created += 1
            else:
                updated += 1
        return ImportResult(files_seen=1, orders_created=created, orders_updated=updated, rows_skipped=skipped)

    def _import_items(self, records: list[dict[str, str]], account_label: str) -> ImportResult:
        created = updated = skipped = 0
        per_order_index: dict[str, int] = {}
        for record in records:
            order_id = clean(record.get("Order ID"))
            title = clean(record.get("Product Description"))
            if not order_id or not title:
                skipped += 1
                continue
            product_id = clean(record.get("Item Number/ASIN")) or product_id_from_url(record.get("Product URL")) or title
            index = per_order_index.get(order_id, 0)
            per_order_index[order_id] = index + 1
            line_key = f"{order_id}:{product_id}:{index}"
            status = self.repo.upsert_order_item(
                account_label=account_label,
                order_id=order_id,
                line_key=line_key,
                order_date=parse_date(record.get("Order Date")),
                store_name=clean(record.get("Store Name")),
                product_id=product_id,
                title=title,
                quantity=parse_float(record.get("Product Quantity")),
                price_paid=parse_float(record.get("Price Paid (Before-Tax)")),
                product_url=clean(record.get("Product URL")),
                image_url=clean(record.get("Product Image")),
                raw_payload=record,
            )
            if status == "created":
                created += 1
            else:
                updated += 1
        return ImportResult(files_seen=1, items_created=created, items_updated=updated, rows_skipped=skipped)


def read_csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.reader(handle))


def find_header_index(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows):
        if row and row[0] in {"Order Type", "Product Order Type"}:
            return index
    return None


def records_from_rows(header: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * max(0, len(header) - len(row))
        records.append({key: padded[index] if index < len(padded) else "" for index, key in enumerate(header)})
    return records


def account_label_for(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = rel.parts
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}"
    if len(parts) >= 2:
        return parts[0]
    return "default"


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_date(value: Any) -> str | None:
    text = clean(value)
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def parse_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def product_id_from_url(value: Any) -> str | None:
    text = clean(value)
    if not text:
        return None
    marker = "/products/"
    if marker not in text:
        return None
    return text.split(marker, 1)[1].split("/", 1)[0].split("?", 1)[0] or None
