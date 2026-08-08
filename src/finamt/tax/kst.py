"""
finamt.tax.kst
~~~~~~~~~~~~~~
Körperschaftsteuer (KSt) — German corporate income tax return.

KSt overview
------------
Körperschaftsteuer applies to legal entities (GmbH, AG, e.G., Verein, …).
The standard rate is **15 %** of the *zu versteuerndes Einkommen* (zvE).
Solidaritätszuschlag (SolZ) is levied on top at **5.5 %** of the KSt amount.

Filing
------
The annual Körperschaftsteuererklärung (form **E30**) is submitted to the
Finanzamt via ELSTER under Datenart "KSt", Verfahren "ElsterErklaerung".
It is always an annual return — there is no periodic pre-return for KSt.

The E30 form is highly complex with dozens of optional schedules (Anlagen).
This module covers the core computation.  Additional schedules (e.g. KSt 1 A
for GmbH dividend exemptions, KSt 1 B for interest deductions) can be attached
to the :class:`KStReport` as *anlagen_xml* if needed.

Usage::

    from finamt.tax.kst import KStReport, generate_kst

    report = generate_kst(
        company_name="Muster GmbH",
        rechtsform="GmbH",
        year=2024,
        zvE=100_000,          # zu versteuerndes Einkommen
        prepayments=10_000,   # bereits geleistete Vorauszahlungen
    )
    print(report.summary())

    # ELSTER submission via ERiC:
    from finamt.tax.elster import ElsterConfig, ElsterEricClient

    config = ElsterConfig(...)
    client = ElsterEricClient(config, eric_home="/path/to/eric/lib", use_test=True)
    result = client.submit_kst(report)
    print(result)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

_TWO = Decimal("0.01")
_ONE = Decimal("1")

# Standard German corporate tax rates (§ 23 KStG, § 4 SolZG)
KST_RATE = Decimal("0.15")   # 15 %
SOLI_RATE = Decimal("0.055")  # 5.5 % of KSt


def _r2(d: Decimal) -> Decimal:
    return d.quantize(_TWO, rounding=ROUND_HALF_UP)


def _r0(d: Decimal) -> Decimal:
    """Round down to whole euros (ELSTER convention for tax bases)."""
    return d.quantize(_ONE, rounding=ROUND_DOWN)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class KStReport:
    """
    Körperschaftsteuer annual return data.

    Parameters
    ----------
    company_name:
        Name of the corporation (max 45 chars in ELSTER Vorsatz).
    rechtsform:
        Legal form string, e.g. "GmbH", "AG", "e.G.", "Verein".
    year:
        Assessment year (Veranlagungsjahr), e.g. 2024.
    zvE:
        Zu versteuerndes Einkommen (taxable income, rounded down to whole €).
        May be negative (Verlust).
    kst_rate:
        Körperschaftsteuersatz — default 15 % per § 23 Abs. 1 KStG.
    soli_rate:
        Solidaritätszuschlagssatz — default 5.5 % of KSt per § 4 SolZG.
    prepayments:
        Vorauszahlungen already paid (positive = reduces remaining liability).
    is_berichtigung:
        True → amended return (berichtigte Erklärung).

    Computed properties (read-only)
    --------------------------------
    kst          Körperschaftsteuer on zvE at kst_rate.
    soli         Solidaritätszuschlag on kst at soli_rate.
    total_tax    kst + soli.
    remaining    total_tax − prepayments  (positive = still owed; negative = refund).
    """

    company_name: str
    rechtsform: str
    year: int
    zvE: Decimal = field(default_factory=Decimal)
    kst_rate: Decimal = field(default_factory=lambda: KST_RATE)
    soli_rate: Decimal = field(default_factory=lambda: SOLI_RATE)
    prepayments: Decimal = field(default_factory=Decimal)
    is_berichtigung: bool = False

    def __post_init__(self) -> None:
        # Coerce numeric fields to Decimal
        if not isinstance(self.zvE, Decimal):
            self.zvE = Decimal(str(self.zvE))
        if not isinstance(self.kst_rate, Decimal):
            self.kst_rate = Decimal(str(self.kst_rate))
        if not isinstance(self.soli_rate, Decimal):
            self.soli_rate = Decimal(str(self.soli_rate))
        if not isinstance(self.prepayments, Decimal):
            self.prepayments = Decimal(str(self.prepayments))

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @property
    def kst(self) -> Decimal:
        """Körperschaftsteuer = max(zvE, 0) × kst_rate, rounded to cents."""
        taxable = max(_r0(self.zvE), Decimal("0"))
        return _r2(taxable * self.kst_rate)

    @property
    def soli(self) -> Decimal:
        """Solidaritätszuschlag = kst × soli_rate, rounded to cents."""
        return _r2(self.kst * self.soli_rate)

    @property
    def total_tax(self) -> Decimal:
        """KSt + SolZ."""
        return _r2(self.kst + self.soli)

    @property
    def remaining(self) -> Decimal:
        """
        Verbleibende Zahllast / Erstattung.
        Positive → you still owe this amount.
        Negative → Finanzamt owes you a refund.
        """
        return _r2(self.total_tax - self.prepayments)

    @property
    def has_liability(self) -> bool:
        """True when zvE > 0 (tax liability exists)."""
        return self.zvE > 0

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Human-readable summary of the KSt return."""
        lines = [
            f"Körperschaftsteuererklärung {self.year}",
            f"  Unternehmen:          {self.company_name} ({self.rechtsform})",
            f"  zvE:                  {self.zvE:,.2f} €",
            f"  KSt ({self.kst_rate * 100:.0f} %):           {self.kst:,.2f} €",
            f"  SolZ ({self.soli_rate * 100:.1f} %):         {self.soli:,.2f} €",
            f"  Gesamtsteuer:         {self.total_tax:,.2f} €",
            f"  Vorauszahlungen:     −{self.prepayments:,.2f} €",
            "  " + "─" * 38,
        ]
        remaining = self.remaining
        if remaining > 0:
            lines.append(f"  Nachzahlung:          {remaining:,.2f} €")
        elif remaining < 0:
            lines.append(f"  Erstattung:           {abs(remaining):,.2f} €")
        else:
            lines.append("  Kein Restbetrag       0,00 €")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "company_name": self.company_name,
            "rechtsform": self.rechtsform,
            "year": self.year,
            "zvE": str(self.zvE),
            "kst_rate": str(self.kst_rate),
            "soli_rate": str(self.soli_rate),
            "kst": str(self.kst),
            "soli": str(self.soli),
            "total_tax": str(self.total_tax),
            "prepayments": str(self.prepayments),
            "remaining": str(self.remaining),
            "is_berichtigung": self.is_berichtigung,
        }


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def generate_kst(
    company_name: str,
    rechtsform: str,
    year: int,
    zvE: Decimal | int | float | str,
    prepayments: Decimal | int | float | str = 0,
    kst_rate: Decimal | float | str = KST_RATE,
    soli_rate: Decimal | float | str = SOLI_RATE,
    is_berichtigung: bool = False,
) -> KStReport:
    """
    Create a :class:`KStReport` from basic annual figures.

    Parameters
    ----------
    company_name:
        Name of the corporation (max 45 chars for ELSTER Vorsatz).
    rechtsform:
        Legal form, e.g. "GmbH", "AG", "e.G.".
    year:
        Veranlagungsjahr (assessment year), e.g. 2024.
    zvE:
        Zu versteuerndes Einkommen.  Pass a negative value for a loss year.
    prepayments:
        Körperschaftsteuer-Vorauszahlungen already paid in the year.
    kst_rate:
        Override the 15 % standard rate (use e.g. ``Decimal("0.15")``).
    soli_rate:
        Override the 5.5 % SolZ rate.
    is_berichtigung:
        True → amended / corrected return.

    Returns
    -------
    :class:`KStReport`
    """
    return KStReport(
        company_name=company_name,
        rechtsform=rechtsform,
        year=year,
        zvE=Decimal(str(zvE)),
        kst_rate=Decimal(str(kst_rate)),
        soli_rate=Decimal(str(soli_rate)),
        prepayments=Decimal(str(prepayments)),
        is_berichtigung=is_berichtigung,
    )
