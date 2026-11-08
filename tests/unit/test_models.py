"""
tests/test_models.py
~~~~~~~~~~~~~~~~~~~~
Tests for finamt.models — ReceiptCategory, ReceiptItem, ReceiptData,
ExtractionResult, including validation, serialisation and derived properties.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest

from finamt.agents.prompts import RECEIPT_CATEGORIES
from finamt.models import (
    ExtractionResult,
    ReceiptCategory,
    ReceiptData,
    ReceiptItem,
)


class TestReceiptCategory:
    def test_valid_category_accepted(self):
        for cat in RECEIPT_CATEGORIES:
            assert str(ReceiptCategory(cat)) == cat

    def test_invalid_falls_back_to_other(self):
        assert str(ReceiptCategory("flying_cars")) == "other"

    def test_empty_string_falls_back_to_other(self):
        assert str(ReceiptCategory("")) == "other"

    def test_whitespace_normalised(self):
        cat = ReceiptCategory("  software  ")
        assert str(cat) == "software"

    def test_uppercase_normalised(self):
        assert str(ReceiptCategory("TRAVEL")) == "travel"

    def test_is_str_subclass(self):
        cat = ReceiptCategory("travel")
        assert isinstance(cat, str)

    def test_factory_other(self):
        cat = ReceiptCategory.other()
        assert str(cat) == "other"

    def test_valid_frozenset(self):
        assert ReceiptCategory.VALID == frozenset(RECEIPT_CATEGORIES)


class TestReceiptItem:
    def test_minimal_construction(self):
        item = ReceiptItem(description="Laptop")
        assert item.description == "Laptop"
        assert item.total_price is None
        assert str(item.category) == "other"

    def test_to_dict_structure(self, sample_item):
        d = sample_item.to_dict()
        assert set(d.keys()) == {
            "description",
            "position",
            "quantity",
            "unit_price",
            "total_price",
            "category",
            "vat_rate",
            "vat_amount",
        }

    def test_to_dict_decimal_as_float(self, sample_item):
        d = sample_item.to_dict()
        assert isinstance(d["total_price"], float)
        assert isinstance(d["quantity"], float)

    def test_to_dict_none_values(self):
        item = ReceiptItem(description="X")
        d = item.to_dict()
        assert d["quantity"] is None
        assert d["unit_price"] is None
        assert d["total_price"] is None
        assert d["vat_rate"] is None

    def test_category_serialised_as_string(self, sample_item):
        d = sample_item.to_dict()
        assert isinstance(d["category"], str)


class TestReceiptData:
    def test_net_amount_computed_from_rate(self, sample_receipt):
        # Correct gross-to-net: NETTO = BRUTTO ÷ (1 + MwSt./100)
        # sample_receipt: total=25.90, vat_pct=19 → 25.90 / 1.19 = 21.7647... → 21.76
        assert sample_receipt.net_amount == Decimal("21.76")

    def test_net_amount_fallback_to_stored_vat(self):
        # When vat_percentage is absent, fall back to total − stored vat_amount
        r = ReceiptData(total_amount=Decimal("25.90"), vat_amount=Decimal("4.13"))
        assert r.net_amount == Decimal("21.77")  # 25.90 − 4.13

    def test_net_amount_none_when_total_missing(self):
        r = ReceiptData(vat_amount=Decimal("1.00"))
        assert r.net_amount is None

    def test_net_amount_none_when_vat_missing(self):
        r = ReceiptData(total_amount=Decimal("10.00"))
        assert r.net_amount is None

    def test_validate_passes_valid_receipt(self, sample_receipt):
        assert sample_receipt.validate() is True

    def test_validate_warns_on_future_date(self):
        # Future dates produce a warning but the receipt is NOT blocked — it's
        # saved and surfaced in the UI so the user can correct or delete it.
        r = ReceiptData(receipt_date=datetime(2099, 1, 1))
        result = r.validate()
        assert result is False
        assert len(r.validation_warnings) == 1
        assert "Future date" in r.validation_warnings[0]

    def test_validate_populates_warnings_list(self):
        r = ReceiptData(total_amount=Decimal("-5.00"))
        r.validate()
        assert len(r.validation_warnings) == 1
        assert "positive" in r.validation_warnings[0]

    def test_validate_clears_old_warnings_on_rerun(self):
        r = ReceiptData(total_amount=Decimal("-1"))
        r.validate()
        assert len(r.validation_warnings) == 1
        r.total_amount = Decimal("10")
        r.validate()
        assert r.validation_warnings == []

    def test_validate_rejects_zero_total(self):
        r = ReceiptData(total_amount=Decimal("0"))
        assert r.validate() is False

    def test_validate_rejects_negative_total(self):
        r = ReceiptData(total_amount=Decimal("-5.00"))
        assert r.validate() is False

    def test_validate_rejects_vat_over_100_percent(self):
        r = ReceiptData(vat_percentage=Decimal("150"))
        assert r.validate() is False

    def test_validate_rejects_vat_exceeding_total(self):
        r = ReceiptData(total_amount=Decimal("10.00"), vat_amount=Decimal("15.00"))
        assert r.validate() is False

    def test_validate_passes_empty_receipt(self):
        assert ReceiptData().validate() is True

    def test_to_dict_keys(self, sample_receipt):
        d = sample_receipt.to_dict()
        assert "vendor" in d
        assert "total_amount" in d
        assert "vat_amount" in d
        assert "net_amount" in d
        assert "receipt_date" in d
        assert "items" in d
        # Old field names must NOT appear
        assert "company" not in d
        assert "amount_euro" not in d
        assert "vat_euro" not in d
        assert "confidence_score" not in d

    def test_to_dict_date_as_iso_string(self, sample_receipt):
        d = sample_receipt.to_dict()
        assert d["receipt_date"] == "2024-03-15"

    def test_to_dict_none_date(self):
        d = ReceiptData().to_dict()
        assert d["receipt_date"] is None

    def test_to_dict_items_list(self, sample_receipt):
        d = sample_receipt.to_dict()
        assert isinstance(d["items"], list)
        assert len(d["items"]) == 1

    def test_to_json_valid(self, sample_receipt):
        raw = sample_receipt.to_json()
        parsed = json.loads(raw)
        assert parsed["vendor"] == "Bürobedarf GmbH"

    def test_to_json_ensure_ascii_false(self, sample_receipt):
        raw = sample_receipt.to_json()
        assert "Bürobedarf" in raw  # not escaped to \uXXXX


class TestExtractionResult:
    def test_success_result(self, successful_result):
        assert successful_result.success is True
        assert successful_result.data is not None
        assert successful_result.error_message is None

    def test_failed_result(self, failed_result):
        assert failed_result.success is False
        assert failed_result.data is None
        assert failed_result.error_message is not None

    def test_to_dict_success(self, successful_result):
        d = successful_result.to_dict()
        assert d["success"] is True
        assert d["data"] is not None
        assert d["error_message"] is None
        assert d["processing_time"] == pytest.approx(1.234, rel=1e-3)

    def test_to_dict_failure(self, failed_result):
        d = failed_result.to_dict()
        assert d["success"] is False
        assert d["data"] is None
        assert isinstance(d["error_message"], str)

    def test_processing_time_rounded(self):
        r = ExtractionResult(success=True, processing_time=1.23456789)
        assert r.to_dict()["processing_time"] == pytest.approx(1.235, rel=1e-3)
