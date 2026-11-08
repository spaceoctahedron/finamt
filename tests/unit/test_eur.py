"""
tests/test_eur.py
~~~~~~~~~~~~~~~~~
Tests for finamt.tax.eur — generate_eur, EURReport, EURLinie.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from finamt.models import Counterparty, ReceiptCategory, ReceiptData, ReceiptType
from finamt.tax.eur import EURLinie, EURReport, generate_eur

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YEAR = 2024
START = date(YEAR, 1, 1)
END = date(YEAR, 12, 31)


def _receipt(
    *,
    receipt_date: datetime | None = datetime(YEAR, 6, 15),
    total_amount: str | None = "119.00",
    vat_amount: str | None = "19.00",
    category: str = "software",
    receipt_type: str = "purchase",
) -> ReceiptData:
    return ReceiptData(
        raw_text=f"Test receipt {uuid.uuid4()}",
        receipt_type=ReceiptType(receipt_type),
        counterparty=Counterparty(name="Test GmbH"),
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount) if total_amount else None,
        vat_amount=Decimal(vat_amount) if vat_amount else None,
        category=ReceiptCategory(category),
    )


# ---------------------------------------------------------------------------
# EURLinie
# ---------------------------------------------------------------------------


class TestEURLinie:
    def test_to_dict_contains_required_keys(self):
        ln = EURLinie(category="software", kz="145", label="Software")
        d = ln.to_dict()
        assert "category" in d and "kz" in d and "label" in d
        assert "net_amount" in d and "vat_amount" in d and "gross_amount" in d

    def test_default_amounts_zero(self):
        ln = EURLinie(category="other", kz="176", label="Other")
        assert ln.net_amount == Decimal("0")
        assert ln.count == 0


# ---------------------------------------------------------------------------
# EURReport properties
# ---------------------------------------------------------------------------


class TestEURReport:
    def test_gewinn_empty_report(self):
        r = EURReport(year=YEAR)
        assert r.gewinn == Decimal("0")

    def test_gewinn_with_einnahmen_and_ausgaben(self):
        r = EURReport(year=YEAR)
        r.einnahmen_lines["services"] = EURLinie(
            category="services", kz="111", label="Revenue", net_amount=Decimal("500.00")
        )
        r.ausgaben_lines["software"] = EURLinie(
            category="software", kz="145", label="Software", net_amount=Decimal("200.00")
        )
        assert r.gewinn == Decimal("300.00")

    def test_kz_totals_aggregates_by_kz(self):
        r = EURReport(year=YEAR)
        r.ausgaben_lines["software"] = EURLinie(
            category="software", kz="145", label="Sw", net_amount=Decimal("100.00")
        )
        r.ausgaben_lines["telecommunication"] = EURLinie(
            category="telecommunication", kz="145", label="Tel", net_amount=Decimal("50.00")
        )
        totals = r.kz_totals()
        assert totals["145"] == Decimal("150.00")

    def test_to_dict_structure(self):
        r = EURReport(year=YEAR)
        d = r.to_dict()
        assert d["year"] == YEAR
        assert "total_einnahmen_netto" in d
        assert "gewinn" in d
        assert "einnahmen" in d

    def test_to_json_returns_valid_json(self):
        r = EURReport(year=YEAR)
        raw = r.to_json()
        parsed = json.loads(raw)
        assert parsed["year"] == YEAR

    def test_to_json_writes_file(self, tmp_path):
        p = tmp_path / "eur.json"
        r = EURReport(year=YEAR)
        r.to_json(str(p))
        assert p.exists()
        assert json.loads(p.read_text())["year"] == YEAR

    def test_summary_returns_string(self):
        r = EURReport(year=YEAR)
        s = r.summary()
        assert isinstance(s, str)
        assert str(YEAR) in s


# ---------------------------------------------------------------------------
# generate_eur — core logic
# ---------------------------------------------------------------------------


class TestGenerateEur:
    def test_empty_returns_zero_report(self):
        report = generate_eur([], YEAR)
        assert report.gewinn == Decimal("0")
        assert report.skipped_count == 0
        assert report.einnahmen_lines == {}
        assert report.ausgaben_lines == {}

    def test_purchase_goes_to_ausgaben(self):
        receipts = [_receipt(category="software", receipt_type="purchase")]
        report = generate_eur(receipts, YEAR)
        assert "software" in report.ausgaben_lines
        assert report.ausgaben_lines["software"].net_amount == Decimal("100.00")  # 119-19

    def test_sale_goes_to_einnahmen(self):
        receipts = [
            _receipt(
                category="services", receipt_type="sale", total_amount="595.00", vat_amount="95.00"
            )
        ]
        report = generate_eur(receipts, YEAR)
        assert "services" in report.einnahmen_lines
        assert report.einnahmen_lines["services"].net_amount == Decimal("500.00")

    def test_skips_no_date(self):
        receipts = [_receipt(receipt_date=None)]
        report = generate_eur(receipts, YEAR)
        assert report.skipped_count == 1

    def test_skips_out_of_year(self):
        receipts = [_receipt(receipt_date=datetime(YEAR - 1, 12, 31))]
        report = generate_eur(receipts, YEAR)
        assert report.skipped_count == 1

    def test_skips_no_total_amount(self):
        receipts = [_receipt(total_amount=None, vat_amount=None)]
        report = generate_eur(receipts, YEAR)
        assert report.skipped_count == 1

    def test_travel_mapped_to_kz165(self):
        receipts = [_receipt(category="travel")]
        report = generate_eur(receipts, YEAR)
        assert report.ausgaben_lines["travel"].kz == "165"

    def test_education_mapped_to_kz183(self):
        receipts = [_receipt(category="education")]
        report = generate_eur(receipts, YEAR)
        assert report.ausgaben_lines["education"].kz == "183"

    def test_unknown_category_falls_back_to_176(self):
        receipts = [_receipt(category="other")]
        report = generate_eur(receipts, YEAR)
        assert report.ausgaben_lines["other"].kz == "176"

    def test_multiple_receipts_same_category_accumulate(self):
        receipts = [
            _receipt(category="software"),
            _receipt(category="software"),
        ]
        report = generate_eur(receipts, YEAR)
        assert report.ausgaben_lines["software"].net_amount == Decimal("200.00")
        assert report.ausgaben_lines["software"].count == 2

    def test_gewinn_calculated_correctly(self):
        receipts = [
            # sale: total=1190, vat=190, net=1000
            _receipt(
                category="services",
                receipt_type="sale",
                total_amount="1190.00",
                vat_amount="190.00",
            ),
            # purchase: total=357, vat=57, net=300
            _receipt(
                category="software",
                receipt_type="purchase",
                total_amount="357.00",
                vat_amount="57.00",
            ),
        ]
        report = generate_eur(receipts, YEAR)
        assert report.gewinn == Decimal("700.00")

    def test_vat_tracked_separately(self):
        receipts = [
            _receipt(
                category="software",
                total_amount="119.00",
                vat_amount="19.00",
                receipt_type="purchase",
            )
        ]
        report = generate_eur(receipts, YEAR)
        ln = report.ausgaben_lines["software"]
        assert ln.vat_amount == Decimal("19.00")
        assert ln.gross_amount == Decimal("119.00")

    def test_date_as_date_object_accepted(self):
        r = ReceiptData(
            raw_text=f"Test {uuid.uuid4()}",
            receipt_type=ReceiptType("purchase"),
            counterparty=Counterparty(name="X"),
            receipt_date=date(YEAR, 3, 1),
            total_amount=Decimal("100.00"),
            vat_amount=Decimal("0"),
            category=ReceiptCategory("other"),
        )
        report = generate_eur([r], YEAR)
        assert report.skipped_count == 0
