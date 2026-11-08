"""
tests/test_pipeline.py
~~~~~~~~~~~~~~~~~~~~~~
Unit tests for pipeline helper functions.
"""

from __future__ import annotations

from finamt.agents.pipeline import _reconcile_vat, _strip_taxpayer_fields, implied_vat_rate

# ---------------------------------------------------------------------------
# _strip_taxpayer_fields
# ---------------------------------------------------------------------------

TAXPAYER = {
    "name": "Mustermann GmbH",
    "vat_id": "DE123456789",
    "tax_number": "29/815/00806",
    "address": "Musterstraße 1, 12345 Musterstadt",  # legacy composite, kept for compat
    # Individual address fields (sent by the frontend as separate query params)
    "street": "Musterstraße 1",
    "postcode": "12345",
    "city": "Musterstadt",
    "state": "Bayern",
    "country": "DE",
}


def _cp(**kwargs) -> dict:
    """Build a minimal counterparty dict."""
    defaults = {
        "name": None,
        "vat_id": None,
        "tax_number": None,
        "street_and_number": None,
        "address_supplement": None,
        "postcode": None,
        "city": None,
        "state": None,
        "country": None,
    }
    defaults.update(kwargs)
    return defaults


class TestStripTaxpayerFields:
    def test_noop_when_no_taxpayer_info(self):
        cp = _cp(name="ACME AG", vat_id="DE999")
        result = _strip_taxpayer_fields(cp, None)
        assert result["name"] == "ACME AG"
        assert result["vat_id"] == "DE999"

    def test_noop_when_taxpayer_info_empty(self):
        cp = _cp(name="ACME AG", vat_id="DE999")
        result = _strip_taxpayer_fields(cp, {})
        assert result["name"] == "ACME AG"
        assert result["vat_id"] == "DE999"

    def test_strips_matching_vat_id(self):
        cp = _cp(name="Some Vendor", vat_id="DE123456789")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["vat_id"] is None
        assert result["name"] == "Some Vendor"  # name differs → kept

    def test_strips_matching_tax_number(self):
        cp = _cp(name="Some Vendor", tax_number="29/815/00806")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["tax_number"] is None

    def test_strips_matching_name(self):
        cp = _cp(name="Mustermann GmbH", vat_id="DE999")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["name"] is None
        assert result["vat_id"] == "DE999"  # different → kept

    def test_case_insensitive_match(self):
        cp = _cp(vat_id="de123456789")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["vat_id"] is None

    def test_whitespace_normalised_match(self):
        cp = _cp(vat_id="  DE123456789  ")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["vat_id"] is None

    def test_partial_match_not_stripped(self):
        """A substring match must not trigger stripping — exact match only."""
        cp = _cp(vat_id="DE12345678")  # one digit shorter
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["vat_id"] == "DE12345678"

    def test_strips_all_matching_fields_at_once(self):
        cp = _cp(
            name="Mustermann GmbH",
            vat_id="DE123456789",
            tax_number="29/815/00806",
        )
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["name"] is None
        assert result["vat_id"] is None
        assert result["tax_number"] is None

    def test_strips_matching_street(self):
        cp = _cp(street_and_number="Musterstraße 1")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["street_and_number"] is None

    def test_strips_matching_postcode(self):
        cp = _cp(postcode="12345")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["postcode"] is None

    def test_strips_matching_city(self):
        cp = _cp(city="Musterstadt")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["city"] is None

    def test_strips_matching_state(self):
        cp = _cp(state="Bayern")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["state"] is None

    def test_strips_matching_country(self):
        cp = _cp(country="DE")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["country"] is None

    def test_address_fields_not_stripped_when_different(self):
        """Different address values must not be touched."""
        cp = _cp(
            city="Berlin",
            postcode="10117",
        )
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["city"] == "Berlin"
        assert result["postcode"] == "10117"

    def test_address_supplement_never_stripped(self):
        """address_supplement has no taxpayer counterpart — always kept."""
        cp = _cp(address_supplement="c/o Musterstraße 1")
        result = _strip_taxpayer_fields(cp, TAXPAYER)
        assert result["address_supplement"] == "c/o Musterstraße 1"

    def test_does_not_mutate_original(self):
        cp = _cp(vat_id="DE123456789")
        original_vat = cp["vat_id"]
        _strip_taxpayer_fields(cp, TAXPAYER)
        assert cp["vat_id"] == original_vat  # original dict unchanged


# ---------------------------------------------------------------------------
# _reconcile_vat / implied_vat_rate
# ---------------------------------------------------------------------------


class TestReconcileVat:
    def test_zero_vat_amount_forces_zero_rate(self):
        got = _reconcile_vat({"total_amount": 113.0, "vat_percentage": 19.0, "vat_amount": 0.0}, "")
        assert got["vat_percentage"] == 0.0

    def test_amounts_imply_rate_overrides_llm(self):
        got = _reconcile_vat({"total_amount": 107.0, "vat_percentage": 19.0, "vat_amount": 7.0}, "")
        assert got["vat_percentage"] == 7.0

    def test_ungrounded_rate_is_dropped(self):
        got = _reconcile_vat({"total_amount": 113.0, "vat_percentage": 19.0}, "Summe 113,00 EUR")
        assert "vat_percentage" not in got

    def test_rate_printed_in_text_is_kept(self):
        got = _reconcile_vat({"total_amount": 119.0, "vat_percentage": 19.0}, "MwSt 19,00 % 19,00")
        assert got["vat_percentage"] == 19.0

    def test_zero_rate_gets_zero_amount(self):
        got = _reconcile_vat({"total_amount": 50.0, "vat_percentage": 0.0}, "steuerfrei")
        assert got["vat_amount"] == 0.0

    def test_mixed_rates_left_alone(self):
        assert implied_vat_rate(100.0, 12.0) is None
