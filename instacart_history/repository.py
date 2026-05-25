from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ProductCandidate:
    id: int
    product_id: str
    title: str
    store_name: str | None
    product_url: str | None
    image_url: str | None
    account_label: str
    purchase_count: int
    latest_order_date: str | None


@dataclass(frozen=True)
class OrderItem:
    id: int
    account_label: str
    order_id: str
    line_key: str
    order_date: str | None
    store_name: str | None
    product_id: str
    title: str
    quantity: float | None
    price_paid: float | None
    product_url: str | None
    image_url: str | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class IngredientMapping:
    id: int
    ingredient_key: str
    ingredient_text: str
    selected_product_id: str | None
    status: str
    confidence: float | None
    reason: str | None
    hint: str | None
    source: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MappingAttempt:
    id: int
    ingredient_key: str
    llm_input: dict[str, Any]
    llm_output: dict[str, Any]
    selected_product_id: str | None
    confidence: float | None
    reason: str | None
    review_required: bool
    created_at: str


class HistoryRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY,
                    account_label TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    order_date TEXT,
                    store_name TEXT,
                    currency TEXT,
                    grand_total REAL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_label, order_id)
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY,
                    account_label TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    line_key TEXT NOT NULL,
                    order_date TEXT,
                    store_name TEXT,
                    product_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    quantity REAL,
                    price_paid REAL,
                    product_url TEXT,
                    image_url TEXT,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_label, line_key)
                );

                CREATE TABLE IF NOT EXISTS ingredient_mappings (
                    id INTEGER PRIMARY KEY,
                    ingredient_key TEXT NOT NULL,
                    ingredient_text TEXT NOT NULL,
                    selected_product_id TEXT,
                    status TEXT NOT NULL CHECK(status IN ('approved', 'suggested', 'rejected', 'needs_review')),
                    confidence REAL,
                    reason TEXT,
                    hint TEXT,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_mappings_key_status
                    ON ingredient_mappings(ingredient_key, status, updated_at);

                CREATE TABLE IF NOT EXISTS mapping_attempts (
                    id INTEGER PRIMARY KEY,
                    ingredient_key TEXT NOT NULL,
                    llm_input TEXT NOT NULL,
                    llm_output TEXT NOT NULL,
                    selected_product_id TEXT,
                    confidence REAL,
                    reason TEXT,
                    review_required INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def upsert_order(
        self,
        *,
        account_label: str,
        order_id: str,
        order_date: str | None,
        store_name: str | None,
        currency: str | None,
        grand_total: float | None,
        raw_payload: dict[str, Any],
    ) -> str:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM orders WHERE account_label = ? AND order_id = ?",
                (account_label, order_id),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO orders (
                    account_label, order_id, order_date, store_name, currency, grand_total, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_label, order_id) DO UPDATE SET
                    order_date = excluded.order_date,
                    store_name = excluded.store_name,
                    currency = excluded.currency,
                    grand_total = excluded.grand_total,
                    raw_payload = excluded.raw_payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    account_label,
                    order_id,
                    order_date,
                    store_name,
                    currency,
                    grand_total,
                    json.dumps(raw_payload, sort_keys=True),
                ),
            )
            return "updated" if existing else "created"

    def upsert_order_item(
        self,
        *,
        account_label: str,
        order_id: str,
        line_key: str,
        order_date: str | None,
        store_name: str | None,
        product_id: str,
        title: str,
        quantity: float | None,
        price_paid: float | None,
        product_url: str | None,
        image_url: str | None,
        raw_payload: dict[str, Any],
    ) -> str:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM order_items WHERE account_label = ? AND line_key = ?",
                (account_label, line_key),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO order_items (
                    account_label, order_id, line_key, order_date, store_name, product_id, title,
                    quantity, price_paid, product_url, image_url, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_label, line_key) DO UPDATE SET
                    order_id = excluded.order_id,
                    order_date = excluded.order_date,
                    store_name = excluded.store_name,
                    product_id = excluded.product_id,
                    title = excluded.title,
                    quantity = excluded.quantity,
                    price_paid = excluded.price_paid,
                    product_url = excluded.product_url,
                    image_url = excluded.image_url,
                    raw_payload = excluded.raw_payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    account_label,
                    order_id,
                    line_key,
                    order_date,
                    store_name,
                    product_id,
                    title,
                    quantity,
                    price_paid,
                    product_url,
                    image_url,
                    json.dumps(raw_payload, sort_keys=True),
                ),
            )
            return "updated" if existing else "created"

    def get_order_item(self, item_id: int) -> OrderItem:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM order_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"order item not found: {item_id}")
        return self._order_item(row)

    def find_products(self, query: str, *, limit: int = 25) -> list[ProductCandidate]:
        terms = [term for term in normalize_for_search(query).split(" ") if term]
        if not terms:
            terms = [query.strip().lower()]
        where = " AND ".join("LOWER(title) LIKE ?" for _ in terms)
        params = [f"%{term}%" for term in terms]
        sql = f"""
            SELECT
                MIN(id) AS id,
                product_id,
                title,
                store_name,
                product_url,
                image_url,
                MIN(account_label) AS account_label,
                COUNT(*) AS purchase_count,
                MAX(order_date) AS latest_order_date
            FROM order_items
            WHERE {where}
            GROUP BY product_id, title, store_name, product_url, image_url
            ORDER BY purchase_count DESC, latest_order_date DESC, title ASC
            LIMIT ?
        """
        with self.connect() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        return [self._product_candidate(row) for row in rows]

    def product_by_product_id(self, product_id: str) -> ProductCandidate | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    MIN(id) AS id,
                    product_id,
                    title,
                    store_name,
                    product_url,
                    image_url,
                    MIN(account_label) AS account_label,
                    COUNT(*) AS purchase_count,
                    MAX(order_date) AS latest_order_date
                FROM order_items
                WHERE product_id = ?
                GROUP BY product_id, title, store_name, product_url, image_url
                ORDER BY purchase_count DESC, latest_order_date DESC
                LIMIT 1
                """,
                (product_id,),
            ).fetchone()
        return self._product_candidate(row) if row else None

    def save_mapping(
        self,
        *,
        ingredient_key: str,
        ingredient_text: str,
        selected_product_id: str | None,
        status: str,
        confidence: float | None,
        reason: str | None,
        hint: str | None,
        source: str,
    ) -> IngredientMapping:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ingredient_mappings (
                    ingredient_key, ingredient_text, selected_product_id, status,
                    confidence, reason, hint, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ingredient_key, ingredient_text, selected_product_id, status, confidence, reason, hint, source),
            )
            row = conn.execute("SELECT * FROM ingredient_mappings WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._mapping(row)

    def latest_mapping(self, ingredient_key: str, *, statuses: Iterable[str]) -> IngredientMapping | None:
        status_list = list(statuses)
        placeholders = ",".join("?" for _ in status_list)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM ingredient_mappings
                WHERE ingredient_key = ? AND status IN ({placeholders})
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (ingredient_key, *status_list),
            ).fetchone()
        return self._mapping(row) if row else None

    def list_mappings(self, *, status: str | None = None) -> list[IngredientMapping]:
        query = "SELECT * FROM ingredient_mappings"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY updated_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._mapping(row) for row in rows]

    def update_mapping(
        self,
        mapping_id: int,
        *,
        status: str | None = None,
        selected_product_id: str | None = None,
        hint: str | None = None,
        reason: str | None = None,
    ) -> IngredientMapping:
        current = self.get_mapping(mapping_id)
        next_status = status if status is not None else current.status
        next_product_id = selected_product_id if selected_product_id is not None else current.selected_product_id
        next_hint = hint if hint is not None else current.hint
        next_reason = reason if reason is not None else current.reason
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingredient_mappings
                SET status = ?, selected_product_id = ?, hint = ?, reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (next_status, next_product_id, next_hint, next_reason, mapping_id),
            )
            row = conn.execute("SELECT * FROM ingredient_mappings WHERE id = ?", (mapping_id,)).fetchone()
        return self._mapping(row)

    def get_mapping(self, mapping_id: int) -> IngredientMapping:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM ingredient_mappings WHERE id = ?", (mapping_id,)).fetchone()
        if row is None:
            raise KeyError(f"mapping not found: {mapping_id}")
        return self._mapping(row)

    def record_attempt(
        self,
        *,
        ingredient_key: str,
        llm_input: dict[str, Any],
        llm_output: dict[str, Any],
        selected_product_id: str | None,
        confidence: float | None,
        reason: str | None,
        review_required: bool,
    ) -> MappingAttempt:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mapping_attempts (
                    ingredient_key, llm_input, llm_output, selected_product_id,
                    confidence, reason, review_required
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ingredient_key,
                    json.dumps(llm_input, sort_keys=True),
                    json.dumps(llm_output, sort_keys=True),
                    selected_product_id,
                    confidence,
                    reason,
                    int(review_required),
                ),
            )
            row = conn.execute("SELECT * FROM mapping_attempts WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._attempt(row)

    def list_attempts(self) -> list[MappingAttempt]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM mapping_attempts ORDER BY id").fetchall()
        return [self._attempt(row) for row in rows]

    @staticmethod
    def _product_candidate(row: sqlite3.Row) -> ProductCandidate:
        return ProductCandidate(
            id=int(row["id"]),
            product_id=str(row["product_id"]),
            title=str(row["title"]),
            store_name=row["store_name"],
            product_url=row["product_url"],
            image_url=row["image_url"],
            account_label=str(row["account_label"]),
            purchase_count=int(row["purchase_count"]),
            latest_order_date=row["latest_order_date"],
        )

    @staticmethod
    def _order_item(row: sqlite3.Row) -> OrderItem:
        return OrderItem(
            id=int(row["id"]),
            account_label=str(row["account_label"]),
            order_id=str(row["order_id"]),
            line_key=str(row["line_key"]),
            order_date=row["order_date"],
            store_name=row["store_name"],
            product_id=str(row["product_id"]),
            title=str(row["title"]),
            quantity=row["quantity"],
            price_paid=row["price_paid"],
            product_url=row["product_url"],
            image_url=row["image_url"],
            raw_payload=json.loads(row["raw_payload"]),
        )

    @staticmethod
    def _mapping(row: sqlite3.Row) -> IngredientMapping:
        return IngredientMapping(
            id=int(row["id"]),
            ingredient_key=str(row["ingredient_key"]),
            ingredient_text=str(row["ingredient_text"]),
            selected_product_id=row["selected_product_id"],
            status=str(row["status"]),
            confidence=row["confidence"],
            reason=row["reason"],
            hint=row["hint"],
            source=str(row["source"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _attempt(row: sqlite3.Row) -> MappingAttempt:
        return MappingAttempt(
            id=int(row["id"]),
            ingredient_key=str(row["ingredient_key"]),
            llm_input=json.loads(row["llm_input"]),
            llm_output=json.loads(row["llm_output"]),
            selected_product_id=row["selected_product_id"],
            confidence=row["confidence"],
            reason=row["reason"],
            review_required=bool(row["review_required"]),
            created_at=str(row["created_at"]),
        )


def normalize_for_search(value: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())
