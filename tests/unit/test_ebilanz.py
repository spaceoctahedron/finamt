"""
tests/test_ebilanz.py
~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.tax.ebilanz — EBilanzConfig, build_xbrl, write_xbrl.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from finamt.models import Counterparty, ReceiptCategory, ReceiptData, ReceiptType
from finamt.tax.bilanz import generate_jahresabschluss
from finamt.tax.ebilanz import NS_GAAP, NS_XBRLI, EBilanzConfig, build_xbrl, write_xbrl

try:
    from lxml import etree as ET

    _LXML = True
except ImportError:
    _LXML = False

pytestmark = pytest.mark.skipif(not _LXML, reason="lxml not installed")

STAMMKAPITAL = Decimal("25000")
EINGEZAHLT = Decimal("12500")
YEAR = 2024


def _cfg(**kwargs) -> EBilanzConfig:
    defaults = {
        "steuernummer": "21/815/08150",
        "company_name": "Muster GmbH",
        "legal_form": "GmbH",
        "fiscal_year_start": f"{YEAR}-01-01",
        "fiscal_year_end": f"{YEAR}-12-31",
    }
    defaults.update(kwargs)
    return EBilanzConfig(**defaults)


def _empty_jab():
    return generate_jahresabschluss(
        [],
        year=YEAR,
        stammkapital=STAMMKAPITAL,
        eingezahltes_kapital=EINGEZAHLT,
    )


def _receipt(
    *,
    receipt_date=datetime(YEAR, 6, 15),
    vat_amount: str = "19.00",
    total_amount: str = "119.00",
    category: str = "software",
    receipt_type: str = "purchase",
) -> ReceiptData:
    """net_amount = total_amount - vat_amount (computed by ReceiptData)."""
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
# EBilanzConfig dataclass
# ---------------------------------------------------------------------------


class TestEBilanzConfig:
    def test_defaults(self):
        cfg = EBilanzConfig(steuernummer="21/815/08150", company_name="Test GmbH")
        assert cfg.legal_form == "GmbH"
        assert cfg.fiscal_year_start == ""
        assert cfg.elster_id == ""

    def test_custom_values(self):
        cfg = _cfg(legal_form="UG (haftungsbeschränkt)", preparer="Max Mustermann")
        assert cfg.legal_form == "UG (haftungsbeschränkt)"
        assert cfg.preparer == "Max Mustermann"


# ---------------------------------------------------------------------------
# build_xbrl — structure
# ---------------------------------------------------------------------------


class TestBuildXbrl:
    def test_returns_bytes(self):
        xml = build_xbrl(_empty_jab(), _cfg())
        assert isinstance(xml, bytes)

    def test_is_valid_xml(self):
        xml = build_xbrl(_empty_jab(), _cfg())
        root = ET.fromstring(xml)
        assert root is not None

    def test_root_tag_is_xbrl(self):
        xml = build_xbrl(_empty_jab(), _cfg())
        root = ET.fromstring(xml)
        assert root.tag == f"{{{NS_XBRLI}}}xbrl"

    def test_xml_declaration_present(self):
        xml = build_xbrl(_empty_jab(), _cfg())
        assert xml.startswith(b"<?xml")

    def test_company_name_in_xml(self):
        xml = build_xbrl(_empty_jab(), _cfg(company_name="Muster GmbH"))
        tree = ET.fromstring(xml)
        # Search for the company name fact text
        texts = [el.text for el in tree.iter() if el.text]
        assert "Muster GmbH" in texts

    def test_total_assets_fact_present(self):
        xml = build_xbrl(_empty_jab(), _cfg())
        tree = ET.fromstring(xml)
        tag = f"{{{NS_GAAP}}}bs.ass"
        facts = tree.findall(f".//{tag}")
        assert len(facts) > 0

    def test_unknown_legal_form_defaults_to_gmbh_code(self):
        xml = build_xbrl(_empty_jab(), _cfg(legal_form="UnknownForm"))
        # Should not raise — falls back to GMBH code
        tree = ET.fromstring(xml)
        assert tree is not None

    def test_with_sale_receipts(self):
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
        xml = build_xbrl(jab, _cfg())
        tree = ET.fromstring(xml)
        tag = f"{{{NS_GAAP}}}ismi.netIncome.netSales"
        facts = tree.findall(f".//{tag}")
        assert any(f.text == "500.00" for f in facts)

    def test_with_material_purchase(self):
        # total=238, vat=38, net=200
        receipts = [
            _receipt(
                category="material",
                receipt_type="purchase",
                total_amount="238.00",
                vat_amount="38.00",
            )
        ]
        jab = generate_jahresabschluss(
            receipts,
            year=YEAR,
            stammkapital=STAMMKAPITAL,
            eingezahltes_kapital=EINGEZAHLT,
        )
        xml = build_xbrl(jab, _cfg())
        tree = ET.fromstring(xml)
        tag = f"{{{NS_GAAP}}}ismi.netIncome.materialServices"
        facts = tree.findall(f".//{tag}")
        assert any(f.text == "200.00" for f in facts)

    def test_fiscal_year_fallback_from_year(self):
        cfg = EBilanzConfig(steuernummer="21/815/08150", company_name="Test")
        xml = build_xbrl(_empty_jab(), cfg)
        assert b"2024-01-01" in xml

    def test_write_xbrl_creates_file(self, tmp_path):
        p = tmp_path / "ebilanz.xbrl"
        result = write_xbrl(_empty_jab(), _cfg(), p)
        assert result.exists()
        assert result.read_bytes().startswith(b"<?xml")


class TestBuildXbrlNoLxml:
    """Test ImportError raised when lxml is absent (mocked)."""

    def test_import_error_without_lxml(self, monkeypatch):
        import finamt.tax.ebilanz as ebilanz_mod

        monkeypatch.setattr(ebilanz_mod, "_LXML_AVAILABLE", False)
        with pytest.raises(ImportError, match="lxml"):
            build_xbrl(_empty_jab(), _cfg())
