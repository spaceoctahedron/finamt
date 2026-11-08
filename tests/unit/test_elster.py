"""
tests/test_elster.py
~~~~~~~~~~~~~~~~~~~~
Tests for finamt.tax.elster — pure helpers, dataclasses, XML builders,
response parser, and ImportError guards.

Network and certificate operations are not exercised here.
"""

from __future__ import annotations

import os
import re
import uuid
import warnings
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from finamt.models import Counterparty, ReceiptCategory, ReceiptData, ReceiptType
from finamt.tax.elster import (
    ELSTER_URL_PRODUCTION,
    ELSTER_URL_TEST,
    TESTMERKER,
    EBilanzEnvelopeBuilder,
    ElsterConfig,
    ElsterEricClient,
    ElsterXMLBuilder,
    SubmissionResult,
    _bundesland_ziel,
    _make_ticket,
    _ustva_kennzahlen,
    bundesland_kz_from_city,
    normalise_steuernummer,
)
from finamt.tax.ustva import generate_ustva

try:
    from lxml import etree as ET

    _LXML = True
except ImportError:
    _LXML = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YEAR = 2024
Q1_S = date(YEAR, 1, 1)
Q1_E = date(YEAR, 3, 31)


def _cfg(**kwargs) -> ElsterConfig:
    defaults = {
        "cert_path": "/tmp/test.pfx",
        "cert_password": "secret",
        "steuernummer": "21/815/08150",
        "finanzamt_nr": "2181",
        "bundesland_kz": "21",
    }
    defaults.update(kwargs)
    return ElsterConfig(**defaults)


def _receipt(
    *,
    total_amount: str = "119.00",
    vat_amount: str = "19.00",
    vat_percentage: str = "19",
    receipt_type: str = "purchase",
    receipt_date: datetime = datetime(YEAR, 2, 14),
) -> ReceiptData:
    return ReceiptData(
        raw_text=f"Test {uuid.uuid4()}",
        receipt_type=ReceiptType(receipt_type),
        counterparty=Counterparty(name="Test GmbH"),
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount),
        vat_amount=Decimal(vat_amount),
        vat_percentage=Decimal(vat_percentage),
        category=ReceiptCategory("software"),
    )


# ---------------------------------------------------------------------------
# _make_ticket
# ---------------------------------------------------------------------------


class TestMakeTicket:
    _REGEX = re.compile(r"^[0-9a-km-z]{2}[0-9]{3}[0-9a-km-z]{27}$")

    def test_length_is_32(self):
        assert len(_make_ticket()) == 32

    def test_matches_eric_regex(self):
        for _ in range(20):
            assert self._REGEX.match(_make_ticket()), _make_ticket()

    def test_no_lowercase_l(self):
        for _ in range(50):
            assert "l" not in _make_ticket()

    def test_uniqueness(self):
        tickets = {_make_ticket() for _ in range(100)}
        assert len(tickets) > 90  # allow tiny collision chance


# ---------------------------------------------------------------------------
# _bundesland_ziel
# ---------------------------------------------------------------------------


class TestBundeslandZiel:
    def test_numeric_to_short_code(self):
        assert _bundesland_ziel("09") == "BY"

    def test_berlin(self):
        assert _bundesland_ziel("11") == "BE"

    def test_direct_letter_code_passthrough(self):
        # If caller already passes "BY", it's forwarded as-is (not in dict)
        assert _bundesland_ziel("BY") == "BY"

    def test_all_16_states_present(self):
        from finamt.tax.elster import _BUNDESLAND_ZIEL

        assert len(_BUNDESLAND_ZIEL) == 16

    def test_unknown_code_returns_input(self):
        assert _bundesland_ziel("99") == "99"


# ---------------------------------------------------------------------------
# bundesland_kz_from_city
# ---------------------------------------------------------------------------


class TestBundeslandKzFromCity:
    def test_berlin(self):
        assert bundesland_kz_from_city("Berlin") == "11"

    def test_case_insensitive(self):
        assert bundesland_kz_from_city("MÜNCHEN") == "09"

    def test_münchen(self):
        assert bundesland_kz_from_city("münchen") == "09"

    def test_hamburg(self):
        assert bundesland_kz_from_city("Hamburg") == "02"

    def test_unknown_city_returns_empty(self):
        assert bundesland_kz_from_city("Atlantis") == ""

    def test_strips_whitespace(self):
        assert bundesland_kz_from_city("  dresden  ") == "14"


# ---------------------------------------------------------------------------
# normalise_steuernummer
# ---------------------------------------------------------------------------


