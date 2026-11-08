"""
tests/test_utils.py
~~~~~~~~~~~~~~~~~~~~
Tests for finamt.utils — DataExtractor, clean_json_response,
parse_decimal, parse_date.

Covers the bugs that were fixed:
- extract_date YYYY-MM-DD field-order swap
- extract_amounts max() vs keyword-anchored total
- clean_json_response regex corrupting string values
- parse_date locale-dependent %B/%b removed
- CATEGORY_KEYWORDS aligned with RECEIPT_CATEGORIES
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest

from finamt.agents.prompts import RECEIPT_CATEGORIES
from finamt.utils import (
    DataExtractor,
    clean_json_response,
    parse_date,
    parse_decimal,
)

# ---------------------------------------------------------------------------
# extract_company_name
# ---------------------------------------------------------------------------


class TestExtractCompanyName:
    def test_returns_first_meaningful_line(self):
        text = "Müller GmbH\nMusterstraße 1\n10115 Berlin"
        assert DataExtractor.extract_company_name(text) == "Müller GmbH"

    def test_skips_blank_lines(self):
        text = "\n\nMüller GmbH\nstraße"
        assert DataExtractor.extract_company_name(text) == "Müller GmbH"

    def test_skips_lines_starting_with_digit(self):
        text = "12345\nMüller GmbH"
        assert DataExtractor.extract_company_name(text) == "Müller GmbH"

    def test_skips_boilerplate_words(self):
        text = "Kassenbon\nMüller GmbH"
        assert DataExtractor.extract_company_name(text) == "Müller GmbH"

    def test_skips_too_short_lines(self):
        text = "AB\nMüller GmbH"
        assert DataExtractor.extract_company_name(text) == "Müller GmbH"

    def test_returns_none_when_no_candidate(self):
        text = "12345\n67890"
        assert DataExtractor.extract_company_name(text) is None

    def test_only_looks_at_first_eight_lines(self):
        lines = "\n".join(["00000"] * 8 + ["Müller GmbH"])
        assert DataExtractor.extract_company_name(lines) is None


# ---------------------------------------------------------------------------
# extract_date — regression: YYYY-MM-DD was unpacked day/month/year incorrectly
# ---------------------------------------------------------------------------


class TestExtractDate:
    def test_german_format_ddmmyyyy(self):
        result = DataExtractor.extract_date("Datum: 15.03.2024")
        assert result == datetime(2024, 3, 15)

    def test_iso_format_yyyymmdd(self):
        """Regression: was returning datetime(15, 3, 2024) due to order swap."""
        result = DataExtractor.extract_date("Date: 2024-03-15")
        assert result == datetime(2024, 3, 15)

    def test_slash_format(self):
        result = DataExtractor.extract_date("01/06/2023")
        assert result == datetime(2023, 6, 1)

    def test_two_digit_year_below_50(self):
        result = DataExtractor.extract_date("01.01.24")
        assert result is not None
        assert result.year == 2024

    def test_two_digit_year_above_50(self):
        result = DataExtractor.extract_date("01.01.99")
        assert result is not None
        assert result.year == 1999

    def test_german_month_name(self):
        result = DataExtractor.extract_date("15 März 2024")
        assert result == datetime(2024, 3, 15)

    def test_german_month_januar(self):
        result = DataExtractor.extract_date("1 Januar 2023")
        assert result == datetime(2023, 1, 1)

    def test_german_month_dezember(self):
        result = DataExtractor.extract_date("31 Dezember 2023")
        assert result == datetime(2023, 12, 31)

    def test_returns_none_when_no_date(self):
        assert DataExtractor.extract_date("no date here") is None

    def test_returns_none_for_empty_string(self):
        assert DataExtractor.extract_date("") is None


# ---------------------------------------------------------------------------
# extract_amounts — regression: max() was unreliable; keyword anchoring added
# ---------------------------------------------------------------------------


class TestExtractAmounts:
    def test_finds_amount_with_euro_sign(self):
        result = DataExtractor.extract_amounts("Total: 12,99 €")
        assert result["total"] == Decimal("12.99")

    def test_finds_amount_with_eur_prefix(self):
        result = DataExtractor.extract_amounts("EUR 1.234,56")
        assert result["total"] == Decimal("1234.56")

    def test_keyword_anchored_total_preferred(self):
        """
        Regression: without keyword anchoring, max() would pick the highest
        sub-total or line-item price instead of the grand total.
        """
        text = (
            "Druckerpapier  50,00 €\n"
            "Monitor       899,00 €\n"
            "Gesamtbetrag  949,00 €"  # correct total — not the max subtotal
        )
        result = DataExtractor.extract_amounts(text)
        assert result["total"] == Decimal("949.00")

    def test_all_amounts_collected(self):
        text = "A: 10,00 €\nB: 20,00 €\nC: 30,00 €"
        result = DataExtractor.extract_amounts(text)
        assert len(result["all"]) == 3

    def test_empty_text_returns_none(self):
        result = DataExtractor.extract_amounts("no money here")
        assert result["total"] is None
        assert result["all"] == []

    def test_thousands_separator_handled(self):
        result = DataExtractor.extract_amounts("Summe: 1.234,56 €")
        assert result["total"] == Decimal("1234.56")


# ---------------------------------------------------------------------------
# extract_vat_info
# ---------------------------------------------------------------------------


class TestExtractVatInfo:
    def test_extracts_percentage_and_amount(self):
        text = "MwSt. 19% enthaltene Steuer 3,41 €"
        result = DataExtractor.extract_vat_info(text)
        assert result["vat_percentage"] == Decimal("19")
        assert result["vat_amount"] == Decimal("3.41")

    def test_returns_none_when_not_found(self):
        result = DataExtractor.extract_vat_info("no vat info")
        assert result["vat_percentage"] is None
        assert result["vat_amount"] is None

    def test_vat_keyword_case_insensitive(self):
        result = DataExtractor.extract_vat_info("VAT 7% 0,70 €")
        assert result["vat_percentage"] == Decimal("7")


# ---------------------------------------------------------------------------
# extract_items
# ---------------------------------------------------------------------------


class TestExtractItems:
    def test_simple_description_price(self):
        items = DataExtractor.extract_items("Druckerpapier A4  12,99 €")
        assert len(items) == 1
        assert items[0]["description"] == "Druckerpapier A4"
        assert items[0]["total_price"] == pytest.approx(12.99)

    def test_quantity_x_price_pattern(self):
        items = DataExtractor.extract_items("3x Kugelschreiber 2,97 €")
        assert len(items) == 1
        assert items[0]["quantity"] == pytest.approx(3.0)
        # unit_price = total / qty = 2.97 / 3 = 0.99
        assert items[0]["unit_price"] == pytest.approx(0.99)
        assert items[0]["total_price"] == pytest.approx(2.97)

    def test_quantity_X_uppercase(self):
        items = DataExtractor.extract_items("2X Drucker-Toner 49,98 €")
        assert len(items) == 1
        assert items[0]["quantity"] == pytest.approx(2.0)

    def test_empty_text_returns_empty_list(self):
        assert DataExtractor.extract_items("") == []

    def test_category_assigned(self):
        items = DataExtractor.extract_items("Software-Lizenz 99,00 €")
        assert len(items) == 1
        assert items[0]["category"] == "software"

    def test_unrecognised_category_is_other(self):
        # "Zauberstab" used to match travel via "uber" substring — fixed by
        # removing "uber" from keywords (too short, too many false matches).
        items = DataExtractor.extract_items("Glühbirne 4,99 €")
        assert items[0]["category"] == "other"

    def test_item_categories_are_valid(self):
        """All heuristically assigned categories must be valid ReceiptCategory values."""
        text = "\n".join(
            [
                "Software-Lizenz 99,00 €",
                "Hotel Berlin   189,00 €",
                "Druckerpapier   12,99 €",
            ]
        )
        items = DataExtractor.extract_items(text)
        for item in items:
            assert item["category"] in RECEIPT_CATEGORIES


# ---------------------------------------------------------------------------
# _categorize_item
# ---------------------------------------------------------------------------


class TestCategorizeItem:
    @pytest.mark.parametrize(
        "description,expected",
        [
            ("Microsoft 365 Lizenz", "software"),
            ("Flug Berlin München", "travel"),
            ("Hotel Mitte Berlin", "travel"),
            ("Strom Abrechnung", "utilities"),
            ("Python Kurs Online", "education"),
            ("Haftpflicht Police", "insurance"),
            ("Finanzamt Gebühren", "taxes"),
            ("Drucker HP LaserJet", "equipment"),
            ("Völlig unbekannt", "other"),
        ],
    )
    def test_category_mapping(self, description, expected):
        result = DataExtractor._categorize_item(description)
        assert result == expected

    def test_result_always_valid_category(self):
        for description in ["anything", "Druckerpapier", "12345", ""]:
            result = DataExtractor._categorize_item(description)
            assert result in RECEIPT_CATEGORIES


# ---------------------------------------------------------------------------
# clean_json_response
# ---------------------------------------------------------------------------


class TestCleanJsonResponse:
    def test_strips_markdown_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = clean_json_response(raw)
        assert json.loads(result) == {"key": "value"}

    def test_strips_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        result = clean_json_response(raw)
        assert json.loads(result) == {"key": "value"}

    def test_removes_trailing_commas_in_object(self):
        raw = '{"a": 1, "b": 2,}'
        result = clean_json_response(raw)
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_removes_trailing_commas_in_array(self):
        raw = '{"items": [1, 2, 3,]}'
        result = clean_json_response(raw)
        parsed = json.loads(result)
        assert parsed["items"] == [1, 2, 3]

    def test_returns_empty_object_on_no_json(self):
        result = clean_json_response("This is plain text with no JSON.")
        assert result == "{}"

    def test_valid_json_passes_through(self):
        raw = '{"vendor": "Müller GmbH", "total_amount": 25.90}'
        result = clean_json_response(raw)
        parsed = json.loads(result)
        assert parsed["vendor"] == "Müller GmbH"

    def test_does_not_corrupt_url_in_value(self):
        """
        Regression: old regex ran on the entire string including string values,
        turning 'http://localhost:11434' into broken JSON.
        Now valid JSON is returned as-is without any regex substitution.
        """
        raw = '{"base_url": "http://localhost:11434"}'
        result = clean_json_response(raw)
        parsed = json.loads(result)
        assert parsed["base_url"] == "http://localhost:11434"

    def test_does_not_corrupt_nested_colons(self):
        raw = '{"note": "Ratio: 1:2 split"}'
        result = clean_json_response(raw)
        parsed = json.loads(result)
        assert "Ratio" in parsed["note"]
        assert "1:2" in parsed["note"]

    def test_extracts_json_from_surrounding_text(self):
        raw = 'Here is the result:\n{"vendor": "Test GmbH"}\nEnd of response.'
        result = clean_json_response(raw)
        parsed = json.loads(result)
        assert parsed["vendor"] == "Test GmbH"


# ---------------------------------------------------------------------------
# parse_decimal
# ---------------------------------------------------------------------------


class TestParseDecimal:
    def test_integer_string(self):
        assert parse_decimal("42") == Decimal("42")

    def test_float_string(self):
        assert parse_decimal("3.14") == Decimal("3.14")

    def test_integer_value(self):
        assert parse_decimal(100) == Decimal("100")

    def test_float_value(self):
        assert parse_decimal(9.99) is not None

    def test_none_returns_none(self):
        assert parse_decimal(None) is None

    def test_empty_string_returns_none(self):
        assert parse_decimal("") is None

    def test_non_numeric_returns_none(self):
        assert parse_decimal("not a number") is None

    def test_decimal_input(self):
        d = Decimal("5.50")
        assert parse_decimal(d) == d


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_iso_format(self):
        assert parse_date("2024-03-15") == datetime(2024, 3, 15)

    def test_german_dot_format(self):
        assert parse_date("15.03.2024") == datetime(2024, 3, 15)

    def test_slash_format(self):
        assert parse_date("15/03/2024") == datetime(2024, 3, 15)

    def test_none_returns_none(self):
        assert parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert parse_date("") is None

    def test_invalid_string_returns_none(self):
        assert parse_date("not-a-date") is None

    def test_german_month_name_via_fallback(self):
        """parse_date must handle German month names without relying on locale."""
        result = parse_date("15 März 2024")
        assert result == datetime(2024, 3, 15)

    def test_no_locale_dependency(self):
        """
        Regression: old code used %B/%b which fails on English macOS
        for German month names.
        """
        result = parse_date("1 Januar 2023")
        assert result == datetime(2023, 1, 1)
