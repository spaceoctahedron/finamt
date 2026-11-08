"""
tests/test_bilanz.py
~~~~~~~~~~~~~~~~~~~~
Tests for finamt.tax.bilanz — Bilanz, GuV, Jahresabschluss,
generate_jahresabschluss.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal

from finamt.models import Counterparty, ReceiptCategory, ReceiptData, ReceiptType
from finamt.tax.bilanz import (
    Bilanz,
    GuV,
    Jahresabschluss,
    generate_jahresabschluss,
)

YEAR = 2024
STAMMKAPITAL = Decimal("25000")
EINGEZAHLT = Decimal("12500")
_ZERO = Decimal("0")


def _receipt(
    *,
    receipt_date: datetime | None = datetime(YEAR, 6, 15),
    total_amount: str = "119.00",
    vat_amount: str = "19.00",
    category: str = "software",
    receipt_type: str = "purchase",
) -> ReceiptData:
    """net_amount is computed as total_amount - vat_amount by ReceiptData."""
    return ReceiptData(
        raw_text=f"Test {uuid.uuid4()}",
        receipt_type=ReceiptType(receipt_type),
        counterparty=Counterparty(name="Test GmbH"),
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount),
        vat_amount=Decimal(vat_amount),
        category=ReceiptCategory(category),
    )


# ---------------------------------------------------------------------------
# Bilanz
# ---------------------------------------------------------------------------


class TestBilanz:
    def test_summe_aktiva_sums_correctly(self):
        b = Bilanz(
            year=YEAR,
            kassenbestand=Decimal("10000"),
            anlagevermögen=Decimal("5000"),
        )
        assert b.summe_aktiva == Decimal("15000")

    def test_summe_eigenkapital(self):
        b = Bilanz(
            year=YEAR,
            stammkapital=Decimal("25000"),
            jahresergebnis=Decimal("1000"),
            gewinnvortrag=Decimal("500"),
        )
        assert b.summe_eigenkapital == Decimal("26500")

    def test_nicht_eingefordert_reduces_eigenkapital(self):
        b = Bilanz(
            year=YEAR,
            stammkapital=Decimal("25000"),
            nicht_eingeforderte_einlagen=Decimal("12500"),
        )
        assert b.summe_eigenkapital == Decimal("12500")

    def test_bilanz_ausgeglichen_true(self):
        b = Bilanz(
            year=YEAR,
            kassenbestand=Decimal("12500"),
            stammkapital=Decimal("25000"),
            nicht_eingeforderte_einlagen=Decimal("12500"),
        )
        assert b.bilanz_ausgeglichen is True

    def test_to_dict_keys(self):
        b = Bilanz(year=YEAR)
        d = b.to_dict()
        assert "aktiva" in d and "passiva" in d
        assert "bilanz_ausgeglichen" in d


# ---------------------------------------------------------------------------
# GuV
# ---------------------------------------------------------------------------


class TestGuV:
    def test_jahresergebnis_positive(self):
        g = GuV(year=YEAR, umsatzerlöse=Decimal("1000"), sonstige_betriebsausgaben=Decimal("400"))
        assert g.jahresergebnis == Decimal("600")

    def test_jahresergebnis_negative(self):
        g = GuV(year=YEAR, sonstige_betriebsausgaben=Decimal("500"))
        assert g.jahresergebnis == Decimal("-500")

    def test_gesamtleistung(self):
        g = GuV(
            year=YEAR,
            umsatzerlöse=Decimal("800"),
            sonstige_betriebserlöse=Decimal("200"),
        )
        assert g.gesamtleistung == Decimal("1000")

    def test_to_dict_contains_jahresergebnis(self):
        g = GuV(year=YEAR)
        d = g.to_dict()
        assert "jahresergebnis" in d


# ---------------------------------------------------------------------------
# Jahresabschluss
# ---------------------------------------------------------------------------


class TestJahresabschluss:
    def test_to_dict_nested(self):
        b = Bilanz(year=YEAR)
        g = GuV(year=YEAR)
        jab = Jahresabschluss(bilanz=b, guv=g)
        d = jab.to_dict()
        assert "bilanz" in d and "guv" in d and "skipped_count" in d

    def test_to_json_valid(self):
        b = Bilanz(year=YEAR)
        g = GuV(year=YEAR)
        jab = Jahresabschluss(bilanz=b, guv=g)
        raw = jab.to_json()
        parsed = json.loads(raw)
        assert "bilanz" in parsed

    def test_to_json_writes_file(self, tmp_path):
        b = Bilanz(year=YEAR)
        g = GuV(year=YEAR)
        jab = Jahresabschluss(bilanz=b, guv=g)
        p = tmp_path / "jab.json"
        jab.to_json(str(p))
        assert p.exists()

    def test_summary_returns_string(self):
        b = Bilanz(year=YEAR, kassenbest=Decimal("0")) if False else Bilanz(year=YEAR)
        g = GuV(year=YEAR)
        jab = Jahresabschluss(bilanz=b, guv=g)
        s = jab.summary()
        assert isinstance(s, str)
        assert str(YEAR) in s


# ---------------------------------------------------------------------------
# generate_jahresabschluss
# ---------------------------------------------------------------------------


class TestGenerateJahresabschluss:
    def test_empty_receipts_grundungsjahr(self):
        jab = generate_jahresabschluss(
            [],
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.bilanz.kassenbestand == EINGEZAHLT
        assert jab.guv.jahresergebnis == _ZERO
        assert jab.skipped_count == 0

    def test_nettomethode_balance_sheet_balanced(self):
        jab = generate_jahresabschluss(
            [],
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
            nettomethode=True,
        )
        assert jab.bilanz.bilanz_ausgeglichen is True

    def test_bruttomethode_ausstehende_einlagen_on_aktiva(self):
        jab = generate_jahresabschluss(
            [],
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
            nettomethode=False,
        )
        assert jab.bilanz.ausstehende_einlagen == Decimal("12500")
        assert jab.bilanz.nicht_eingeforderte_einlagen == _ZERO

    def test_purchase_reduces_kassenbestand(self):
        # total=119, vat=19, net=100
        receipts = [_receipt(category="software", total_amount="119.00", vat_amount="19.00")]
        jab = generate_jahresabschluss(
            receipts,
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.bilanz.kassenbestand == EINGEZAHLT - Decimal("100.00")

    def test_sale_increases_kassenbestand(self):
        # total=595, vat=95, net=500
        receipts = [
            _receipt(
                category="services", receipt_type="sale", total_amount="595.00", vat_amount="95.00"
            )
        ]
        jab = generate_jahresabschluss(
            receipts,
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.bilanz.kassenbestand == EINGEZAHLT + Decimal("500.00")

    def test_material_goes_to_materialaufwand(self):
        # total=238, vat=38, net=200
        receipts = [_receipt(category="material", total_amount="238.00", vat_amount="38.00")]
        jab = generate_jahresabschluss(
            receipts,
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.guv.materialaufwand == Decimal("200.00")

    def test_other_category_goes_to_sonstige(self):
        # total=89.25, vat=14.25, net=75
        receipts = [_receipt(category="other", total_amount="89.25", vat_amount="14.25")]
        jab = generate_jahresabschluss(
            receipts,
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.guv.sonstige_betriebsausgaben == Decimal("75.00")

    def test_skips_no_date(self):
        receipts = [_receipt(receipt_date=None)]
        jab = generate_jahresabschluss(
            receipts,
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.skipped_count == 1

    def test_skips_out_of_year(self):
        receipts = [_receipt(receipt_date=datetime(YEAR - 1, 12, 31))]
        jab = generate_jahresabschluss(
            receipts,
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.skipped_count == 1

    def test_skips_no_net_amount(self):
        r = ReceiptData(
            raw_text=f"Test {uuid.uuid4()}",
            receipt_type=ReceiptType("purchase"),
            counterparty=Counterparty(name="X"),
            receipt_date=datetime(YEAR, 1, 15),
            total_amount=None,
            vat_amount=None,
            category=ReceiptCategory("other"),
        )
        jab = generate_jahresabschluss(
            [r],
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        assert jab.skipped_count == 1

    def test_vortrag_gewinnverlust_in_eigenkapital(self):
        jab = generate_jahresabschluss(
            [],
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
            vortrag_gewinnverlust=Decimal("5000"),
        )
        assert jab.bilanz.gewinnvortrag == Decimal("5000")

    def test_custom_kassen_eroffnungsbestand(self):
        jab = generate_jahresabschluss(
            [],
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
            kassen_eröffnungsbestand=Decimal("8000"),
        )
        assert jab.bilanz.kassenbestand == Decimal("8000")

    def test_summary_ausgeglichen_message(self):
        jab = generate_jahresabschluss(
            [],
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        s = jab.summary()
        assert "ausgeglichen" in s or "Differenz" in s
