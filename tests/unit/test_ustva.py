"""
tests/test_ustva.py
~~~~~~~~~~~~~~~~~~~~
Tests for finamt.tax.ustva — generate_ustva, USTVAReport, USTVALineItem.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from finamt.models import Counterparty, ReceiptCategory, ReceiptData, ReceiptType
from finamt.tax.ustva import USTVALineItem, USTVAReport, generate_ustva

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    receipt_date: datetime | None = datetime(2024, 2, 14),
    total_amount: str | None = "119.00",
    vat_percentage: str | None = "19",
    vat_amount: str | None = "19.00",
    category: str = "software",
    receipt_type: str = "purchase",
) -> ReceiptData:
    return ReceiptData(
        raw_text=f"Test receipt {uuid.uuid4()}",  # unique hash per receipt
        receipt_type=ReceiptType(receipt_type),
        counterparty=Counterparty(name="Test GmbH"),
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount) if total_amount else None,
        vat_percentage=Decimal(vat_percentage) if vat_percentage else None,
        vat_amount=Decimal(vat_amount) if vat_amount else None,
        category=ReceiptCategory(category),
    )


Q1_START = date(2024, 1, 1)
Q1_END = date(2024, 3, 31)


# ---------------------------------------------------------------------------
# generate_ustva — basic correctness
# ---------------------------------------------------------------------------


class TestGenerateUstva:
    def test_empty_input_returns_empty_report(self):
        report = generate_ustva([], Q1_START, Q1_END)
        assert report.total_input_vat == Decimal("0")
        assert report.total_output_vat == Decimal("0")
        assert report.net_liability == Decimal("0")
        assert report.lines == {}

    def test_single_purchase_19pct(self):
        receipts = [_receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert "19" in report.lines
        ln = report.lines["19"]
        assert ln.purchase_vat == Decimal("19.00")
        assert ln.purchase_net == Decimal("100.00")
        assert ln.purchase_count == 1
        assert ln.sale_vat == Decimal("0")

    def test_single_sale_19pct(self):
        receipts = [
            _receipt(
                total_amount="119.00", vat_amount="19.00", vat_percentage="19", receipt_type="sale"
            )
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        ln = report.lines["19"]
        assert ln.sale_vat == Decimal("19.00")
        assert ln.sale_net == Decimal("100.00")
        assert ln.sale_count == 1
        assert ln.purchase_vat == Decimal("0")

    def test_single_receipt_7pct(self):
        receipts = [_receipt(total_amount="107.00", vat_amount="7.00", vat_percentage="7")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert "7" in report.lines
        assert report.lines["7"].purchase_vat == Decimal("7.00")

    def test_mixed_rates_grouped_separately(self):
        receipts = [
            _receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19"),
            _receipt(total_amount="107.00", vat_amount="7.00", vat_percentage="7"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert "19" in report.lines
        assert "7" in report.lines

    def test_multiple_purchases_same_rate_accumulated(self):
        receipts = [
            _receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19"),
            _receipt(total_amount="238.00", vat_amount="38.00", vat_percentage="19"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.lines["19"].purchase_vat == Decimal("57.00")
        assert report.lines["19"].purchase_net == Decimal("300.00")
        assert report.lines["19"].purchase_count == 2

    def test_net_liability_purchase_only(self):
        """Only purchases → output VAT is 0 → liability is negative (refund)."""
        receipts = [_receipt(vat_amount="19.00", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.net_liability == Decimal("-19.00")

    def test_net_liability_sale_only(self):
        """Only sales → input VAT is 0 → liability is positive (you owe)."""
        receipts = [_receipt(vat_amount="19.00", vat_percentage="19", receipt_type="sale")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.net_liability == Decimal("19.00")

    def test_net_liability_balanced(self):
        receipts = [
            _receipt(vat_amount="19.00", vat_percentage="19", receipt_type="purchase"),
            _receipt(vat_amount="19.00", vat_percentage="19", receipt_type="sale"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.net_liability == Decimal("0")

    def test_total_input_vat_sums_purchases(self):
        receipts = [
            _receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19"),
            _receipt(total_amount="107.00", vat_amount="7.00", vat_percentage="7"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.total_input_vat == Decimal("26.00")

    def test_total_output_vat_sums_sales(self):
        receipts = [
            _receipt(vat_amount="19.00", vat_percentage="19", receipt_type="sale"),
            _receipt(vat_amount="7.00", vat_percentage="7", receipt_type="sale"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.total_output_vat == Decimal("26.00")


# ---------------------------------------------------------------------------
# Skipping logic
# ---------------------------------------------------------------------------


class TestSkipping:
    def test_skips_receipt_without_date(self):
        report = generate_ustva([_receipt(receipt_date=None)], Q1_START, Q1_END)
        assert report.skipped_count == 1
        assert report.total_input_vat == Decimal("0")

    def test_skips_receipt_outside_period(self):
        report = generate_ustva([_receipt(receipt_date=datetime(2024, 12, 1))], Q1_START, Q1_END)
        assert report.skipped_count == 1

    def test_skips_receipt_with_zero_vat(self):
        report = generate_ustva([_receipt(vat_amount="0.00")], Q1_START, Q1_END)
        assert report.skipped_count == 1

    def test_skips_receipt_with_none_vat(self):
        report = generate_ustva([_receipt(vat_amount=None)], Q1_START, Q1_END)
        assert report.skipped_count == 1

    def test_skipped_and_valid_counted_separately(self):
        receipts = [
            _receipt(receipt_date=None),  # skipped
            _receipt(receipt_date=datetime(2023, 6, 1)),  # outside period
            _receipt(receipt_date=datetime(2024, 2, 1)),  # valid
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.skipped_count == 2
        assert report.total_receipts == 1

    def test_period_boundary_inclusive(self):
        receipts = [
            _receipt(receipt_date=datetime(2024, 1, 1)),  # first day
            _receipt(receipt_date=datetime(2024, 3, 31)),  # last day
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.skipped_count == 0
        assert report.total_receipts == 2


# ---------------------------------------------------------------------------
# datetime vs date regression
# ---------------------------------------------------------------------------


class TestDateHandling:
    def test_datetime_receipt_date_does_not_raise(self):
        r = _receipt(receipt_date=datetime(2024, 2, 15, 14, 30))
        report = generate_ustva([r], Q1_START, Q1_END)
        assert report.total_receipts == 1

    def test_date_bounds_accepted(self):
        r = _receipt(receipt_date=datetime(2024, 2, 15))
        report = generate_ustva([r], date(2024, 1, 1), date(2024, 3, 31))
        assert report.total_receipts == 1

    def test_datetime_bounds_accepted(self):
        r = _receipt(receipt_date=datetime(2024, 2, 15))
        report = generate_ustva([r], datetime(2024, 1, 1), datetime(2024, 3, 31))
        assert report.total_receipts == 1


# ---------------------------------------------------------------------------
# USTVALineItem
# ---------------------------------------------------------------------------


class TestUSTVALineItem:
    def test_net_liability_is_sale_minus_purchase(self):
        ln = USTVALineItem(
            vat_rate=Decimal("19"),
            purchase_vat=Decimal("10.00"),
            sale_vat=Decimal("30.00"),
        )
        assert ln.net_liability == Decimal("20.00")

    def test_net_liability_negative_means_refund(self):
        ln = USTVALineItem(
            vat_rate=Decimal("19"),
            purchase_vat=Decimal("30.00"),
            sale_vat=Decimal("10.00"),
        )
        assert ln.net_liability == Decimal("-20.00")

    def test_to_dict_keys(self):
        ln = USTVALineItem(
            vat_rate=Decimal("19"),
            purchase_net=Decimal("100.00"),
            purchase_vat=Decimal("19.00"),
            purchase_count=1,
            sale_net=Decimal("200.00"),
            sale_vat=Decimal("38.00"),
            sale_count=2,
        )
        d = ln.to_dict()
        assert set(d.keys()) == {
            "vat_rate",
            "purchase_net",
            "purchase_vat",
            "purchase_count",
            "sale_net",
            "sale_vat",
            "sale_count",
            "net_liability",
        }
        assert d["purchase_count"] == 1
        assert d["sale_count"] == 2


# ---------------------------------------------------------------------------
# USTVAReport
# ---------------------------------------------------------------------------


class TestUSTVAReport:
    def _report(self) -> USTVAReport:
        report = USTVAReport(period_start=Q1_START, period_end=Q1_END)
        report.lines["19"] = USTVALineItem(
            vat_rate=Decimal("19"),
            purchase_net=Decimal("200.00"),
            purchase_vat=Decimal("38.00"),
            purchase_count=2,
            sale_net=Decimal("100.00"),
            sale_vat=Decimal("19.00"),
            sale_count=1,
        )
        report.lines["7"] = USTVALineItem(
            vat_rate=Decimal("7"),
            purchase_net=Decimal("100.00"),
            purchase_vat=Decimal("7.00"),
            purchase_count=1,
        )
        return report

    def test_total_input_vat(self):
        assert self._report().total_input_vat == Decimal("45.00")

    def test_total_output_vat(self):
        assert self._report().total_output_vat == Decimal("19.00")

    def test_net_liability(self):
        # 19.00 (output) - 45.00 (input) = -26.00 (refund)
        assert self._report().net_liability == Decimal("-26.00")

    def test_total_receipts(self):
        # purchase_count: 2+1=3, sale_count: 1
        assert self._report().total_receipts == 4

    def test_line_19_accessor(self):
        assert self._report().line_19 is not None
        assert self._report().line_19.vat_rate == Decimal("19")

    def test_line_7_accessor(self):
        assert self._report().line_7 is not None

    def test_line_19_none_when_absent(self):
        report = USTVAReport(period_start=Q1_START, period_end=Q1_END)
        assert report.line_19 is None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    def test_to_dict_structure(self):
        receipts = [_receipt()]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        d = report.to_dict()
        assert d["period_start"] == "2024-01-01"
        assert d["period_end"] == "2024-03-31"
        for key in (
            "total_input_vat",
            "total_output_vat",
            "net_liability",
            "total_receipts",
            "lines",
        ):
            assert key in d

    def test_to_json_is_valid_json(self):
        report = generate_ustva([_receipt()], Q1_START, Q1_END)
        parsed = json.loads(report.to_json())
        assert "period_start" in parsed

    def test_to_json_writes_file(self, tmp_path):
        report = generate_ustva([_receipt()], Q1_START, Q1_END)
        out = tmp_path / "ustva.json"
        report.to_json(out)
        assert out.exists()
        assert json.loads(out.read_text(encoding="utf-8"))["period_start"] == "2024-01-01"

    def test_summary_contains_period(self):
        report = generate_ustva([_receipt()], Q1_START, Q1_END)
        summary = report.summary()
        assert "2024-01-01" in summary
        assert "2024-03-31" in summary

    def test_summary_contains_vat_rate(self):
        report = generate_ustva(
            [_receipt(vat_percentage="19", vat_amount="19.00")], Q1_START, Q1_END
        )
        assert "19" in report.summary()

    def test_summary_contains_totals(self):
        report = generate_ustva(
            [_receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19")],
            Q1_START,
            Q1_END,
        )
        summary = report.summary()
        assert "19.00" in summary
        assert "100.00" in summary

    def test_summary_shows_liability_direction(self):
        purchase = _receipt(vat_amount="10.00", vat_percentage="19")
        sale = _receipt(vat_amount="30.00", vat_percentage="19", receipt_type="sale")
        report = generate_ustva([purchase, sale], Q1_START, Q1_END)
        assert "Finanzamt" in report.summary()  # shows direction in German text


# ---------------------------------------------------------------------------
# Rounding / normalisation
# ---------------------------------------------------------------------------


class TestRounding:
    def test_vat_amounts_rounded_to_two_decimal_places(self):
        # Formula: NETTO = 10.00 / 1.19 = 8.4034... → 8.40; VAT = 10.00 − 8.40 = 1.60
        # The stored vat_amount is ignored when vat_percentage is present.
        receipts = [_receipt(total_amount="10.00", vat_amount="1.905", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.lines["19"].purchase_vat == Decimal("1.60")

    def test_decimal_normalisation(self):
        """Decimal('19.0').normalize() == '19' — both map to the same bucket."""
        receipts = [
            _receipt(vat_percentage="19.0", vat_amount="19.00"),
            _receipt(vat_percentage="19", vat_amount="19.00"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert len(report.lines) == 1
        assert report.lines["19"].purchase_count == 2