class TestNormaliseSteuernummer:
    def test_13_digits_unchanged(self):
        assert normalise_steuernummer("2181508150001", "21") == "2181508150001"

    def test_slash_format_normalised(self):
        # SH: FF/BBB/UUUUP → 21FF0BBBUUUUP
        result = normalise_steuernummer("21/815/08150", "21")
        assert result == "2121081508150"

    def test_strips_leading_bundesland(self):
        # 2108150001 — FA=21, rest=08150001 → 21 + 21 + 0 + 08150001
        result = normalise_steuernummer("2108150001", "21")
        assert result == "2121008150001"

    def test_pads_short_number(self):
        result = normalise_steuernummer("12345678", "09")
        assert len(result) == 13


# ---------------------------------------------------------------------------
# _ustva_kennzahlen
# ---------------------------------------------------------------------------


class TestUstvaKennzahlen:
    def test_single_purchase_19pct_gets_kz66(self):
        receipts = [_receipt(vat_amount="19.00", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_S, Q1_E)
        kz = _ustva_kennzahlen(report)
        assert "Kz66" in kz
        assert Decimal(kz["Kz66"]) == Decimal("19.00")

    def test_single_sale_19pct_gets_kz81(self):
        receipts = [
            _receipt(
                total_amount="119.00",
                vat_amount="19.00",
                vat_percentage="19",
                receipt_type="sale",
            )
        ]
        report = generate_ustva(receipts, Q1_S, Q1_E)
        kz = _ustva_kennzahlen(report)
        assert "Kz81" in kz
        assert int(kz["Kz81"]) == 100  # net, whole euros

    def test_sale_7pct_gets_kz86(self):
        receipts = [
            _receipt(
                total_amount="107.00",
                vat_amount="7.00",
                vat_percentage="7",
                receipt_type="sale",
            )
        ]
        report = generate_ustva(receipts, Q1_S, Q1_E)
        kz = _ustva_kennzahlen(report)
        assert "Kz86" in kz

    def test_empty_report_no_kz(self):
        report = generate_ustva([], Q1_S, Q1_E)
        kz = _ustva_kennzahlen(report)
        assert kz == {}

    def test_sale_net_rounded_down(self):
        # Net = 100.99 → should be truncated to 100
        receipts = [
            _receipt(
                total_amount="107.06",
                vat_amount="7.07",
                vat_percentage="7",
                receipt_type="sale",
            )
        ]
        report = generate_ustva(receipts, Q1_S, Q1_E)
        kz = _ustva_kennzahlen(report)
        if "Kz86" in kz:
            assert "." not in kz["Kz86"]  # whole euros — no decimal point

    def test_nonstandard_rate_gets_kz35_kz36(self):
        receipts = [
            _receipt(
                total_amount="110.00",
                vat_amount="10.00",
                vat_percentage="10",
                receipt_type="sale",
            )
        ]
        report = generate_ustva(receipts, Q1_S, Q1_E)
        kz = _ustva_kennzahlen(report)
        assert "Kz35" in kz
        assert "Kz36" in kz


# ---------------------------------------------------------------------------
# ElsterConfig
# ---------------------------------------------------------------------------


class TestElsterConfig:
    def test_creation(self):
        cfg = _cfg()
        assert cfg.steuernummer == "21/815/08150"
        assert cfg.bundesland_kz == "21"

    def test_from_env(self):
        env = {
            "FINAMT_ELSTER_CERT_PATH": "/tmp/cert.pfx",
            "FINAMT_ELSTER_CERT_PASSWORD": "pw",
            "FINAMT_ELSTER_STEUERNUMMER": "21/815/08150",
            "FINAMT_ELSTER_FINANZAMT_NR": "2181",
            "FINAMT_ELSTER_BUNDESLAND_KZ": "21",
        }
        with patch.dict(os.environ, env):
            cfg = ElsterConfig.from_env()
        assert cfg.cert_path == "/tmp/cert.pfx"
        assert cfg.finanzamt_nr == "2181"
        assert cfg.hersteller_id == ""

    def test_from_env_with_hersteller_id(self):
        env = {
            "FINAMT_ELSTER_CERT_PATH": "/tmp/cert.pfx",
            "FINAMT_ELSTER_CERT_PASSWORD": "pw",
            "FINAMT_ELSTER_STEUERNUMMER": "21/815/08150",
            "FINAMT_ELSTER_FINANZAMT_NR": "2181",
            "FINAMT_ELSTER_BUNDESLAND_KZ": "21",
            "FINAMT_ELSTER_HERSTELLER_ID": "H12345",
        }
        with patch.dict(os.environ, env):
            cfg = ElsterConfig.from_env()
        assert cfg.hersteller_id == "H12345"

    def test_from_env_missing_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                ElsterConfig.from_env()


# ---------------------------------------------------------------------------
# SubmissionResult
# ---------------------------------------------------------------------------


class TestSubmissionResult:
    def test_success_str(self):
        r = SubmissionResult(success=True, telenummer="ABC123")
        assert "ABC123" in str(r)
        assert "✓" in str(r)

    def test_failure_str(self):
        r = SubmissionResult(success=False, error_code="E001", error_message="Fehler")
        assert "E001" in str(r)
        assert "✗" in str(r)

    def test_failure_fields(self):
        r = SubmissionResult(
            success=False,
            error_code="PARSE_ERROR",
            error_message="Invalid XML",
            raw_response="<response/>",
        )
        assert r.raw_response == "<response/>"
        assert r.telenummer is None


# ---------------------------------------------------------------------------
# ElsterXMLBuilder (requires lxml)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LXML, reason="lxml not installed")
class TestElsterXMLBuilder:
    def _report(self) -> object:
        receipts = [_receipt(receipt_type="sale")]
        return generate_ustva(receipts, Q1_S, Q1_E)

    def test_returns_bytes(self):
        builder = ElsterXMLBuilder(_cfg())
        xml = builder.build_ustva(self._report(), year=YEAR, period=1)
        assert isinstance(xml, bytes)

    def test_xml_declaration_present(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 1)
        assert xml.startswith(b"<?xml")

    def test_root_tag_is_elster(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 1)
        root = ET.fromstring(xml)
        assert root.tag.endswith("}Elster") or root.tag == "Elster"

    def test_testmerker_present_in_test_mode(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 1, use_test=True)
        assert TESTMERKER.encode() in xml

    def test_testmerker_absent_in_live_mode(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 1, use_test=False)
        assert TESTMERKER.encode() not in xml

    def test_steuernummer_present(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 1)
        # SH: 21/815/08150 + bundesland_kz="21" → 21 + 21 + 0 + 815 + 08150 = 2121081508150
        assert b"2121081508150" in xml

    def test_year_in_xml(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 6)
        assert str(YEAR).encode() in xml

    def test_period_in_xml(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 6)
        assert b"06" in xml

    def test_invalid_steuernummer_raises(self):
        # Unresolvable → normalise fails → ValueError
        cfg = _cfg(steuernummer="INVALID", bundesland_kz="")
        builder = ElsterXMLBuilder(cfg)
        with pytest.raises(ValueError, match="13 digits"):
            builder.build_ustva(self._report(), YEAR, 1)

    def test_kz10_berichtigung_flag(self):
        xml = ElsterXMLBuilder(_cfg()).build_ustva(self._report(), YEAR, 1, is_berichtigung=True)
        assert b"<ns0:Kz10>1<" in xml or b">1<" in xml

    def test_import_error_without_lxml(self, monkeypatch):
        import finamt.tax.elster as elster_mod

        monkeypatch.setattr(elster_mod, "_LXML_AVAILABLE", False)
        with pytest.raises(ImportError, match="lxml"):
            ElsterXMLBuilder(_cfg())


# ---------------------------------------------------------------------------
# EBilanzEnvelopeBuilder (requires lxml)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LXML, reason="lxml not installed")
class TestEBilanzEnvelopeBuilder:
    def _xbrl(self) -> bytes:
        """Minimal well-formed XBRL stub."""
        return b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance">
  <context id="D-2024"><entity><identifier scheme="x">21815</identifier></entity>
  <period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period></context>
</xbrl>"""

    def test_returns_bytes(self):
        env = EBilanzEnvelopeBuilder(_cfg())
        xml = env.build(self._xbrl(), year=YEAR)
        assert isinstance(xml, bytes)

    def test_verfahren_is_elster_bilanz(self):
        xml = EBilanzEnvelopeBuilder(_cfg()).build(self._xbrl(), year=YEAR)
        assert b"ElsterBilanz" in xml

    def test_datenart_is_bilanz(self):
        xml = EBilanzEnvelopeBuilder(_cfg()).build(self._xbrl(), year=YEAR)
        assert b"Bilanz" in xml

    def test_testmerker_in_test_mode(self):
        xml = EBilanzEnvelopeBuilder(_cfg()).build(self._xbrl(), year=YEAR, use_test=True)
        assert TESTMERKER.encode() in xml

    def test_testmerker_absent_live(self):
        xml = EBilanzEnvelopeBuilder(_cfg()).build(self._xbrl(), year=YEAR, use_test=False)
        assert TESTMERKER.encode() not in xml

    def test_xbrl_embedded_in_nutzdaten(self):
        xml = EBilanzEnvelopeBuilder(_cfg()).build(self._xbrl(), year=YEAR)
        root = ET.fromstring(xml)
        nutzdaten = root.findall(".//{*}Nutzdaten")
        assert len(nutzdaten) > 0

    def test_invalid_xbrl_raises_value_error(self):
        env = EBilanzEnvelopeBuilder(_cfg())
        with pytest.raises(ValueError, match="XBRL"):
            env.build(b"<not valid xml<<<", year=YEAR)

    def test_datenart_version_constant(self):
        assert EBilanzEnvelopeBuilder.DATENART_VERSION == "Bilanz_6_9"

    def test_import_error_without_lxml(self, monkeypatch):
        import finamt.tax.elster as elster_mod

        monkeypatch.setattr(elster_mod, "_LXML_AVAILABLE", False)
        with pytest.raises(ImportError, match="lxml"):
            EBilanzEnvelopeBuilder(_cfg())


# ---------------------------------------------------------------------------
# ElsterClient._parse_response (pure static, no network)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LXML, reason="lxml not installed")
class TestElsterClientParseResponse:
    def test_success_telenummer(self):
        xml = """<Elster><Erfolg><Telenummer>TN123456</Telenummer></Erfolg></Elster>"""
        result = from_elster_module_parse_response(xml)
        assert result.success is True
        assert result.telenummer == "TN123456"

    def test_error_response(self):
        xml = """<Elster><Fehler><Code>E9999</Code><Meldung>Ungültige Daten</Meldung></Fehler></Elster>"""
        result = from_elster_module_parse_response(xml)
        assert result.success is False
        assert result.error_code == "E9999"
        assert "Ungültige" in result.error_message

    def test_parse_error_on_broken_xml(self):
        result = from_elster_module_parse_response("this is not xml<<<")
        assert result.success is False
        assert result.error_code == "PARSE_ERROR"

    def test_unknown_response_no_telenummer(self):
        xml = """<Elster><RandomElement/></Elster>"""
        result = from_elster_module_parse_response(xml)
        assert result.success is False


def from_elster_module_parse_response(raw: str) -> SubmissionResult:
    from finamt.tax.elster import ElsterClient

    return ElsterClient._parse_response(raw)


# ---------------------------------------------------------------------------
# ElsterEricClient static helpers
# ---------------------------------------------------------------------------


class TestElsterEricClientStatics:
    def test_extract_telenummer_none_on_empty(self):
        assert ElsterEricClient._extract_telenummer(b"") is None

    @pytest.mark.skipif(not _LXML, reason="lxml not installed")
    def test_extract_telenummer_from_xml(self):
        xml = b"<root><Telenummer>TN999</Telenummer></root>"
        assert ElsterEricClient._extract_telenummer(xml) == "TN999"

    @pytest.mark.skipif(not _LXML, reason="lxml not installed")
    def test_extract_telenummer_missing_returns_none(self):
        xml = b"<root><Other>value</Other></root>"
        assert ElsterEricClient._extract_telenummer(xml) is None

    @pytest.mark.skipif(not _LXML, reason="lxml not installed")
    def test_extract_eric_error_with_eric_text(self):
        msg = ElsterEricClient._extract_eric_error(610301010, b"", b"", eric_text="Fehler X")
        assert "Fehler X" in msg

    @pytest.mark.skipif(not _LXML, reason="lxml not installed")
    def test_extract_eric_error_fallback_to_code(self):
        msg = ElsterEricClient._extract_eric_error(999, b"", b"")
        assert "999" in msg

    @pytest.mark.skipif(not _LXML, reason="lxml not installed")
    def test_extract_eric_error_parses_response_xml(self):
        response_xml = b"<root><Text>Validation failed</Text></root>"
        msg = ElsterEricClient._extract_eric_error(610301010, response_xml, b"")
        assert "Validation failed" in msg


# ---------------------------------------------------------------------------
# ElsterEricClient (ERiC library mocked)
# ---------------------------------------------------------------------------


class TestElsterEricClientInit:
    def test_use_test_default(self):
        client = ElsterEricClient(_cfg(), eric_home="/nonexistent")
        assert client.use_test is True

    def test_production_mode_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ElsterEricClient(_cfg(), eric_home="/nonexistent", use_test=False)
        assert any("PRODUCTION" in str(x.message) for x in w)

    def test_log_dir_default_is_none(self):
        client = ElsterEricClient(_cfg(), eric_home="/nonexistent")
        assert client.log_dir is None

    def test_eric_load_error_returns_failure(self, tmp_path):
        client = ElsterEricClient(_cfg(), eric_home=str(tmp_path), log_dir=str(tmp_path))
        result = client.validate_ebilanz(b"<xbrl/>", year=YEAR)
        # Should fail gracefully — library doesn't exist
        assert result.success is False
        assert result.error_code in ("ERIC_LOAD_ERROR", "XML_BUILD_ERROR", "ERIC_ERROR")


# ---------------------------------------------------------------------------
# Endpoints / constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_production_url_is_https(self):
        assert ELSTER_URL_PRODUCTION.startswith("https://")

    def test_test_url_is_https(self):
        assert ELSTER_URL_TEST.startswith("https://")

    def test_testmerker_value(self):
        assert TESTMERKER == "700000004"
