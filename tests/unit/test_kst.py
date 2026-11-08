"""
Tests for finamt.tax.kst — Körperschaftsteuer computation and ELSTER XML.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from finamt.tax.kst import KStReport, KST_RATE, SOLI_RATE, generate_kst


# ---------------------------------------------------------------------------
# KStReport computation
# ---------------------------------------------------------------------------


class TestKStReport:
    def _report(self, **kwargs) -> KStReport:
        defaults = dict(
            company_name="Test GmbH",
            rechtsform="GmbH",
            year=2024,
            zvE=Decimal("100000"),
        )
        defaults.update(kwargs)
        return KStReport(**defaults)

    def test_kst_standard_rate(self):
        r = self._report(zvE=Decimal("100000"))
        assert r.kst == Decimal("15000.00")

    def test_soli_standard_rate(self):
        r = self._report(zvE=Decimal("100000"))
        # 5.5% of 15000 = 825.00
        assert r.soli == Decimal("825.00")

    def test_total_tax(self):
        r = self._report(zvE=Decimal("100000"))
        assert r.total_tax == Decimal("15825.00")

    def test_remaining_with_prepayments(self):
        r = self._report(zvE=Decimal("100000"), prepayments=Decimal("10000"))
        assert r.remaining == Decimal("5825.00")

    def test_remaining_refund(self):
        r = self._report(zvE=Decimal("100000"), prepayments=Decimal("20000"))
        assert r.remaining == Decimal("-4175.00")

    def test_loss_year_no_kst(self):
        r = self._report(zvE=Decimal("-50000"))
        assert r.kst == Decimal("0.00")
        assert r.soli == Decimal("0.00")
        assert r.total_tax == Decimal("0.00")

    def test_zero_income(self):
        r = self._report(zvE=Decimal("0"))
        assert r.kst == Decimal("0.00")
        assert not r.has_liability

    def test_has_liability_positive(self):
        r = self._report(zvE=Decimal("1"))
        assert r.has_liability

    def test_fractional_zvE_rounded_down(self):
        # zvE rounded down to whole euros before applying rate
        r = self._report(zvE=Decimal("100999.99"))
        # Should compute on 100999
        expected_kst = (Decimal("100999") * KST_RATE).quantize(Decimal("0.01"))
        assert r.kst == expected_kst

    def test_custom_kst_rate(self):
        r = self._report(zvE=Decimal("100000"), kst_rate=Decimal("0.15"))
        assert r.kst == Decimal("15000.00")

    def test_to_dict_keys(self):
        r = self._report()
        d = r.to_dict()
        for key in ("company_name", "rechtsform", "year", "zvE", "kst", "soli",
                    "total_tax", "prepayments", "remaining", "is_berichtigung"):
            assert key in d, f"Missing key: {key}"

    def test_summary_contains_company(self):
        r = self._report()
        s = r.summary()
        assert "Test GmbH" in s
        assert "2024" in s


# ---------------------------------------------------------------------------
# generate_kst factory
# ---------------------------------------------------------------------------


class TestGenerateKst:
    def test_basic(self):
        r = generate_kst("Muster GmbH", "GmbH", 2024, zvE=50000)
        assert r.company_name == "Muster GmbH"
        assert r.year == 2024
        assert r.zvE == Decimal("50000")

    def test_accepts_int_zvE(self):
        r = generate_kst("A AG", "AG", 2024, zvE=200000)
        assert r.kst == Decimal("30000.00")

    def test_accepts_string_zvE(self):
        r = generate_kst("B GmbH", "GmbH", 2023, zvE="75000")
        assert r.zvE == Decimal("75000")

    def test_prepayments(self):
        r = generate_kst("C GmbH", "GmbH", 2024, zvE=100000, prepayments=15825)
        assert r.remaining == Decimal("0.00")


# ---------------------------------------------------------------------------
# ELSTER XML builder (requires lxml)
# ---------------------------------------------------------------------------


pytest.importorskip("lxml", reason="lxml not installed — skipping XML builder tests")


class TestElsterXMLBuilderKst:
    """Smoke-test the E30 XML envelope without an ERiC library."""

    def _config(self):
        from finamt.tax.elster import ElsterConfig

        return ElsterConfig(
            cert_path="/dev/null",  # not loaded in XML-only tests
            cert_password="",
            steuernummer="1137053950531",  # already 13-digit
            finanzamt_nr="1137",
            bundesland_kz="11",
            company_name="Test GmbH",
            street="Musterstraße",
            house_number="1",
            postal_code="10115",
            city="Berlin",
        )

    def _report(self) -> KStReport:
        return generate_kst(
            company_name="Test GmbH",
            rechtsform="GmbH",
            year=2024,
            zvE=100_000,
            prepayments=10_000,
        )

    def test_build_kst_returns_bytes(self):
        from finamt.tax.elster import ElsterXMLBuilder

        builder = ElsterXMLBuilder(self._config())
        xml = builder.build_kst(self._report(), year=2024, use_test=True)
        assert isinstance(xml, bytes)
        assert b"E30" in xml

    def test_build_kst_contains_testmerker(self):
        from finamt.tax.elster import ElsterXMLBuilder

        builder = ElsterXMLBuilder(self._config())
        xml = builder.build_kst(self._report(), year=2024, use_test=True)
        assert b"Testmerker" in xml

    def test_build_kst_datenart_kst(self):
        from finamt.tax.elster import ElsterXMLBuilder

        builder = ElsterXMLBuilder(self._config())
        xml = builder.build_kst(self._report(), year=2024, use_test=True)
        assert b"<ns0:DatenArt>KSt</ns0:DatenArt>" in xml or b">KSt<" in xml

    def test_build_kst_namespace(self):
        from finamt.tax.elster import ElsterXMLBuilder

        builder = ElsterXMLBuilder(self._config())
        xml = builder.build_kst(self._report(), year=2024, use_test=True)
        assert b"finkonsens.de/elster/elstererklaerung/kst/e30/v2024" in xml

    def test_build_kst_contains_zvE(self):
        from finamt.tax.elster import ElsterXMLBuilder

        builder = ElsterXMLBuilder(self._config())
        xml = builder.build_kst(self._report(), year=2024, use_test=True)
        # zvE = 100000 → should appear in E4500001
        assert b"100000" in xml

    def test_build_kst_steuernummer(self):
        from finamt.tax.elster import ElsterXMLBuilder

        builder = ElsterXMLBuilder(self._config())
        xml = builder.build_kst(self._report(), year=2024, use_test=True)
        assert b"1137053950531" in xml

    def test_build_kst_berichtigung_vorgang_02(self):
        from finamt.tax.elster import ElsterXMLBuilder

        builder = ElsterXMLBuilder(self._config())
        report = generate_kst("Test GmbH", "GmbH", 2024, zvE=100000, is_berichtigung=True)
        xml = builder.build_kst(report, year=2024, use_test=True)
        assert b"02" in xml  # Vorgang = "02" for Berichtigung
