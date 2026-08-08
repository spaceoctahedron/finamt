"""
finamt.tax
~~~~~~~~~~~~~
Tax return computation modules.

Currently implemented:
  - ``UStVA``  — Umsatzsteuer-Voranmeldung (VAT pre-return)
  - ``USt``    — Umsatzsteuerjahreserklärung (E50, annual VAT return)
  - ``KSt``    — Körperschaftsteuererklärung (E30, corporate income tax)

Planned:
  - ``GewSt``     — Gewerbesteuer
  - ``JA``        — Jahresabschluss
  - ``eür``       — Einnahmen-Überschuss-Rechnung (EÜR / income-surplus statement)
  - ``anlage_n``  — Anlage N (employment income)
"""

from .kst import KStReport, generate_kst
from .ustva import USTVALineItem, USTVAReport, generate_ustva

__all__ = [
    "USTVAReport",
    "USTVALineItem",
    "generate_ustva",
    "KStReport",
    "generate_kst",
]
