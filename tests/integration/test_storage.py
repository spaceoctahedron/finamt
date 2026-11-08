"""
tests/test_storage.py
~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.storage.sqlite — SQLiteRepository.
All tests use tmp_path, never touching ~/.finamt/finamt.db.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from finamt.models import (
    Address,
    Counterparty,
    ReceiptCategory,
    ReceiptData,
    ReceiptItem,
    ReceiptType,
)
from finamt.storage.base import ReceiptRepository
from finamt.storage.sqlite import SQLiteRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path) -> SQLiteRepository:
    db = SQLiteRepository(db_path=tmp_path / "test.db")
    yield db
    db.close()


def _make_counterparty(name: str = "Test GmbH") -> Counterparty:
    return Counterparty(
        name=name,
        address=Address(
            street_and_number="Musterstraße 1",
            postcode="10115",
            city="Berlin",
            state="Berlin",
            country="Germany",
        ),
        vat_id=f"DE{abs(hash(name)) % 10**9:09d}",
    )


def _make_receipt(
    *,
    counterparty: Counterparty | None = None,
    receipt_date: datetime | None = datetime(2024, 3, 15),
    total_amount: str | None = "119.00",
    vat_percentage: str | None = "19",
    vat_amount: str | None = "19.00",
    category: str = "software",
    receipt_type: str = "purchase",
    items: list | None = None,
    raw_text: str | None = None,
) -> ReceiptData:
    if counterparty is None:
        counterparty = _make_counterparty()
    # Use unique raw_text per receipt so hash IDs don't collide
    if raw_text is None:
        raw_text = f"Receipt from {counterparty.name} {uuid.uuid4()}"
    return ReceiptData(
        raw_text=raw_text,
        receipt_type=ReceiptType(receipt_type),
        counterparty=counterparty,
        receipt_number="RE-2024-001",
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount) if total_amount else None,
        vat_percentage=Decimal(vat_percentage) if vat_percentage else None,
        vat_amount=Decimal(vat_amount) if vat_amount else None,
        category=ReceiptCategory(category),
        items=items or [],
    )


def _make_item(
    description: str = "Python-Lizenz",
    total_price: str = "119.00",
    vat_rate: str = "19.0",
) -> ReceiptItem:
    return ReceiptItem(
        description=description,
        total_price=Decimal(total_price),
        quantity=Decimal("1"),
        unit_price=Decimal(total_price),
        category=ReceiptCategory("software"),
        vat_rate=Decimal(vat_rate),
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_is_receipt_repository(self, repo):
        assert isinstance(repo, ReceiptRepository)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager_closes_connection(self, tmp_path):
        with SQLiteRepository(db_path=tmp_path / "ctx.db") as repo:
            r = _make_receipt()
            repo.save(r)
        with pytest.raises(sqlite3.ProgrammingError):
            repo.get(r.id)


# ---------------------------------------------------------------------------
# save / get
# ---------------------------------------------------------------------------


class TestSaveGet:
    def test_save_and_retrieve(self, repo):
        r = _make_receipt()
        repo.save(r)
        found = repo.get(r.id)
        assert found is not None
        assert found.id == r.id
        assert found.counterparty.name == "Test GmbH"

    def test_get_returns_none_for_unknown_id(self, repo):
        assert repo.get("a" * 64) is None

    def test_decimal_precision_preserved(self, repo):
        r = _make_receipt(total_amount="1234.56", vat_amount="197.32")
        repo.save(r)
        found = repo.get(r.id)
        assert found.total_amount == Decimal("1234.56")
        assert found.vat_amount == Decimal("197.32")

    def test_none_fields_round_trip(self, repo):
        r = _make_receipt(
            total_amount=None,
            vat_percentage=None,
            vat_amount=None,
            receipt_date=None,
        )
        repo.save(r)
        found = repo.get(r.id)
        assert found.total_amount is None
        assert found.vat_percentage is None
        assert found.vat_amount is None
        assert found.receipt_date is None

    def test_category_restored_as_receipt_category(self, repo):
        r = _make_receipt(category="travel")
        repo.save(r)
        found = repo.get(r.id)
        assert isinstance(found.category, ReceiptCategory)
        assert str(found.category) == "travel"

    def test_invalid_category_normalised_to_other(self, repo):
        r = _make_receipt(category="flying_cars")
        assert str(r.category) == "other"
        repo.save(r)
        assert str(repo.get(r.id).category) == "other"

    def test_upsert_replaces_existing(self, repo):
        r = _make_receipt()
        repo.save(r)
        # save returns False (duplicate)
        result = repo.save(r)
        assert result is False
        assert len(list(repo.list_all())) == 1

    def test_receipt_date_round_trips_as_datetime(self, repo):
        r = _make_receipt(receipt_date=datetime(2024, 6, 30))
        repo.save(r)
        found = repo.get(r.id)
        assert isinstance(found.receipt_date, datetime)
        assert found.receipt_date == datetime(2024, 6, 30)

    def test_vendor_address_and_receipt_number_preserved(self, repo):
        r = _make_receipt()
        repo.save(r)
        found = repo.get(r.id)
        assert found.counterparty.name == "Test GmbH"
        assert found.receipt_number == "RE-2024-001"

    def test_receipt_type_round_trips(self, repo):
        r = _make_receipt(receipt_type="sale")
        repo.save(r)
        assert str(repo.get(r.id).receipt_type) == "sale"

    def test_counterparty_address_round_trips(self, repo):
        r = _make_receipt()
        repo.save(r)
        found = repo.get(r.id)
        assert found.counterparty.address.city == "Berlin"
        assert found.counterparty.address.postcode == "10115"


# ---------------------------------------------------------------------------
# Counterparty deduplication
# ---------------------------------------------------------------------------


class TestCounterpartyDedup:
    def test_same_name_reuses_counterparty(self, repo):
        """Same name → second receipt reuses existing counterparty row, no error.
        (VAT-ID is NOT used as a match key — name is the sole deduplication key.)
        """
        cp = _make_counterparty("Vendor A")
        r1 = _make_receipt(counterparty=cp)
        r2 = _make_receipt(counterparty=cp)
        repo.save(r1)
        repo.save(r2)  # must NOT raise — counterparty is reused
        f1 = repo.get(r1.id)
        f2 = repo.get(r2.id)
        assert f1.counterparty.id == f2.counterparty.id

    def test_same_vat_id_different_names_creates_new_counterparty(self, repo):
        """Same VAT ID but different names → two separate counterparty rows.

        VAT-ID matching was removed to prevent agent OCR errors (e.g. the
        taxpayer's own VAT ID being attached to a supplier) from silently
        merging unrelated counterparties.  Duplicate VAT IDs are highlighted
        in the UI for the user to resolve manually.
        """
        shared_vat = "DE123456789"
        cp1 = Counterparty(name="Deutsche Bank AG", vat_id=shared_vat)
        cp2 = Counterparty(name="Deutsche Bahn AG", vat_id=shared_vat)
        r1 = _make_receipt(counterparty=cp1)
        r2 = _make_receipt(counterparty=cp2)
        repo.save(r1)
        repo.save(r2)
        f1 = repo.get(r1.id)
        f2 = repo.get(r2.id)
        # Must be two distinct counterparty rows — not merged by VAT ID
        assert f1.counterparty.id != f2.counterparty.id
        assert f1.counterparty.name == "Deutsche Bank AG"
        assert f2.counterparty.name == "Deutsche Bahn AG"

    def test_same_name_no_vat_id_reuses_counterparty(self, repo):
        """Same name + no VAT ID → deduplicated on name."""
        cp1 = Counterparty(name="Shared Corp")
        cp2 = Counterparty(name="Shared Corp")
        r1 = _make_receipt(counterparty=cp1)
        r2 = _make_receipt(counterparty=cp2)
        repo.save(r1)
        repo.save(r2)
        f1 = repo.get(r1.id)
        f2 = repo.get(r2.id)
        assert f1.counterparty.id == f2.counterparty.id

    def test_different_vat_id_creates_new_counterparty(self, repo):
        cp1 = Counterparty(name="A", vat_id="DE111111111")
        cp2 = Counterparty(name="B", vat_id="DE222222222")
        r1 = _make_receipt(counterparty=cp1)
        r2 = _make_receipt(counterparty=cp2)
        repo.save(r1)
        repo.save(r2)
        f1 = repo.get(r1.id)
        f2 = repo.get(r2.id)
        assert f1.counterparty.id != f2.counterparty.id


class TestKnownSupplierDefaults:
    def _save(self, repo, name, category, subcategory=None, receipt_type="purchase"):
        r = _make_receipt(
            counterparty=_make_counterparty(name),
            category=category,
            receipt_type=receipt_type,
        )
        r.subcategory = subcategory
        repo.save(r)

    def test_unknown_supplier_returns_empty(self, repo):
        assert repo.get_known_supplier_defaults("Nobody") == {}

    def test_below_threshold_returns_empty(self, repo):
        self._save(repo, "Vodafone", "software", "saas")
        assert repo.get_known_supplier_defaults("Vodafone", min_receipts=2) == {}

    def test_dominant_category_and_subcategory(self, repo):
        self._save(repo, "Vodafone", "software", "saas")
        self._save(repo, "Vodafone", "software", "saas")
        self._save(repo, "Vodafone", "office")
        got = repo.get_known_supplier_defaults("vodafone", receipt_type="purchase")
        assert got["category"] == "software"
        assert got["subcategory"] == "saas"
        assert got["count"] == 2

    def test_other_category_ignored(self, repo):
        self._save(repo, "Acme", "other")
        self._save(repo, "Acme", "other")
        assert repo.get_known_supplier_defaults("Acme") == {}

    def test_receipt_type_filter(self, repo):
        self._save(repo, "Acme", "software", receipt_type="sale")
        self._save(repo, "Acme", "software", receipt_type="sale")
        assert repo.get_known_supplier_defaults("Acme", receipt_type="purchase") == {}


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------


class TestLineItems:
    def test_items_persisted_and_restored(self, repo):
        r = _make_receipt(items=[_make_item()])
        repo.save(r)
        found = repo.get(r.id)
        assert len(found.items) == 1
        assert found.items[0].description == "Python-Lizenz"

    def test_item_decimals_preserved(self, repo):
        r = _make_receipt(items=[_make_item(total_price="119.00", vat_rate="19.0")])
        repo.save(r)
        item = repo.get(r.id).items[0]
        assert item.total_price == Decimal("119.00")
        assert item.vat_rate == Decimal("19.0")

    def test_item_category_restored_as_receipt_category(self, repo):
        r = _make_receipt(items=[_make_item()])
        repo.save(r)
        assert isinstance(repo.get(r.id).items[0].category, ReceiptCategory)

    def test_empty_items_round_trip(self, repo):
        r = _make_receipt(items=[])
        repo.save(r)
        assert repo.get(r.id).items == []

    def test_multiple_items(self, repo):
        items = [_make_item(description=f"Item {i}") for i in range(1, 4)]
        r = _make_receipt(items=items)
        repo.save(r)
        found = repo.get(r.id)
        assert len(found.items) == 3
        assert {i.description for i in found.items} == {"Item 1", "Item 2", "Item 3"}

    def test_item_none_fields_survive_round_trip(self, repo):
        item = ReceiptItem(description="Bare item")
        r = _make_receipt(items=[item])
        repo.save(r)
        restored = repo.get(r.id).items[0]
        assert restored.quantity is None
        assert restored.unit_price is None
        assert restored.vat_rate is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_existing_returns_true(self, repo):
        r = _make_receipt()
        repo.save(r)
        assert repo.delete(r.id) is True
        assert repo.get(r.id) is None

    def test_delete_nonexistent_returns_false(self, repo):
        assert repo.delete("a" * 64) is False

    def test_delete_only_removes_target(self, repo):
        r1 = _make_receipt(counterparty=_make_counterparty("A"))
        r2 = _make_receipt(counterparty=_make_counterparty("B"))
        repo.save(r1)
        repo.save(r2)
        repo.delete(r1.id)
        assert repo.get(r1.id) is None
        assert repo.get(r2.id) is not None


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


class TestListAll:
    def test_empty_repo_returns_empty(self, repo):
        assert list(repo.list_all()) == []

    def test_returns_all_receipts(self, repo):
        for name in ("A GmbH", "B GmbH", "C GmbH"):
            repo.save(_make_receipt(counterparty=_make_counterparty(name)))
        assert len(list(repo.list_all())) == 3

    def test_ordered_by_date_descending(self, repo):
        for month in (1, 3, 2):
            repo.save(_make_receipt(receipt_date=datetime(2024, month, 1)))
        dates = [r.receipt_date for r in repo.list_all()]
        assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# find_by_period
# ---------------------------------------------------------------------------


class TestFindByPeriod:
    def test_returns_receipts_in_range(self, repo):
        repo.save(
            _make_receipt(
                counterparty=_make_counterparty("Jan"), receipt_date=datetime(2024, 1, 15)
            )
        )
        repo.save(
            _make_receipt(
                counterparty=_make_counterparty("Mar"), receipt_date=datetime(2024, 3, 10)
            )
        )
        repo.save(
            _make_receipt(
                counterparty=_make_counterparty("Dec"), receipt_date=datetime(2024, 12, 1)
            )
        )
        result = list(repo.find_by_period(date(2024, 1, 1), date(2024, 3, 31)))
        assert {r.counterparty.name for r in result} == {"Jan", "Mar"}

    def test_inclusive_start_and_end(self, repo):
        repo.save(_make_receipt(receipt_date=datetime(2024, 1, 1)))
        repo.save(_make_receipt(receipt_date=datetime(2024, 3, 31)))
        result = list(repo.find_by_period(date(2024, 1, 1), date(2024, 3, 31)))
        assert len(result) == 2

    def test_excludes_receipts_without_date(self, repo):
        r = _make_receipt(counterparty=_make_counterparty("NoDate"), receipt_date=None)
        repo.save(r)
        result = list(repo.find_by_period(date(2024, 1, 1), date(2024, 12, 31)))
        assert all(x.counterparty.name != "NoDate" for x in result)

    def test_empty_range(self, repo):
        repo.save(_make_receipt(receipt_date=datetime(2024, 6, 1)))
        assert list(repo.find_by_period(date(2025, 1, 1), date(2025, 12, 31))) == []

    def test_accepts_datetime_bounds_without_type_error(self, repo):
        """Regression: datetime bounds must not raise TypeError."""
        repo.save(_make_receipt(receipt_date=datetime(2024, 3, 15)))
        result = list(repo.find_by_period(datetime(2024, 1, 1), datetime(2024, 12, 31)))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# find_by_category
# ---------------------------------------------------------------------------


class TestFindByCategory:
    def test_returns_matching_receipts(self, repo):
        repo.save(_make_receipt(counterparty=_make_counterparty("Soft 1"), category="software"))
        repo.save(_make_receipt(counterparty=_make_counterparty("Travel"), category="travel"))
        repo.save(_make_receipt(counterparty=_make_counterparty("Soft 2"), category="software"))
        result = list(repo.find_by_category("software"))
        assert len(result) == 2
        assert all(str(r.category) == "software" for r in result)

    def test_returns_empty_for_absent_category(self, repo):
        repo.save(_make_receipt(category="software"))
        assert list(repo.find_by_category("travel")) == []


# ---------------------------------------------------------------------------
# find_by_type
# ---------------------------------------------------------------------------


class TestFindByType:
    def test_finds_purchases(self, repo):
        repo.save(_make_receipt(receipt_type="purchase"))
        repo.save(_make_receipt(receipt_type="sale"))
        result = list(repo.find_by_type("purchase"))
        assert len(result) == 1
        assert str(result[0].receipt_type) == "purchase"

    def test_finds_sales(self, repo):
        repo.save(_make_receipt(receipt_type="sale"))
        result = list(repo.find_by_type("sale"))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Persistence across re-opens
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_data_survives_close_and_reopen(self, tmp_path):
        db_path = tmp_path / "persist.db"
        r = _make_receipt(counterparty=_make_counterparty("Persistent GmbH"))
        with SQLiteRepository(db_path=db_path) as repo:
            repo.save(r)
        with SQLiteRepository(db_path=db_path) as repo2:
            found = repo2.get(r.id)
        assert found is not None
        assert found.counterparty.name == "Persistent GmbH"

    def test_schema_migration_preserves_data(self, tmp_path):
        db_path = tmp_path / "migrate.db"
        r = _make_receipt()
        with SQLiteRepository(db_path=db_path) as repo:
            repo.save(r)
        with SQLiteRepository(db_path=db_path) as repo2:
            all_receipts = list(repo2.list_all())
        assert len(all_receipts) == 1


# ---------------------------------------------------------------------------
# update (receipt partial update)
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_receipt_amount(self, repo):
        r = _make_receipt(total_amount="100.00")
        repo.save(r)
        result = repo.update(r.id, {"total_amount": "200.00"})
        assert result is True
        found = repo.get(r.id)
        assert found.total_amount == Decimal("200.00")

    def test_update_nonexistent_returns_false(self, repo):
        result = repo.update("a" * 64, {"total_amount": "1.00"})
        assert result is False

    def test_update_counterparty_name(self, repo):
        r = _make_receipt(counterparty=_make_counterparty("Old Name"))
        repo.save(r)
        repo.update(r.id, {"counterparty_name": "New Name"})
        found = repo.get(r.id)
        assert found.counterparty.name == "New Name"

    def test_update_counterparty_address(self, repo):
        r = _make_receipt()
        repo.save(r)
        repo.update(r.id, {"address": {"city": "Hamburg", "postcode": "20095"}})
        found = repo.get(r.id)
        assert found.counterparty.address.city == "Hamburg"
        assert found.counterparty.address.postcode == "20095"

    def test_update_vat_splits(self, repo):
        r = _make_receipt()
        repo.save(r)
        splits = [{"vat_rate": 19, "vat_amount": 9.50, "net_amount": 50.0}]
        repo.update(r.id, {"vat_splits": splits})
        found = repo.get(r.id)
        assert len(found.vat_splits) == 1
        assert found.vat_splits[0]["vat_rate"] == 19.0

    def test_update_items_replaces(self, repo):
        r = _make_receipt(items=[_make_item(description="Old Item")])
        repo.save(r)
        new_items = [
            {
                "description": "New Item",
                "total_price": "10.00",
                "vat_rate": "19",
                "vat_amount": None,
                "unit_price": None,
                "quantity": None,
                "category": "software",
            }
        ]
        repo.update(r.id, {"items": new_items})
        found = repo.get(r.id)
        assert len(found.items) == 1
        assert found.items[0].description == "New Item"

    def test_update_creates_counterparty_when_none(self, repo):
        """If receipt has no counterparty, update with cp fields creates one."""
        r = _make_receipt(counterparty=None)
        r.counterparty = None
        # Save without going through counterparty resolution
        repo.save(r)
        repo.update(r.id, {"counterparty_name": "New Corp", "vat_id": "DE999888777"})
        found = repo.get(r.id)
        assert found.counterparty is not None
        assert found.counterparty.name == "New Corp"

    def test_update_counterparty_verified_flag(self, repo):
        r = _make_receipt()
        repo.save(r)
        cp_id = repo.get(r.id).counterparty.id
        repo.update(r.id, {"counterparty_verified": True})
        cps = repo.list_verified_counterparties()
        assert any(c["id"] == cp_id for c in cps)


# ---------------------------------------------------------------------------
# Counterparty management methods
# ---------------------------------------------------------------------------


class TestCounterpartyManagement:
    def test_list_all_counterparties_empty(self, repo):
        assert repo.list_all_counterparties() == []

    def test_list_all_counterparties_after_save(self, repo):
        for name in ("Alpha", "Beta", "Gamma"):
            repo.save(_make_receipt(counterparty=_make_counterparty(name)))
        cps = repo.list_all_counterparties()
        assert len(cps) == 3
        assert all("id" in cp and "name" in cp and "address" in cp for cp in cps)

    def test_update_counterparty_name(self, repo):
        r = _make_receipt(counterparty=_make_counterparty("Original"))
        repo.save(r)
        cp_id = repo.get(r.id).counterparty.id
        ok = repo.update_counterparty(cp_id, {"name": "Updated"})
        assert ok is True
        cps = repo.list_all_counterparties()
        assert any(cp["name"] == "Updated" for cp in cps)

    def test_update_counterparty_ignores_unknown_fields(self, repo):
        r = _make_receipt(counterparty=_make_counterparty("Safe"))
        repo.save(r)
        cp_id = repo.get(r.id).counterparty.id
        # disallowed field — should be ignored, method returns False (no allowed fields)
        result = repo.update_counterparty(cp_id, {"unknown_field": "value"})
        assert result is False

    def test_update_counterparty_nonexistent_returns_false(self, repo):
        result = repo.update_counterparty("nonexistent-id", {"name": "X"})
        assert result is False

    def test_delete_counterparty(self, repo):
        r = _make_receipt(counterparty=_make_counterparty("ToDelete"))
        repo.save(r)
        cp_id = repo.get(r.id).counterparty.id
        ok = repo.delete_counterparty(cp_id)
        assert ok is True
        cps = repo.list_all_counterparties()
        assert all(cp["id"] != cp_id for cp in cps)

    def test_delete_counterparty_nonexistent_returns_false(self, repo):
        assert repo.delete_counterparty("does-not-exist") is False

    def test_set_counterparty_verified(self, repo):
        r = _make_receipt(counterparty=_make_counterparty("Verifiable"))
        repo.save(r)
        cp_id = repo.get(r.id).counterparty.id
        repo.set_counterparty_verified(cp_id, True)
        verified = repo.list_verified_counterparties()
        assert any(cp["id"] == cp_id for cp in verified)

    def test_set_counterparty_unverified(self, repo):
        r = _make_receipt(counterparty=_make_counterparty("WasVerified"))
        repo.save(r)
        cp_id = repo.get(r.id).counterparty.id
        repo.set_counterparty_verified(cp_id, True)
        repo.set_counterparty_verified(cp_id, False)
        verified = repo.list_verified_counterparties()
        assert all(cp["id"] != cp_id for cp in verified)

    def test_list_verified_counterparties_empty(self, repo):
        repo.save(_make_receipt(counterparty=_make_counterparty("Unverified")))
        assert repo.list_verified_counterparties() == []

    def test_all_counterparty_fields_returned(self, repo):
        cp = Counterparty(
            name="Full Corp",
            vat_id="DE123456789",
            tax_number="123/456/78901",
            address=Address(
                street_and_number="Main St 42",
                postcode="10115",
                city="Berlin",
                state="Berlin",
                country="Germany",
            ),
        )
        repo.save(_make_receipt(counterparty=cp))
        result = repo.list_all_counterparties()[0]
        assert result["vat_id"] == "DE123456789"
        assert result["tax_number"] == "123/456/78901"
        assert result["address"]["street_and_number"] == "Main St 42"
        assert result["address"]["city"] == "Berlin"


# ---------------------------------------------------------------------------
# Startup deduplication sweep
# ---------------------------------------------------------------------------


class TestKnownSupplierVat:
    def _save(self, repo, name, vat):
        repo.save(_make_receipt(counterparty=_make_counterparty(name), vat_percentage=vat))

    def test_unknown_or_too_few(self, repo):
        assert repo.get_known_supplier_vat("Nobody") == {}
        self._save(repo, "Rent GmbH", "0")
        assert repo.get_known_supplier_vat("Rent GmbH") == {}

    def test_zero_rate_is_returned(self, repo):
        self._save(repo, "Rent GmbH", "0")
        self._save(repo, "Rent GmbH", "0")
        got = repo.get_known_supplier_vat("rent gmbh")
        assert got["vat_percentage"] == Decimal("0")
        assert got["count"] == 2

    def test_mixed_rates_not_overridden(self, repo):
        self._save(repo, "Mixed", "7")
        self._save(repo, "Mixed", "19")
        assert repo.get_known_supplier_vat("Mixed") == {}


# ---------------------------------------------------------------------------
# Startup deduplication sweep
# ---------------------------------------------------------------------------


class TestStartupDedup:
    def test_dedup_runs_on_reopen(self, tmp_path):
        """When duplicate counterparties exist on disk, re-opening merges them."""
        import sqlite3 as _sqlite3
        import uuid
        from datetime import datetime, timezone

        db_path = tmp_path / "dedup.db"

        # Bootstrap a DB with the correct schema via the repo
        r = _make_receipt(counterparty=_make_counterparty("DupCorp"))
        with SQLiteRepository(db_path=db_path) as repo:
            repo.save(r)

        # Manually inject a second row with the same name/vat_id
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        existing = conn.execute("SELECT vat_id FROM counterparties LIMIT 1").fetchone()
        vat_id = existing["vat_id"] if existing else "DE999000999"
        conn.execute(
            "INSERT INTO counterparties (id, name, vat_id, created_at, verified) "
            "VALUES (?, 'DupCorp', ?, ?, 0)",
            (str(uuid.uuid4()), vat_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

        # Re-open — dedup sweep runs automatically
        with SQLiteRepository(db_path=db_path) as repo2:
            cps = repo2.list_all_counterparties()
        # Should have collapsed to exactly one counterparty
        assert len(cps) == 1


# ---------------------------------------------------------------------------
# VAT splits round-trip
# ---------------------------------------------------------------------------


class TestVatSplits:
    def test_vat_splits_saved_and_restored(self, repo):
        r = _make_receipt()
        r.vat_splits = [
            {"position": 1, "vat_rate": 19.0, "vat_amount": 19.0, "net_amount": 100.0},
            {"position": 2, "vat_rate": 7.0, "vat_amount": 7.0, "net_amount": 100.0},
        ]
        repo.save(r)
        found = repo.get(r.id)
        assert len(found.vat_splits) == 2
        rates = {s["vat_rate"] for s in found.vat_splits}
        assert rates == {19.0, 7.0}
