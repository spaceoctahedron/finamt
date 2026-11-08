"""
finamt.storage.sqlite
~~~~~~~~~~~~~~~~~~~~~~~~
SQLite-backed receipt repository — 4-table schema.

Tables
------
counterparties  — vendors and clients with parsed address + tax numbers
receipts        — core record: hash id, FK to counterparty, type, totals
receipt_items   — line items, FK to receipt
receipt_content — raw OCR text, FK to receipt (kept separate, can be large)

Receipt ID
----------
The ``id`` is the SHA-256 hash of the normalised OCR text (computed by
``ReceiptData.__post_init__``).  Identical content → identical ID → duplicate.

Default path: ``~/.finamt/default/finamt.db``
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import (
    Address,
    Counterparty,
    Posting,
    PostingDirection,
    PostingType,
    ReceiptCategory,
    ReceiptData,
    ReceiptItem,
    ReceiptType,
)
from .project import resolve_project

DEFAULT_DB_PATH = resolve_project().db_path  # ~/.finamt/default/finamt.db
_SCHEMA_VERSION = 1

_NULL_STRINGS = frozenset({"null", "none", "n/a", "na", "nan", "nil", "undefined"})


def _null_to_none(v):
    """Map the literal text "null"/"none"/... (written by LLMs) to ``None``."""
    if isinstance(v, str) and v.strip().lower() in _NULL_STRINGS:
        return None
    return v


class SQLiteRepository:
    """Persistent SQLite storage implementing ``ReceiptRepository``."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._cleanup_orphaned_counterparties()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> SQLiteRepository:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self._create_tables()
                self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                self._conn.commit()
            # Always run migrations — safe on new and existing DBs
            self._migrate()

    def _migrate(self) -> None:
        """Idempotent column/table additions for schema evolution."""
        for tbl, col, typedef in [
            ("receipt_items", "position", "INTEGER"),
            ("receipt_items", "vat_amount", "TEXT"),
            ("counterparties", "verified", "INTEGER DEFAULT 0"),
            ("counterparties", "street_and_number", "TEXT"),
            ("counterparties", "address_supplement", "TEXT"),
            ("counterparties", "state", "TEXT"),
            ("receipt_vat_splits", "net_amount", "TEXT"),
            ("receipts", "currency", "TEXT DEFAULT 'EUR'"),
            ("receipts", "subcategory", "TEXT"),
            ("receipts", "description", "TEXT"),
            ("receipts", "private_use_share", "TEXT DEFAULT '0'"),
            ("receipts", "validation_warnings", "TEXT"),
            ("receipts", "einfuhr_vat", "TEXT"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typedef}")
                self._conn.commit()
            except Exception:
                pass  # column already exists — expected on all but first run

        # Migrate existing street/street_number data to street_and_number
        try:
            self._conn.execute("""
                UPDATE counterparties
                SET street_and_number = TRIM(COALESCE(street, '') || ' ' || COALESCE(street_number, ''))
                WHERE street_and_number IS NULL AND (street IS NOT NULL OR street_number IS NOT NULL)
            """)
            self._conn.commit()
        except Exception:
            pass  # migration already done or not needed

        # vat_splits table (safe CREATE IF NOT EXISTS)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS receipt_vat_splits (
                id         TEXT PRIMARY KEY,
                receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position   INTEGER,
                vat_rate   TEXT,
                vat_amount TEXT,
                net_amount TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_vat_splits_receipt
                ON receipt_vat_splits (receipt_id);
        """)
        self._conn.commit()

        # postings table — double-entry journal entries derived from receipts
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS postings (
                id           TEXT PRIMARY KEY,
                receipt_id   TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position     INTEGER,
                posting_type TEXT NOT NULL,
                direction    TEXT NOT NULL,
                amount       TEXT NOT NULL,
                description  TEXT,
                created_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_postings_receipt
                ON postings (receipt_id);
            CREATE INDEX IF NOT EXISTS idx_postings_type
                ON postings (posting_type);
        """)
        self._conn.commit()

        # project_metadata — key/value store for project-level settings (e.g. taxpayer profile)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS project_metadata (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS counterparties (
                id                  TEXT PRIMARY KEY,
                name                TEXT,
                street_and_number   TEXT,
                address_supplement  TEXT,
                postcode            TEXT,
                city                TEXT,
                state               TEXT,
                country             TEXT,
                tax_number          TEXT,
                vat_id              TEXT,
                verified            INTEGER NOT NULL DEFAULT 0,
                created_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cp_name   ON counterparties (name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_cp_vat_id ON counterparties (vat_id);

            CREATE TABLE IF NOT EXISTS receipts (
                id               TEXT PRIMARY KEY,  -- SHA-256 content hash
                counterparty_id  TEXT REFERENCES counterparties(id) ON DELETE SET NULL,
                receipt_type     TEXT NOT NULL DEFAULT 'purchase',
                receipt_number   TEXT,
                receipt_date     TEXT,
                total_amount     TEXT,
                vat_percentage   TEXT,
                vat_amount       TEXT,
                category         TEXT,
                subcategory      TEXT,
                created_at       TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_receipts_date     ON receipts (receipt_date);
            CREATE INDEX IF NOT EXISTS idx_receipts_category ON receipts (category);
            CREATE INDEX IF NOT EXISTS idx_receipts_type     ON receipts (receipt_type);

            CREATE TABLE IF NOT EXISTS receipt_items (
                id           TEXT PRIMARY KEY,
                receipt_id   TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position     INTEGER,
                description  TEXT,
                quantity     TEXT,
                unit_price   TEXT,
                total_price  TEXT,
                vat_rate     TEXT,
                vat_amount   TEXT,
                category     TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_items_receipt ON receipt_items (receipt_id);

            CREATE TABLE IF NOT EXISTS receipt_vat_splits (
                id           TEXT PRIMARY KEY,
                receipt_id   TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position     INTEGER,
                vat_rate     TEXT,
                vat_amount   TEXT,
                net_amount   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_vat_splits_receipt ON receipt_vat_splits (receipt_id);

            CREATE TABLE IF NOT EXISTS receipt_content (
                receipt_id   TEXT PRIMARY KEY REFERENCES receipts(id) ON DELETE CASCADE,
                raw_text     TEXT,
                content_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS postings (
                id           TEXT PRIMARY KEY,
                receipt_id   TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position     INTEGER,
                posting_type TEXT NOT NULL,
                direction    TEXT NOT NULL,
                amount       TEXT NOT NULL,
                description  TEXT,
                created_at   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_postings_receipt ON postings (receipt_id);
            CREATE INDEX IF NOT EXISTS idx_postings_type    ON postings (posting_type);
        """)

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _execmany(self, sql: str, rows: list) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _dec(v) -> Decimal | None:
        return Decimal(str(v)) if v is not None else None

    # ------------------------------------------------------------------
    # Counterparty deduplication
    # ------------------------------------------------------------------

    def get_or_create_counterparty(self, cp: Counterparty) -> Counterparty:
        """
        Return an existing counterparty matching by name only (case-insensitive).

        VAT-ID is intentionally NOT used as a match key: agent OCR errors can
        produce the same VAT ID for completely different companies (e.g. the
        taxpayer's own ID being attached to a supplier), and merging on VAT ID
        alone would silently overwrite unrelated counterparties.  Duplicate VAT
        IDs are surfaced to the user in the UI instead.

        Only inserts a new row when no name-match is found.
        The SELECT + INSERT is performed under the write lock to prevent
        duplicate rows from concurrent uploads.
        """
        with self._lock:
            row = None
            if cp.name and cp.name.strip():
                row = self._conn.execute(
                    "SELECT * FROM counterparties"
                    " WHERE LOWER(name) = LOWER(?)"
                    " ORDER BY created_at ASC LIMIT 1",
                    (cp.name.strip(),),
                ).fetchone()
            if row is not None:
                return self._row_to_counterparty(row)
            # No existing match — insert
            self._conn.execute(
                """INSERT INTO counterparties
                   (id, name, street_and_number, address_supplement, postcode, city, state, country,
                    tax_number, vat_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cp.id,
                    cp.name,
                    cp.address.street_and_number,
                    cp.address.address_supplement,
                    cp.address.postcode,
                    cp.address.city,
                    cp.address.state,
                    cp.address.country,
                    cp.tax_number,
                    cp.vat_id,
                    self._now(),
                ),
            )
            self._conn.commit()
        return cp

    def _cleanup_orphaned_counterparties(self) -> None:
        """Delete counterparty rows not linked to any receipt.

        An orphan is created when the user applies a verified counterparty to
        a receipt — the auto-extracted row loses its only reference and should
        be removed.  This is the only automatic counterparty housekeeping;
        everything else is driven by explicit user actions in the UI.
        """
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM counterparties
                WHERE id NOT IN (
                    SELECT counterparty_id FROM receipts
                    WHERE counterparty_id IS NOT NULL
                )
                """
            )
            self._conn.commit()

    def _row_to_counterparty(self, row: sqlite3.Row) -> Counterparty:
        # Older rows may hold the literal text "null" written by the LLM;
        # present those as missing values.
        def _c(key: str):
            return _null_to_none(row[key]) if key in row.keys() else None

        return Counterparty(
            id=row["id"],
            name=_c("name"),
            address=Address(
                street_and_number=_c("street_and_number"),
                address_supplement=_c("address_supplement"),
                postcode=_c("postcode"),
                city=_c("city"),
                state=_c("state"),
                country=_c("country"),
            ),
            tax_number=_c("tax_number"),
            vat_id=_c("vat_id"),
        )

    # ------------------------------------------------------------------
    # save
    # ------------------------------------------------------------------

    def save(self, receipt: ReceiptData) -> bool:
        """
        Persist a receipt.

        Returns ``True`` on success, ``False`` if a duplicate already exists.
        Raises no exceptions on duplicate — callers check the return value
        or call ``exists()`` first.
        """
        if self.exists(receipt.id):
            return False

        # Resolve/create counterparty
        cp_id: str | None = None
        if receipt.counterparty:
            resolved = self.get_or_create_counterparty(receipt.counterparty)
            receipt.counterparty = resolved
            cp_id = resolved.id

        date_str: str | None = None
        if receipt.receipt_date is not None:
            d = (
                receipt.receipt_date.date()
                if isinstance(receipt.receipt_date, datetime)
                else receipt.receipt_date
            )
            date_str = d.isoformat()

        with self._lock:
            # receipts
            self._conn.execute(
                """INSERT INTO receipts
                   (id, counterparty_id, receipt_type, receipt_number,
                    receipt_date, total_amount, vat_percentage, vat_amount,
                    currency, category, subcategory, description,
                    private_use_share, validation_warnings, einfuhr_vat, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    receipt.id,
                    cp_id,
                    str(receipt.receipt_type),
                    receipt.receipt_number,
                    date_str,
                    str(receipt.total_amount) if receipt.total_amount is not None else None,
                    str(receipt.vat_percentage) if receipt.vat_percentage is not None else None,
                    str(receipt.vat_amount) if receipt.vat_amount is not None else None,
                    getattr(receipt, "currency", "EUR") or "EUR",
                    str(receipt.category),
                    getattr(receipt, "subcategory", None),
                    getattr(receipt, "description", None) or None,
                    str(getattr(receipt, "private_use_share", "0") or "0"),
                    json.dumps(getattr(receipt, "validation_warnings", []) or []),
                    str(getattr(receipt, "einfuhr_vat", None) or "") or None,
                    self._now(),
                ),
            )

            # receipt_items
            import uuid as _uuid

            item_rows = [
                (
                    str(_uuid.uuid4()),
                    receipt.id,
                    item.position,
                    item.description,
                    str(item.quantity) if item.quantity is not None else None,
                    str(item.unit_price) if item.unit_price is not None else None,
                    str(item.total_price) if item.total_price is not None else None,
                    str(item.vat_rate) if item.vat_rate is not None else None,
                    str(item.vat_amount) if item.vat_amount is not None else None,
                    str(item.category),
                )
                for item in receipt.items
            ]
            self._conn.executemany(
                """INSERT INTO receipt_items
                   (id, receipt_id, position, description, quantity, unit_price,
                    total_price, vat_rate, vat_amount, category)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                item_rows,
            )

            # vat_splits
            if hasattr(receipt, "vat_splits") and receipt.vat_splits:
                import uuid as _uuid_vs

                for pos, split in enumerate(receipt.vat_splits, start=1):
                    self._conn.execute(
                        """INSERT INTO receipt_vat_splits (id, receipt_id, position, vat_rate, vat_amount, net_amount)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            str(_uuid_vs.uuid4()),
                            receipt.id,
                            split.get("position", pos),
                            str(split["vat_rate"]) if split.get("vat_rate") is not None else None,
                            str(split["vat_amount"])
                            if split.get("vat_amount") is not None
                            else None,
                            str(split["net_amount"])
                            if split.get("net_amount") is not None
                            else None,
                        ),
                    )

            # receipt_content
            self._conn.execute(
                """INSERT INTO receipt_content (receipt_id, raw_text, content_hash)
                   VALUES (?,?,?)""",
                (receipt.id, receipt.raw_text, receipt.id),
            )

            # postings — generate and persist double-entry journal entries
            self._insert_postings(receipt)

            self._conn.commit()

        return True

    # ------------------------------------------------------------------
    # Postings helpers
    # ------------------------------------------------------------------

    def _insert_postings(self, receipt: ReceiptData) -> None:
        """Generate postings from *receipt* and write them to the DB.

        Called inside an existing write-lock context so it must **not** call
        ``self._lock`` again.
        """
        import uuid as _uuid_p

        postings = receipt.generate_postings()
        now = self._now()
        for pos, p in enumerate(postings, start=1):
            self._conn.execute(
                """INSERT INTO postings
                   (id, receipt_id, position, posting_type, direction, amount, description, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(_uuid_p.uuid4()),
                    receipt.id,
                    pos,
                    str(p.posting_type),
                    str(p.direction),
                    str(p.amount),
                    p.description,
                    now,
                ),
            )

    def _sync_postings(self, receipt_id: str) -> None:
        """Wipe and regenerate postings for *receipt_id*.

        Call this after any update that may alter amounts or
        ``private_use_share``.
        """
        receipt = self.get(receipt_id)
        if receipt is None:
            return
        with self._lock:
            self._conn.execute("DELETE FROM postings WHERE receipt_id = ?", (receipt_id,))
            self._insert_postings(receipt)
            self._conn.commit()

    def get_postings(self, receipt_id: str) -> list[Posting]:
        """Return all postings for *receipt_id*, ordered by position."""
        rows = self._conn.execute(
            """SELECT * FROM postings
               WHERE receipt_id = ?
               ORDER BY position ASC""",
            (receipt_id,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                p = Posting(
                    receipt_id=r["receipt_id"],
                    posting_type=PostingType(r["posting_type"]),
                    direction=PostingDirection(r["direction"]),
                    amount=Decimal(str(r["amount"])),
                    description=r["description"] or "",
                )
                result.append(p)
            except (ValueError, Exception):
                pass  # skip malformed rows from old schema
        return result

    def list_all_postings(self) -> list[dict]:
        """Return all postings across all receipts as dicts (e.g. for EÜR derivation)."""
        rows = self._conn.execute(
            """SELECT p.*, r.receipt_date, r.receipt_type, r.category
               FROM postings p
               JOIN receipts r ON r.id = p.receipt_id
               ORDER BY r.receipt_date DESC NULLS LAST, p.receipt_id, p.position ASC"""
        ).fetchall()
        return [
            {
                "receipt_id": r["receipt_id"],
                "receipt_date": r["receipt_date"],
                "receipt_type": r["receipt_type"],
                "category": r["category"],
                "position": r["position"],
                "posting_type": r["posting_type"],
                "direction": r["direction"],
                "amount": float(Decimal(str(r["amount"]))),
                "description": r["description"] or "",
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def exists(self, receipt_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        return row is not None

    def get(self, receipt_id: str) -> ReceiptData | None:
        row = self._conn.execute(
            """SELECT r.*, rc.raw_text,
                      c.id as cp_id, c.name as cp_name,
                      c.street_and_number, c.postcode, c.city, c.state, c.country,
                      c.tax_number, c.vat_id, COALESCE(c.verified, 0) as verified
               FROM receipts r
               LEFT JOIN receipt_content rc ON rc.receipt_id = r.id
               LEFT JOIN counterparties c   ON c.id = r.counterparty_id
               WHERE r.id = ?""",
            (receipt_id,),
        ).fetchone()
        return self._row_to_receipt(row) if row else None

    def delete(self, receipt_id: str) -> bool:
        cur = self._exec("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        return cur.rowcount > 0

    def update(self, receipt_id: str, fields: dict) -> bool:
        """
        Partially update a receipt's mutable fields (user corrections).

        Receipt fields: ``receipt_type``, ``receipt_number``, ``receipt_date``,
        ``total_amount``, ``vat_percentage``, ``vat_amount``, ``category``.

        Counterparty fields (applied to the counterparty row owned by this
        receipt): ``counterparty_name``, ``vat_id``, ``tax_number``,
        and address sub-fields via an ``address`` dict with keys
        ``street_and_number``, ``address_supplement``, ``postcode``,
        ``city``, ``state``, ``country``.

        Returns True if the receipt row was found.
        """
        RECEIPT_MUTABLE = {
            "receipt_type",
            "receipt_number",
            "receipt_date",
            "total_amount",
            "vat_percentage",
            "vat_amount",
            "currency",
            "category",
            "subcategory",
            "description",
            "private_use_share",
            "validation_warnings",
            "einfuhr_vat",
        }
        # Financial fields whose change should trigger posting regeneration
        _POSTING_SENSITIVE = {
            "total_amount",
            "vat_percentage",
            "vat_amount",
            "currency",
            "receipt_type",
            "private_use_share",
        }
        CP_SCALAR = {
            "counterparty_name": "name",
            "vat_id": "vat_id",
            "tax_number": "tax_number",
        }
        ADDR_FIELDS = {
            "street_and_number",
            "address_supplement",
            "postcode",
            "city",
            "state",
            "country",
        }

        receipt_updates = {k: v for k, v in fields.items() if k in RECEIPT_MUTABLE}

        # Normalise date/decimal
        if "receipt_date" in receipt_updates and receipt_updates["receipt_date"]:
            d = receipt_updates["receipt_date"]
            receipt_updates["receipt_date"] = d.isoformat() if hasattr(d, "isoformat") else str(d)
        for field in ("total_amount", "vat_percentage", "vat_amount"):
            if field in receipt_updates and receipt_updates[field] is not None:
                receipt_updates[field] = str(receipt_updates[field])
        if "einfuhr_vat" in receipt_updates:
            try:
                ev = receipt_updates["einfuhr_vat"]
                receipt_updates["einfuhr_vat"] = (
                    str(Decimal(str(ev))) if ev not in (None, "") else None
                )
            except Exception:
                receipt_updates.pop("einfuhr_vat", None)
        if "currency" in receipt_updates:
            raw_cur = str(receipt_updates["currency"]).strip().upper()
            receipt_updates["currency"] = (
                raw_cur if (2 <= len(raw_cur) <= 4 and raw_cur.isalpha()) else "EUR"
            )
        if "private_use_share" in receipt_updates:
            try:
                p = Decimal(str(receipt_updates["private_use_share"]))
                receipt_updates["private_use_share"] = str(max(Decimal("0"), min(Decimal("1"), p)))
            except Exception:
                receipt_updates.pop("private_use_share", None)
        # Serialise validation_warnings list → JSON text
        if "validation_warnings" in receipt_updates:
            vw = receipt_updates["validation_warnings"]
            receipt_updates["validation_warnings"] = json.dumps(vw if isinstance(vw, list) else [])

        # Apply receipt-level updates
        if receipt_updates:
            set_clause = ", ".join(f"{col} = ?" for col in receipt_updates)
            params = tuple(receipt_updates.values()) + (receipt_id,)
            self._exec(f"UPDATE receipts SET {set_clause} WHERE id = ?", params)

        # Counterparty updates
        cp_row = self._conn.execute(
            "SELECT counterparty_id FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        cp_id = cp_row["counterparty_id"] if cp_row else None

        # If the caller specifies an existing counterparty to link to, re-point the
        # receipt to that CP and skip all field-level CP updates — the selected CP's
        # data is already correct as-is in the DB.  The old CP becomes an orphan and
        # will be removed by _cleanup_orphaned_counterparties on the next DB open.
        skip_cp_field_updates = False
        if fields.get("counterparty_id"):
            new_cp_id = str(fields["counterparty_id"])
            self._exec(
                "UPDATE receipts SET counterparty_id = ? WHERE id = ?",
                (new_cp_id, receipt_id),
            )
            cp_id = new_cp_id  # used by counterparty_verified logic below
            skip_cp_field_updates = True

        # Collect all counterparty field changes
        # vat_id and tax_number may be explicitly cleared (set to null/empty),
        # so include them whenever the key is present — even if the value is None.
        # name is only updated when a non-empty value is supplied.
        cp_updates: dict = {}
        for field_in, col in CP_SCALAR.items():
            if field_in not in fields:
                continue
            val = fields[field_in]
            if col == "name" and not val:  # never clear the supplier name
                continue
            # Normalise empty string → None so SQLite stores NULL
            cp_updates[col] = val if val else None
        addr = fields.get("address", {})
        if isinstance(addr, dict):
            for k in ADDR_FIELDS:
                if k in addr:
                    cp_updates[k] = addr[k]

        if cp_updates and not skip_cp_field_updates:
            if cp_id:
                # Edit the counterparty row directly.  All receipts sharing this
                # counterparty will reflect the change — which is the desired
                # behaviour (if OpenAI was mis-labelled everywhere, fix it once).
                # Note: verified is NOT touched here — it must only be set by an
                # explicit user action (checkbox / select-from-verified).  The
                # orphan-cleanup routine uses receipt references, not this flag.
                set_clause = ", ".join(f"{col} = ?" for col in cp_updates)
                params = tuple(cp_updates.values()) + (cp_id,)
                self._exec(f"UPDATE counterparties SET {set_clause} WHERE id = ?", params)
            else:
                # No counterparty row yet — create one and link it to the receipt
                import uuid

                new_cp_id = str(uuid.uuid4())
                self._exec(
                    """INSERT INTO counterparties
                       (id, name, street_and_number, address_supplement, postcode, city, state, country,
                        tax_number, vat_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_cp_id,
                        cp_updates.get("name"),
                        cp_updates.get("street_and_number"),
                        cp_updates.get("address_supplement"),
                        cp_updates.get("postcode"),
                        cp_updates.get("city"),
                        cp_updates.get("state"),
                        cp_updates.get("country"),
                        cp_updates.get("tax_number"),
                        cp_updates.get("vat_id"),
                        self._now(),
                    ),
                )
                self._exec(
                    "UPDATE receipts SET counterparty_id = ? WHERE id = ?",
                    (new_cp_id, receipt_id),
                )

        # VAT splits — full replace when provided
        if "vat_splits" in fields and isinstance(fields["vat_splits"], list):
            import uuid as _uuid_vs2

            self._exec("DELETE FROM receipt_vat_splits WHERE receipt_id = ?", (receipt_id,))
            for pos, split in enumerate(fields["vat_splits"], start=1):
                self._exec(
                    """INSERT INTO receipt_vat_splits (id, receipt_id, position, vat_rate, vat_amount, net_amount)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid_vs2.uuid4()),
                        receipt_id,
                        split.get("position", pos),
                        str(split["vat_rate"]) if split.get("vat_rate") is not None else None,
                        str(split["vat_amount"]) if split.get("vat_amount") is not None else None,
                        str(split["net_amount"]) if split.get("net_amount") is not None else None,
                    ),
                )

        # Counterparty verified flag
        if "counterparty_verified" in fields and cp_id:
            self._exec(
                "UPDATE counterparties SET verified = ? WHERE id = ?",
                (1 if fields["counterparty_verified"] else 0, cp_id),
            )

        # Items — full replace when provided
        if "items" in fields and isinstance(fields["items"], list):
            import uuid as _uuid3

            self._exec("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
            for pos, item in enumerate(fields["items"], start=1):
                self._exec(
                    """INSERT INTO receipt_items
                       (id, receipt_id, position, description, quantity, unit_price,
                        total_price, vat_rate, vat_amount, category)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid3.uuid4()),
                        receipt_id,
                        item.get("position", pos),
                        item.get("description"),
                        str(item["quantity"]) if item.get("quantity") is not None else None,
                        str(item["unit_price"]) if item.get("unit_price") is not None else None,
                        str(item["total_price"]) if item.get("total_price") is not None else None,
                        str(item["vat_rate"]) if item.get("vat_rate") is not None else None,
                        str(item["vat_amount"]) if item.get("vat_amount") is not None else None,
                        item.get("category", "other"),
                    ),
                )

        # Regenerate postings whenever a financially sensitive field changed
        if receipt_updates and _POSTING_SENSITIVE.intersection(receipt_updates):
            self._sync_postings(receipt_id)

        return self.exists(receipt_id)

    def list_verified_counterparties(self) -> list[dict]:
        """Return all verified counterparties sorted alphabetically by name (case-insensitive)."""
        rows = self._conn.execute(
            """SELECT id, name, street_and_number, address_supplement,
                      postcode, city, state, country,
                      tax_number, vat_id, verified
               FROM counterparties
               WHERE verified = 1
               ORDER BY LOWER(COALESCE(name,'')) ASC, name ASC"""
        ).fetchall()
        return [
            {
                "id": r["id"],
                "name": _null_to_none(r["name"]),
                "tax_number": _null_to_none(r["tax_number"]),
                "vat_id": _null_to_none(r["vat_id"]),
                "verified": bool(r["verified"]),
                "address": {
                    "street_and_number": _null_to_none(r["street_and_number"]),
                    "address_supplement": _null_to_none(r["address_supplement"]),
                    "postcode": _null_to_none(r["postcode"]),
                    "city": _null_to_none(r["city"]),
                    "state": _null_to_none(r["state"]),
                    "country": _null_to_none(r["country"]),
                },
            }
            for r in rows
        ]

    def get_category_defaults_for_counterparty(self, cp_id: str) -> dict:
        """Return the most-used (category, subcategory) pair for a counterparty.

        Prefers non-'other' categories.  Returns empty dict when no receipts
        exist yet for this counterparty.
        """
        row = self._conn.execute(
            """
            SELECT category, subcategory, COUNT(*) AS cnt
            FROM   receipts
            WHERE  counterparty_id = ?
              AND  category IS NOT NULL
              AND  category != 'other'
            GROUP BY category, subcategory
            ORDER BY cnt DESC
            LIMIT 1
            """,
            (cp_id,),
        ).fetchone()
        if row is None:
            # Fall back to any category including 'other'
            row = self._conn.execute(
                """
                SELECT category, subcategory, COUNT(*) AS cnt
                FROM   receipts
                WHERE  counterparty_id = ?
                  AND  category IS NOT NULL
                GROUP BY category, subcategory
                ORDER BY cnt DESC
                LIMIT 1
                """,
                (cp_id,),
            ).fetchone()
        if row is None:
            return {}
        return {
            "category": row["category"],
            "subcategory": row["subcategory"] or "",
        }

    def get_known_supplier_defaults(
        self,
        name: str | None,
        receipt_type: str | None = None,
        min_receipts: int = 2,
    ) -> dict:
        """Return the historically dominant (category, subcategory) for a supplier.

        The supplier is matched by name (case-insensitive), consistent with
        :meth:`get_or_create_counterparty`.  Only receipts with a real
        category (not ``'other'``) are counted.  The most frequent category
        wins; the subcategory is then the most frequent one within that
        category (empty string when none was ever set).

        Returns ``{}`` when the supplier is unknown or has fewer than
        *min_receipts* classified receipts, so callers can keep the AI value.
        """
        if not name or not name.strip():
            return {}
        params: list = [name.strip()]
        type_clause = ""
        if receipt_type:
            type_clause = " AND r.receipt_type = ?"
            params.append(str(receipt_type))

        cat_row = self._conn.execute(
            f"""
            SELECT r.category AS category, COUNT(*) AS cnt
            FROM   receipts r
            JOIN   counterparties c ON c.id = r.counterparty_id
            WHERE  LOWER(c.name) = LOWER(?)
              AND  r.category IS NOT NULL
              AND  r.category != 'other'
              {type_clause}
            GROUP BY r.category
            ORDER BY cnt DESC, MAX(r.created_at) DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if cat_row is None or cat_row["cnt"] < min_receipts:
            return {}

        sub_row = self._conn.execute(
            f"""
            SELECT r.subcategory AS subcategory, COUNT(*) AS cnt
            FROM   receipts r
            JOIN   counterparties c ON c.id = r.counterparty_id
            WHERE  LOWER(c.name) = LOWER(?)
              AND  r.category = ?
              AND  r.subcategory IS NOT NULL
              AND  r.subcategory != ''
              {type_clause}
            GROUP BY r.subcategory
            ORDER BY cnt DESC, MAX(r.created_at) DESC
            LIMIT 1
            """,
            [params[0], cat_row["category"], *params[1:]],
        ).fetchone()
        return {
            "category": cat_row["category"],
            "subcategory": (sub_row["subcategory"] if sub_row else "") or "",
            "count": cat_row["cnt"],
        }

    def get_known_supplier_vat(
        self,
        name: str | None,
        receipt_type: str | None = None,
        min_receipts: int = 2,
        min_share: float = 0.8,
    ) -> dict:
        """Return the dominant VAT rate (incl. 0) historically used for a supplier.

        Matching is by counterparty name, case-insensitive.  The rate is only
        returned when at least *min_receipts* receipts carry a VAT percentage
        and one rate accounts for at least *min_share* of them, so suppliers
        with mixed rates (e.g. 7 % and 19 %) are left to the extraction.

        Returns ``{"vat_percentage": Decimal, "count": int}`` or ``{}``.
        """
        if not name or not name.strip():
            return {}
        params: list = [name.strip()]
        type_clause = ""
        if receipt_type:
            type_clause = " AND r.receipt_type = ?"
            params.append(str(receipt_type))
        rows = self._conn.execute(
            f"""
            SELECT r.vat_percentage AS vat
            FROM   receipts r
            JOIN   counterparties c ON c.id = r.counterparty_id
            WHERE  LOWER(c.name) = LOWER(?)
              AND  r.vat_percentage IS NOT NULL
              AND  r.vat_percentage != ''
              {type_clause}
            """,
            params,
        ).fetchall()
        counts: dict[Decimal, int] = {}
        for row in rows:
            try:
                rate = Decimal(str(row["vat"])).quantize(Decimal("0.01"))
            except Exception:
                continue
            counts[rate] = counts.get(rate, 0) + 1
        total = sum(counts.values())
        if total < min_receipts:
            return {}
        rate, n = max(counts.items(), key=lambda kv: kv[1])
        if n / total < min_share:
            return {}
        return {"vat_percentage": rate, "count": n}

    def set_counterparty_verified(self, cp_id: str, verified: bool) -> None:
        self._exec(
            "UPDATE counterparties SET verified = ? WHERE id = ?",
            (1 if verified else 0, cp_id),
        )

    def list_all_counterparties(self) -> list[dict]:
        """Return every counterparty row sorted alphabetically by name (case-insensitive)."""
        rows = self._conn.execute(
            """SELECT id, name, street_and_number, address_supplement,
                      postcode, city, state, country,
                      tax_number, vat_id, verified, created_at
               FROM counterparties
               ORDER BY LOWER(COALESCE(name,'')) ASC, name ASC"""
        ).fetchall()
        return [
            {
                "id": r["id"],
                "name": _null_to_none(r["name"]),
                "tax_number": _null_to_none(r["tax_number"]),
                "vat_id": _null_to_none(r["vat_id"]),
                "verified": bool(r["verified"]),
                "created_at": r["created_at"],
                "address": {
                    "street_and_number": _null_to_none(r["street_and_number"]),
                    "address_supplement": _null_to_none(r["address_supplement"]),
                    "postcode": _null_to_none(r["postcode"]),
                    "city": _null_to_none(r["city"]),
                    "state": _null_to_none(r["state"]),
                    "country": _null_to_none(r["country"]),
                },
            }
            for r in rows
        ]

    def update_counterparty(self, cp_id: str, fields: dict) -> bool:
        """Update editable fields of a counterparty. Returns True if a row was updated.

        The verified flag is only changed when explicitly included in *fields*;
        ordinary field edits (name, address, VAT-ID, …) must not touch it.
        """
        allowed = {
            "name",
            "tax_number",
            "vat_id",
            "verified",
            "street_and_number",
            "address_supplement",
            "postcode",
            "city",
            "state",
            "country",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [cp_id]
        cur = self._exec(f"UPDATE counterparties SET {set_clause} WHERE id = ?", values)
        return cur.rowcount > 0

    def relink_counterparty(self, receipt_id: str, fields: dict) -> bool:
        """Find-or-create a counterparty by name/VAT-ID and link *only* this receipt to it.

        The old counterparty row is untouched — if it becomes unreferenced the
        startup orphan-cleanup will remove it on the next open.
        Returns True if the receipt row was found and updated.
        """
        from finamt.models import Address, Counterparty

        cp = Counterparty(
            name=fields.get("name") or None,
            vat_id=fields.get("vat_id") or None,
            tax_number=fields.get("tax_number") or None,
            address=Address(
                street_and_number=fields.get("street_and_number"),
                address_supplement=fields.get("address_supplement"),
                postcode=fields.get("postcode"),
                city=fields.get("city"),
                state=fields.get("state"),
                country=fields.get("country"),
            ),
        )
        resolved = self.get_or_create_counterparty(cp)
        cur = self._exec(
            "UPDATE receipts SET counterparty_id = ? WHERE id = ?",
            (resolved.id, receipt_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_counterparty(self, cp_id: str) -> bool:
        """Delete a counterparty by id. Returns True if a row was removed."""
        cur = self._exec("DELETE FROM counterparties WHERE id = ?", (cp_id,))
        return cur.rowcount > 0

    def list_all(self) -> Iterable[ReceiptData]:
        return self._query_receipts("ORDER BY receipt_date DESC NULLS LAST")

    def find_by_period(self, start: date, end: date) -> Iterable[ReceiptData]:
        s = (start.date() if isinstance(start, datetime) else start).isoformat()
        e = (end.date() if isinstance(end, datetime) else end).isoformat()
        return self._query_receipts(
            "WHERE r.receipt_date BETWEEN ? AND ? ORDER BY r.receipt_date DESC",
            (s, e),
        )

    def find_by_category(self, category: str) -> Iterable[ReceiptData]:
        return self._query_receipts(
            "WHERE r.category = ? ORDER BY r.receipt_date DESC NULLS LAST",
            (category,),
        )

    def find_by_type(self, receipt_type: str) -> Iterable[ReceiptData]:
        return self._query_receipts(
            "WHERE r.receipt_type = ? ORDER BY r.receipt_date DESC NULLS LAST",
            (receipt_type,),
        )

    # ------------------------------------------------------------------
    # Internal query helper
    # ------------------------------------------------------------------

    def _query_receipts(self, where_order: str, params: tuple = ()) -> list[ReceiptData]:
        sql = f"""
            SELECT r.*, rc.raw_text,
                   c.id as cp_id, c.name as cp_name,
                   c.street_and_number, c.address_supplement, c.postcode, c.city, c.state, c.country,
                   c.tax_number, c.vat_id, COALESCE(c.verified, 0) as verified
            FROM receipts r
            LEFT JOIN receipt_content rc ON rc.receipt_id = r.id
            LEFT JOIN counterparties  c  ON c.id = r.counterparty_id
            {where_order}
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_receipt(row) for row in rows]

    def _row_to_receipt(self, row: sqlite3.Row) -> ReceiptData:
        # Counterparty
        cp: Counterparty | None = None
        if row["cp_id"]:
            _cp_verified = row["verified"] if "verified" in row.keys() else 0
            cp = Counterparty(
                id=row["cp_id"],
                name=_null_to_none(row["cp_name"]),
                address=Address(
                    street_and_number=_null_to_none(row["street_and_number"]),
                    address_supplement=_null_to_none(row["address_supplement"])
                    if "address_supplement" in row.keys()
                    else None,
                    postcode=_null_to_none(row["postcode"]),
                    city=_null_to_none(row["city"]),
                    state=_null_to_none(row["state"]),
                    country=_null_to_none(row["country"]),
                ),
                tax_number=_null_to_none(row["tax_number"]),
                vat_id=_null_to_none(row["vat_id"]),
                verified=bool(_cp_verified),
            )

        # receipt_date
        receipt_date: datetime | None = None
        if row["receipt_date"]:
            d = date.fromisoformat(row["receipt_date"])
            receipt_date = datetime(d.year, d.month, d.day)

        # items (separate query to keep row simple)
        item_rows = self._conn.execute(
            "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY position ASC NULLS LAST",
            (row["id"],),
        ).fetchall()
        items = [
            ReceiptItem(
                description=ir["description"] or "",
                position=ir["position"] if "position" in ir.keys() else None,
                quantity=self._dec(ir["quantity"]),
                unit_price=self._dec(ir["unit_price"]),
                total_price=self._dec(ir["total_price"]),
                vat_rate=self._dec(ir["vat_rate"]),
                vat_amount=self._dec(ir["vat_amount"]) if "vat_amount" in ir.keys() else None,
                category=ReceiptCategory(ir["category"] or "other"),
            )
            for ir in item_rows
        ]

        # vat_splits
        split_rows = self._conn.execute(
            "SELECT * FROM receipt_vat_splits WHERE receipt_id = ? ORDER BY position ASC",
            (row["id"],),
        ).fetchall()
        vat_splits = [
            {
                "position": sr["position"],
                "vat_rate": float(self._dec(sr["vat_rate"])) if sr["vat_rate"] else None,
                "vat_amount": float(self._dec(sr["vat_amount"])) if sr["vat_amount"] else None,
                "net_amount": float(self._dec(sr["net_amount"])) if sr["net_amount"] else None,
            }
            for sr in split_rows
        ]

        receipt = ReceiptData.__new__(ReceiptData)
        receipt.raw_text = row["raw_text"] or ""
        receipt.vat_splits = vat_splits
        receipt.id = row["id"]
        receipt.receipt_type = ReceiptType(row["receipt_type"] or "purchase")
        receipt.counterparty = cp
        receipt.receipt_number = row["receipt_number"]
        receipt.receipt_date = receipt_date
        receipt.total_amount = self._dec(row["total_amount"])
        receipt.vat_percentage = self._dec(row["vat_percentage"])
        receipt.vat_amount = self._dec(row["vat_amount"])
        receipt.currency = (
            row["currency"] if "currency" in row.keys() and row["currency"] else "EUR"
        )
        receipt.category = ReceiptCategory(row["category"] or "other")
        receipt.subcategory = row["subcategory"] if "subcategory" in row.keys() else None
        receipt.description = (
            row["description"] if "description" in row.keys() and row["description"] else ""
        )
        receipt.items = items
        # private_use_share — default to 0 for receipts created before this column existed
        _pus = row["private_use_share"] if "private_use_share" in row.keys() else None
        receipt.private_use_share = self._dec(_pus) or Decimal("0")
        # validation_warnings — default to [] for receipts created before this column existed
        _vw_raw = row["validation_warnings"] if "validation_warnings" in row.keys() else None
        receipt.validation_warnings = json.loads(_vw_raw) if _vw_raw else []
        # created_at — when the receipt was first stored (UTC ISO-8601 string)
        receipt.created_at = row["created_at"] if "created_at" in row.keys() else None
        # einfuhr_vat — Einfuhrumsatzsteuer (§ 15 Abs. 1 Satz 1 Nr. 2 UStG)
        receipt.einfuhr_vat = self._dec(row["einfuhr_vat"]) if "einfuhr_vat" in row.keys() else None
        return receipt

    # ------------------------------------------------------------------
    # Project metadata (key/value store)
    # ------------------------------------------------------------------

    def get_metadata(self, key: str) -> dict | None:
        """Return the parsed JSON value for *key*, or None if not set."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM project_metadata WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, KeyError):
            return None

    def set_metadata(self, key: str, value: dict) -> None:
        """Upsert *key* with the JSON-serialised *value*."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO project_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), now),
            )
            self._conn.commit()

    def delete_metadata(self, key: str) -> None:
        """Remove *key* from project_metadata (no-op if absent)."""
        with self._lock:
            self._conn.execute("DELETE FROM project_metadata WHERE key = ?", (key,))
            self._conn.commit()
