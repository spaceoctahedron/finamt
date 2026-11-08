"""
tests/test_private_use.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the private-use / double-entry posting feature.

Design under test
-----------------
* ``ReceiptData.private_use_share`` (0–1)
* ``ReceiptData.generate_postings()``
* ``ReceiptData.business_net`` / ``.business_vat``
* ``ReceiptData.validate()`` — rejects out-of-range share
* DB: ``private_use_share`` column persisted & round-tripped
* DB: ``postings`` table created & used; regenerated on update
* DB: ``get_postings()`` / ``list_all_postings()``
* UStVA: only business portion of input VAT is reported
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from finamt.models import (
    Posting,
    PostingDirection,
    PostingType,
    ReceiptCategory,
    ReceiptData,
    ReceiptType,
)
from finamt.storage.sqlite import SQLiteRepository
from finamt.tax.ustva import generate_ustva

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_purchase(
    *,
    raw_text: str | None = None,
    total_amount: str = "119.00",
    vat_amount: str = "19.00",
    private_use_share: str = "0",
    receipt_date: datetime = datetime(2024, 3, 15),
) -> ReceiptData:
    r = ReceiptData(
        raw_text=raw_text or f"receipt {uuid.uuid4()}",
        receipt_type=ReceiptType("purchase"),
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount),
        vat_percentage=Decimal("19"),
        vat_amount=Decimal(vat_amount),
        category=ReceiptCategory("material"),
        private_use_share=Decimal(private_use_share),
    )
    return r


def _make_sale(
    *,
    raw_text: str | None = None,
    total_amount: str = "119.00",
    vat_amount: str = "19.00",
    receipt_date: datetime = datetime(2024, 3, 15),
) -> ReceiptData:
    r = ReceiptData(
        raw_text=raw_text or f"sale {uuid.uuid4()}",
        receipt_type=ReceiptType("sale"),
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount),
        vat_percentage=Decimal("19"),
        vat_amount=Decimal(vat_amount),
        category=ReceiptCategory("revenue"),
    )
    return r


@pytest.fixture
def repo(tmp_path) -> SQLiteRepository:
    db = SQLiteRepository(db_path=tmp_path / "test_private.db")
    yield db
    db.close()


# ---------------------------------------------------------------------------
# PostingType / PostingDirection validation
# ---------------------------------------------------------------------------


class TestPostingClasses:
    def test_valid_direction_debit(self):
        assert str(PostingDirection("debit")) == "debit"

    def test_valid_direction_credit(self):
        assert str(PostingDirection("credit")) == "credit"

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            PostingDirection("unknown")

    def test_valid_posting_types(self):
        for t in (
            "expense",
            "input_vat",
            "accounts_payable",
            "revenue",
            "output_vat",
            "accounts_receivable",
            "private_withdrawal",
        ):
            assert str(PostingType(t)) == t

    def test_invalid_posting_type_raises(self):
        with pytest.raises(ValueError):
            PostingType("flying_cars")

    def test_posting_to_dict(self):
        p = Posting(
            receipt_id="abc",
            posting_type=PostingType("expense"),
            direction=PostingDirection("debit"),
            amount=Decimal("100.00"),
            description="Test",
        )
        d = p.to_dict()
        assert d["receipt_id"] == "abc"
        assert d["posting_type"] == "expense"
        assert d["direction"] == "debit"
        assert d["amount"] == 100.0
        assert d["description"] == "Test"


# ---------------------------------------------------------------------------
# ReceiptData.private_use_share defaults & validation
# ---------------------------------------------------------------------------


class TestPrivateUseShare:
    def test_default_zero(self):
        r = _make_purchase()
        assert r.private_use_share == Decimal("0")

    def test_explicit_share(self):
        r = _make_purchase(private_use_share="0.4")
        assert r.private_use_share == Decimal("0.4")

    def test_validate_zero_share(self):
        assert _make_purchase(private_use_share="0").validate() is True

    def test_validate_full_private(self):
        assert _make_purchase(private_use_share="1").validate() is True

    def test_validate_mid_share(self):
        assert _make_purchase(private_use_share="0.5").validate() is True

    def test_validate_over_one_fails(self):
        r = _make_purchase(private_use_share="1.01")
        assert r.validate() is False

    def test_validate_negative_fails(self):
        r = _make_purchase(private_use_share="-0.1")
        assert r.validate() is False

    def test_business_net_full_business(self):
        # no private share → business_net == net_amount
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0")
        assert r.business_net == r.net_amount

    def test_business_net_partial_private(self):
        # net = 100, private_use_share = 0.4 → business_net = 60
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0.4")
        assert r.business_net == Decimal("60.00")

    def test_business_vat_full_business(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0")
        assert r.business_vat == r.vat_amount

    def test_business_vat_partial_private(self):
        # vat = 19, private_use_share = 0.4 → business_vat = 19 * 0.6 = 11.40
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0.4")
        assert r.business_vat == Decimal("11.40")

    def test_to_dict_contains_private_use_share(self):
        r = _make_purchase(private_use_share="0.3")
        d = r.to_dict()
        assert "private_use_share" in d
        assert d["private_use_share"] == pytest.approx(0.3)

    def test_to_dict_contains_business_fields(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0.4")
        d = r.to_dict()
        assert d["business_net"] == pytest.approx(60.0)
        assert d["business_vat"] == pytest.approx(11.40)


# ---------------------------------------------------------------------------
# ReceiptData.generate_postings — no private use
# ---------------------------------------------------------------------------


class TestGeneratePostingsNone:
    def test_purchase_three_postings(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        posts = r.generate_postings()
        assert len(posts) == 3

    def test_purchase_balanced(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        posts = r.generate_postings()
        debits = sum(p.amount for p in posts if str(p.direction) == "debit")
        credits = sum(p.amount for p in posts if str(p.direction) == "credit")
        assert debits == credits

    def test_purchase_debit_expense(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        posts = r.generate_postings()
        expense_debits = [
            p for p in posts if str(p.posting_type) == "expense" and str(p.direction) == "debit"
        ]
        assert len(expense_debits) == 1
        assert expense_debits[0].amount == Decimal("100.00")

    def test_purchase_debit_input_vat(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        posts = r.generate_postings()
        vat_debits = [
            p for p in posts if str(p.posting_type) == "input_vat" and str(p.direction) == "debit"
        ]
        assert len(vat_debits) == 1
        assert vat_debits[0].amount == Decimal("19.00")

    def test_purchase_credit_accounts_payable(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        posts = r.generate_postings()
        ap = [p for p in posts if str(p.posting_type) == "accounts_payable"]
        assert len(ap) == 1
        assert str(ap[0].direction) == "credit"
        assert ap[0].amount == Decimal("119.00")

    def test_sale_three_postings(self):
        r = _make_sale(total_amount="238.00", vat_amount="38.00")
        posts = r.generate_postings()
        assert len(posts) == 3

    def test_sale_balanced(self):
        r = _make_sale(total_amount="238.00", vat_amount="38.00")
        posts = r.generate_postings()
        debits = sum(p.amount for p in posts if str(p.direction) == "debit")
        credits = sum(p.amount for p in posts if str(p.direction) == "credit")
        assert debits == credits

    def test_sale_debit_accounts_receivable(self):
        r = _make_sale(total_amount="238.00", vat_amount="38.00")
        posts = r.generate_postings()
        ar = [p for p in posts if str(p.posting_type) == "accounts_receivable"]
        assert len(ar) == 1
        assert str(ar[0].direction) == "debit"
        assert ar[0].amount == Decimal("238.00")

    def test_sale_credit_revenue(self):
        r = _make_sale(total_amount="238.00", vat_amount="38.00")
        posts = r.generate_postings()
        rev = [p for p in posts if str(p.posting_type) == "revenue"]
        assert len(rev) == 1
        assert str(rev[0].direction) == "credit"
        assert rev[0].amount == Decimal("200.00")

    def test_sale_credit_output_vat(self):
        r = _make_sale(total_amount="238.00", vat_amount="38.00")
        posts = r.generate_postings()
        ov = [p for p in posts if str(p.posting_type) == "output_vat"]
        assert len(ov) == 1
        assert str(ov[0].direction) == "credit"
        assert ov[0].amount == Decimal("38.00")

    def test_empty_postings_when_amounts_missing(self):
        r = ReceiptData(raw_text="test")
        assert r.generate_postings() == []


# ---------------------------------------------------------------------------
# ReceiptData.generate_postings — with private use
# ---------------------------------------------------------------------------


class TestGeneratePostingsWithPrivateUse:
    """
    Fixture: net=100, vat=19, gross=119, private_use_share=0.40
    Expected private amounts:
        priv_net   = 100 * 0.40 = 40.00
        priv_vat   =  19 * 0.40 =  7.60
        priv_gross = 119 * 0.40 = 47.60
    """

    @pytest.fixture
    def receipt_40(self):
        return _make_purchase(
            total_amount="119.00",
            vat_amount="19.00",
            private_use_share="0.4",
        )

    def test_six_postings_total(self, receipt_40):
        assert len(receipt_40.generate_postings()) == 6

    def test_balanced(self, receipt_40):
        posts = receipt_40.generate_postings()
        debits = sum(p.amount for p in posts if str(p.direction) == "debit")
        credits = sum(p.amount for p in posts if str(p.direction) == "credit")
        assert debits == credits

    def test_expense_debit_full(self, receipt_40):
        posts = receipt_40.generate_postings()
        debit = next(
            p for p in posts if str(p.posting_type) == "expense" and str(p.direction) == "debit"
        )
        assert debit.amount == Decimal("100.00")

    def test_expense_credit_private(self, receipt_40):
        posts = receipt_40.generate_postings()
        credit = next(
            p for p in posts if str(p.posting_type) == "expense" and str(p.direction) == "credit"
        )
        assert credit.amount == Decimal("40.00")

    def test_input_vat_debit_full(self, receipt_40):
        posts = receipt_40.generate_postings()
        debit = next(
            p for p in posts if str(p.posting_type) == "input_vat" and str(p.direction) == "debit"
        )
        assert debit.amount == Decimal("19.00")

    def test_input_vat_credit_private(self, receipt_40):
        posts = receipt_40.generate_postings()
        credit = next(
            p for p in posts if str(p.posting_type) == "input_vat" and str(p.direction) == "credit"
        )
        assert credit.amount == Decimal("7.60")

    def test_private_withdrawal_debit(self, receipt_40):
        posts = receipt_40.generate_postings()
        pw = next(p for p in posts if str(p.posting_type) == "private_withdrawal")
        assert str(pw.direction) == "debit"
        assert pw.amount == Decimal("47.60")

    def test_net_expense_after_correction(self, receipt_40):
        """Effective business expense = debit − credit on 'expense' = 60.00."""
        posts = receipt_40.generate_postings()
        expense_net = sum(
            p.amount if str(p.direction) == "debit" else -p.amount
            for p in posts
            if str(p.posting_type) == "expense"
        )
        assert expense_net == Decimal("60.00")

    def test_net_input_vat_after_correction(self, receipt_40):
        """Effective reclaimable VAT = 19 - 7.60 = 11.40."""
        posts = receipt_40.generate_postings()
        vat_net = sum(
            p.amount if str(p.direction) == "debit" else -p.amount
            for p in posts
            if str(p.posting_type) == "input_vat"
        )
        assert vat_net == Decimal("11.40")

    def test_fully_private_no_business_expense(self):
        """private_use_share=1 → effective business expense = 0."""
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="1")
        posts = r.generate_postings()
        expense_net = sum(
            p.amount if str(p.direction) == "debit" else -p.amount
            for p in posts
            if str(p.posting_type) == "expense"
        )
        assert expense_net == Decimal("0.00")

    def test_receipt_id_on_all_postings(self, receipt_40):
        posts = receipt_40.generate_postings()
        for p in posts:
            assert p.receipt_id == receipt_40.id


# ---------------------------------------------------------------------------
# SQLiteRepository — private_use_share persistence
# ---------------------------------------------------------------------------


class TestDBPrivateUsePersistence:
    def test_save_and_round_trip_zero(self, repo):
        r = _make_purchase(private_use_share="0")
        repo.save(r)
        loaded = repo.get(r.id)
        assert loaded.private_use_share == Decimal("0")

    def test_save_and_round_trip_nonzero(self, repo):
        r = _make_purchase(private_use_share="0.4")
        repo.save(r)
        loaded = repo.get(r.id)
        assert loaded.private_use_share == Decimal("0.4")

    def test_update_private_use_share(self, repo):
        r = _make_purchase(private_use_share="0")
        repo.save(r)
        repo.update(r.id, {"private_use_share": "0.5"})
        loaded = repo.get(r.id)
        assert loaded.private_use_share == Decimal("0.5")

    def test_update_clamps_over_one(self, repo):
        r = _make_purchase(private_use_share="0")
        repo.save(r)
        repo.update(r.id, {"private_use_share": "1.5"})
        loaded = repo.get(r.id)
        assert loaded.private_use_share == Decimal("1")

    def test_update_clamps_negative(self, repo):
        r = _make_purchase(private_use_share="0.2")
        repo.save(r)
        repo.update(r.id, {"private_use_share": "-0.1"})
        loaded = repo.get(r.id)
        assert loaded.private_use_share == Decimal("0")


# ---------------------------------------------------------------------------
# SQLiteRepository — postings table
# ---------------------------------------------------------------------------


class TestDBPostings:
    def test_postings_created_on_save(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        repo.save(r)
        posts = repo.get_postings(r.id)
        assert len(posts) == 3

    def test_postings_six_with_private_use(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0.4")
        repo.save(r)
        posts = repo.get_postings(r.id)
        assert len(posts) == 6

    def test_postings_contain_posting_objects(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        repo.save(r)
        posts = repo.get_postings(r.id)
        for p in posts:
            assert isinstance(p, Posting)

    def test_postings_balanced(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0.4")
        repo.save(r)
        posts = repo.get_postings(r.id)
        debits = sum(p.amount for p in posts if str(p.direction) == "debit")
        credits = sum(p.amount for p in posts if str(p.direction) == "credit")
        assert debits == credits

    def test_postings_regenerated_on_private_use_update(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        repo.save(r)
        assert len(repo.get_postings(r.id)) == 3  # no private use
        repo.update(r.id, {"private_use_share": "0.4"})
        posts = repo.get_postings(r.id)
        assert len(posts) == 6  # now includes correction postings

    def test_postings_regenerated_on_amount_update(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        repo.save(r)
        repo.update(r.id, {"total_amount": Decimal("238.00"), "vat_amount": Decimal("38.00")})
        posts = repo.get_postings(r.id)
        ap = next(p for p in posts if str(p.posting_type) == "accounts_payable")
        assert ap.amount == Decimal("238.00")

    def test_postings_deleted_with_receipt(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        repo.save(r)
        rid = r.id
        repo.delete(rid)
        posts = repo.get_postings(rid)
        assert posts == []

    def test_list_all_postings(self, repo):
        r1 = _make_purchase(total_amount="119.00", vat_amount="19.00")
        r2 = _make_sale(total_amount="238.00", vat_amount="38.00")
        repo.save(r1)
        repo.save(r2)
        all_posts = repo.list_all_postings()
        # r1: 3 postings, r2: 3 postings
        assert len(all_posts) >= 6

    def test_list_all_postings_contains_receipt_metadata(self, repo):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00")
        repo.save(r)
        all_posts = repo.list_all_postings()
        assert all(
            {"receipt_id", "posting_type", "direction", "amount"} <= d.keys() for d in all_posts
        )

    def test_get_postings_empty_for_unknown_id(self, repo):
        assert repo.get_postings("nonexistent") == []


# ---------------------------------------------------------------------------
# UStVA — private use reduces reclaimable input VAT
# ---------------------------------------------------------------------------


class TestUStVAPrivateUse:
    def test_full_business_full_input_vat(self):
        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0")
        report = generate_ustva([r], date(2024, 1, 1), date(2024, 12, 31))
        assert report.total_input_vat == Decimal("19.00")

    def test_40pct_private_reduces_input_vat(self):
        """40 % private → only 60 % (=11.40) reclaimable."""
        from datetime import date

        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0.4")
        report = generate_ustva([r], date(2024, 1, 1), date(2024, 12, 31))
        assert report.total_input_vat == Decimal("11.40")

    def test_40pct_private_reduces_purchase_net(self):
        from datetime import date

        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="0.4")
        report = generate_ustva([r], date(2024, 1, 1), date(2024, 12, 31))
        assert report.total_purchase_net == Decimal("60.00")

    def test_fully_private_zero_input_vat(self):
        from datetime import date

        r = _make_purchase(total_amount="119.00", vat_amount="19.00", private_use_share="1")
        report = generate_ustva([r], date(2024, 1, 1), date(2024, 12, 31))
        assert report.total_input_vat == Decimal("0.00")

    def test_sale_output_vat_unaffected_by_private_share(self):
        """Sales output VAT is never reduced by private_use_share."""
        from datetime import date

        r = _make_sale(total_amount="119.00", vat_amount="19.00")
        report = generate_ustva([r], date(2024, 1, 1), date(2024, 12, 31))
        assert report.total_output_vat == Decimal("19.00")

    def test_mixed_receipts_ustva(self):
        """Two purchases with different private shares combine correctly."""
        from datetime import date

        # net=100, vat=19, private=0   → business_vat=19.00
        r1 = _make_purchase(
            total_amount="119.00",
            vat_amount="19.00",
            private_use_share="0",
            receipt_date=datetime(2024, 6, 1),
        )
        # net=200, vat=38, private=0.5 → business_vat=19.00
        r2 = _make_purchase(
            total_amount="238.00",
            vat_amount="38.00",
            private_use_share="0.5",
            receipt_date=datetime(2024, 6, 1),
        )
        report = generate_ustva([r1, r2], date(2024, 1, 1), date(2024, 12, 31))
        assert report.total_input_vat == Decimal("38.00")  # 19 + 19

    def test_ustva_skips_zero_vat(self):
        from datetime import date

        r = _make_purchase(total_amount="100.00", vat_amount="19.00", private_use_share="0")
        r_no_vat = ReceiptData(
            raw_text=f"no-vat {uuid.uuid4()}",
            receipt_type=ReceiptType("purchase"),
            receipt_date=datetime(2024, 6, 1),
            total_amount=Decimal("50.00"),
            vat_amount=None,
        )
        report = generate_ustva([r, r_no_vat], date(2024, 1, 1), date(2024, 12, 31))
        assert report.skipped_count == 1
