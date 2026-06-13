"""
finamt.tax.elster
~~~~~~~~~~~~~~~~~
ELSTER XML submission for German tax filings.

Supported form types:
  - UStVA  (Umsatzsteuer-Voranmeldung)   — VAT pre-return
  - EÜR    (Einnahmen-Überschuss-Rechnung) — planned
  - E-Bilanz                              — planned

ELSTER transmission overview:
  1. Build the payload XML (NutzdatenXML) for the specific form.
  2. Wrap it in the ELSTER envelope (TransferHeader + DatenTeil).
  3. Sign the envelope using an ELSTER PKCS#12 certificate.
  4. POST the signed XML to the ELSTER server.
  5. Parse the Rückmeldung (acknowledgement) for success / error codes.

Certificates:
  Obtain a free ELSTER Organisationszertifikat at:
    https://www.elster.de/eportal/portal/honk#!

  Store it securely — never commit to version control.
  Pass path and password via environment variables or the ElsterConfig dataclass.

Dependencies (install with  pip install finamt[elster]):
  - lxml           (XML building + XPath)
  - cryptography   (PKCS#12 parsing, RSA signing)
  - requests       (HTTPS submission)

UStVA Kennzahlen (2024 form — verify against current official form):
  Ausgangsseite (sales):
    Kz 81   Lieferungen/Leistungen 19 %  — Bemessungsgrundlage (netto, ganze EUR)
    Kz 86   Lieferungen/Leistungen 7 %   — Bemessungsgrundlage
    Kz 35   Andere Steuersätze           — Bemessungsgrundlage
    Kz 36   Andere Steuersätze           — Steuerbetrag
  Vorsteuer (purchases):
    Kz 66   Abziehbare Vorsteuerbeträge  — gesamt
  Ergebnis:
    Kz 83   Verbleibende Vorauszahlung / Erstattung (computed by Finanzamt)

⚠  IMPORTANT:
  - Always test against the ELSTER test environment first (use_test=True).
  - Kennzahlen change annually — verify with the official Formulare on www.elster.de.
  - This module does NOT replace review by a Steuerberater.
  - Decimal amounts for Kz 81/86/35 must be rounded to whole euros (int) per ELSTER spec.

Usage::

    from finamt.tax.elster import ElsterConfig, ElsterClient
    from finamt.tax.ustva import generate_ustva

    config = ElsterConfig(
        cert_path="~/.finamt/elster.pfx",
        cert_password="my-secret",
        steuernummer="21/815/08150",    # Steuernummer from your Finanzamt
        finanzamt_nr="2181",             # 4-digit Finanzamtsnummer
        bundesland_kz="21",              # 2-digit Länderkennzeichen
    )

    client = ElsterClient(config, use_test=True)   # always start in test mode!
    result = client.submit_ustva(report, year=2024, period=1)  # period=1 → January
    print(result)
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from base64 import b64encode
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional imports — only needed for actual signing / submission
# ---------------------------------------------------------------------------

try:
    from lxml import etree

    _LXML_AVAILABLE = True
except ImportError:
    _LXML_AVAILABLE = False

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives.serialization import pkcs12

    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

try:
    import requests as _requests

    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

from .ustva import USTVAReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ELSTER endpoints
# ---------------------------------------------------------------------------

ELSTER_URL_PRODUCTION = "https://www.elster.de/ekona/upload/elster"
ELSTER_URL_TEST = "https://www.elster.de/ekona/upload/elstertest"

# Testmerker — signals the Finanzamt that this is a test submission
TESTMERKER = "700000004"

# ELSTER XML namespace (v11 — required by ERiC libcheckBilanz plugin)
NS = "http://www.elster.de/elsterxml/schema/v11"

# Product identification sent to ELSTER
PRODUKT_NAME = "finamt"
PRODUKT_VERSION = "0.1"

# Länderkennzeichen (2-digit numeric) → ELSTER <Ziel> code for TransferHeader
_BUNDESLAND_ZIEL: dict[str, str] = {
    "01": "SH",
    "02": "HH",
    "03": "NI",
    "04": "HB",
    "05": "NW",
    "06": "HE",
    "07": "RP",
    "08": "BW",
    "09": "BY",
    "10": "SL",
    "11": "BE",
    "12": "BB",
    "13": "MV",
    "14": "SN",
    "15": "ST",
    "16": "TH",
    # also accept 2-letter values passed directly
}


def _make_ticket() -> str:
    """Generate a transfer ticket matching ERiC regex ``[0-9a-km-z]{2}[0-9]{3}[0-9a-km-z]{27}``."""
    _alpha = "abcdefghijkmnopqrstuvwxyz0123456789"  # a-z minus 'l', plus digits
    _digits = "0123456789"
    part1 = "".join(random.choices(_alpha, k=2))
    part2 = "".join(random.choices(_digits, k=3))
    part3 = "".join(random.choices(_alpha, k=27))
    return part1 + part2 + part3


def _bundesland_ziel(bundesland_kz: str) -> str:
    """Return the 2-letter ELSTER <Ziel> code from a numeric Länderkennzeichen."""
    return _BUNDESLAND_ZIEL.get(bundesland_kz, bundesland_kz)


# city/state name → Länderkennzeichen (lower-cased for matching)
_CITY_TO_KZ: dict[str, str] = {
    # Stadtstaaten
    "berlin": "11",
    "hamburg": "02",
    "bremen": "04",
    "bremerhaven": "04",
    # Flächenländer – capitals + common aliases
    "kiel": "01",  # Schleswig-Holstein
    "schleswig-holstein": "01",
    "niedersachsen": "03",
    "hannover": "03",
    "nordrhein-westfalen": "05",
    "düsseldorf": "05",
    "köln": "05",
    "hessen": "06",
    "wiesbaden": "06",
    "frankfurt": "06",
    "rheinland-pfalz": "07",
    "mainz": "07",
    "baden-württemberg": "08",
    "stuttgart": "08",
    "bayern": "09",
    "munich": "09",
    "münchen": "09",
    "saarland": "10",
    "saarbrücken": "10",
    "brandenburg": "12",
    "potsdam": "12",
    "mecklenburg-vorpommern": "13",
    "schwerin": "13",
    "sachsen": "14",
    "dresden": "14",
    "sachsen-anhalt": "15",
    "magdeburg": "15",
    "thüringen": "16",
    "erfurt": "16",
}


def bundesland_kz_from_city(city: str) -> str:
    """
    Derive a numeric Länderkennzeichen from an (approximate) city or state name.
    Returns ``""`` when not recognised.
    """
    return _CITY_TO_KZ.get(city.strip().lower(), "")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ElsterConfig:
    """
    Configuration for ELSTER submissions.

    Parameters
    ----------
    cert_path:
        Path to the ELSTER PKCS#12 certificate file (.pfx or .p12).
        Obtain for free at https://www.elster.de/eportal/portal/honk#!
    cert_password:
        Password for the certificate.  Prefer passing via environment variable
        FINAMT_ELSTER_CERT_PASSWORD rather than hard-coding.
    steuernummer:
        Your company's Steuernummer in the format used by your Finanzamt,
        e.g. "21/815/08150" (Bayern) or "30/450/09999" (Berlin).
        Will be normalised to the 13-digit ELSTER format automatically.
    finanzamt_nr:
        4-digit Finanzamtsnummer, e.g. "2181" (München).
        Look up at: https://www.bzst.de/DE/Service/Behoerdenwegweiser/Finanzamtsuche
    bundesland_kz:
        2-digit Länderkennzeichen (state prefix of the Steuernummer).
        E.g. "21" for Bayern, "30" for Berlin, "22" for Brandenburg.
    """

    cert_path: str | Path
    cert_password: str
    steuernummer: str
    finanzamt_nr: str
    bundesland_kz: str
    hersteller_id: str = ""  # register at https://www.elster.de/eportal/softwareentwickler

    # Annual USt 2A sender / taxpayer address details
    company_name: str = ""  # Absender name + E3000901 (max 45)
    street: str = ""  # Straße for Vorsatz.AbsStr and Adr.E3001101
    house_number: str = ""  # Hausnummer for Adr.E3001203 (max 4)
    postal_code: str = ""  # PLZ for AbsPlz / Adr.E3001206 (5 digits)
    city: str = ""  # Ort for AbsOrt / Adr.E3001207
    besteuerungsart: str = "1"  # E3002203: 1=vereinbarte, 2=vereinnahmte, 3=mixed
    vorauszahlungssoll: Decimal = field(default_factory=lambda: Decimal("0"))

    @classmethod
    def from_env(cls) -> ElsterConfig:
        """Load config from environment variables."""
        return cls(
            cert_path=os.environ["FINAMT_ELSTER_CERT_PATH"],
            cert_password=os.environ["FINAMT_ELSTER_CERT_PASSWORD"],
            steuernummer=os.environ["FINAMT_ELSTER_STEUERNUMMER"],
            finanzamt_nr=os.environ["FINAMT_ELSTER_FINANZAMT_NR"],
            bundesland_kz=os.environ["FINAMT_ELSTER_BUNDESLAND_KZ"],
            hersteller_id=os.environ.get("FINAMT_ELSTER_HERSTELLER_ID", ""),
        )


# ---------------------------------------------------------------------------
# Submission result
# ---------------------------------------------------------------------------


@dataclass
class SubmissionResult:
    success: bool
    telenummer: str | None = None  # ELSTER transfer ticket number
    error_code: str | None = None
    error_message: str | None = None
    raw_response: str | None = None

    def __str__(self) -> str:
        if self.success:
            return f"✓ Übermittlung erfolgreich — Telenummer: {self.telenummer}"
        return f"✗ Fehler {self.error_code}: {self.error_message}"


# ---------------------------------------------------------------------------
# Steuernummer normalisation
# ---------------------------------------------------------------------------
#
# Official conversion table (Bundesministerium der Finanzen):
# Bundesland             Local format         Unified 13-digit
# Baden-Württemberg      FF/BBB/UUUUP         28FF0BBBUUUUP
# Bayern                 FFF/BBB/UUUUP         9FFF0BBBUUUUP
# Berlin                 FF/BBB/UUUUP         11FF0BBBUUUUP
# Brandenburg            0FF/BBB/UUUUP        30FF0BBBUUUUP
# Bremen                 FF/BBB/UUUUP         24FF0BBBUUUUP
# Hamburg                FF/BBB/UUUUP         22FF0BBBUUUUP
# Hessen                 0FF/BBB/UUUUP        26FF0BBBUUUUP
# Mecklenburg-Vorpommern 0FF/BBB/UUUUP        40FF0BBBUUUUP
# Niedersachsen          FF/BBB/UUUUP         23FF0BBBUUUUP
# Nordrhein-Westfalen    FFF/BBBB/UUUP         5FFF0BBBBUUUP
# Rheinland-Pfalz        FF/BBB/UUUUP         27FF0BBBUUUUP
# Saarland               0FF/BBB/UUUUP        10FF0BBBUUUUP
# Sachsen                2FF/BBB/UUUUP        32FF0BBBUUUUP
# Sachsen-Anhalt         1FF/BBB/UUUUP        31FF0BBBUUUUP
# Schleswig-Holstein     FF/BBB/UUUUP         21FF0BBBUUUUP
# Thüringen              1FF/BBB/UUUUP        41FF0BBBUUUUP
#
# Key: bundesland_kz as used by the caller → (bl_prefix_in_unified, fa_offset, fa_len)
#   fa_offset: how many leading local digits to skip before the FA part
#   fa_len:    number of FA digits in the unified number
# The inserted '0' always goes between FA and the remaining (Bezirk+Prüfziffer) digits.
_BL_STRUCTURE: dict[str, tuple[str, int, int]] = {
    "28": ("28", 0, 2),  # Baden-Württemberg:       FF/BBB/UUUUP
    "08": ("28", 0, 2),  # Baden-Württemberg alt kz
    "9":  ("9",  0, 3),  # Bayern:                 FFF/BBB/UUUUP
    "09": ("9",  0, 3),  # Bayern alt kz
    "11": ("11", 0, 2),  # Berlin:                  FF/BBB/UUUUP
    "30": ("30", 1, 2),  # Brandenburg:            0FF/BBB/UUUUP
    "12": ("30", 1, 2),  # Brandenburg alt kz
    "24": ("24", 0, 2),  # Bremen:                  FF/BBB/UUUUP
    "04": ("24", 0, 2),  # Bremen alt kz
    "22": ("22", 0, 2),  # Hamburg:                 FF/BBB/UUUUP
    "02": ("22", 0, 2),  # Hamburg alt kz
    "26": ("26", 1, 2),  # Hessen:                 0FF/BBB/UUUUP
    "06": ("26", 1, 2),  # Hessen alt kz
    "40": ("40", 1, 2),  # Mecklenburg-Vorpommern: 0FF/BBB/UUUUP
    "13": ("40", 1, 2),  # Mecklenburg-Vorpommern alt kz
    "23": ("23", 0, 2),  # Niedersachsen:           FF/BBB/UUUUP
    "03": ("23", 0, 2),  # Niedersachsen alt kz
    "5":  ("5",  0, 3),  # Nordrhein-Westfalen:    FFF/BBBB/UUUP
    "05": ("5",  0, 3),  # Nordrhein-Westfalen alt kz
    "27": ("27", 0, 2),  # Rheinland-Pfalz:         FF/BBB/UUUUP
    "07": ("27", 0, 2),  # Rheinland-Pfalz alt kz
    "10": ("10", 1, 2),  # Saarland:               0FF/BBB/UUUUP
    "32": ("32", 1, 2),  # Sachsen:                2FF/BBB/UUUUP
    "14": ("32", 1, 2),  # Sachsen alt kz
    "31": ("31", 1, 2),  # Sachsen-Anhalt:         1FF/BBB/UUUUP
    "15": ("31", 1, 2),  # Sachsen-Anhalt alt kz
    "21": ("21", 0, 2),  # Schleswig-Holstein:      FF/BBB/UUUUP
    "01": ("21", 0, 2),  # Schleswig-Holstein alt kz
    "41": ("41", 1, 2),  # Thüringen:              1FF/BBB/UUUUP
    "16": ("41", 1, 2),  # Thüringen alt kz
}


def normalise_steuernummer(raw: str, bundesland_kz: str) -> str:
    """
    Normalise a Steuernummer to the 13-digit ELSTER unified format.

    Applies the official BMF conversion table.  The unified 13-digit number
    is assembled as:  bl_prefix + FA + '0' + Bezirk+Prüfziffer.

    Pass the 13-digit form directly (returned unchanged) if already normalised.

    Reference: Bundesministerium der Finanzen — Steuernummer-Aufbau
    """
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 13:
        return digits

    struct = _BL_STRUCTURE.get(bundesland_kz)
    if struct is None:
        # Unknown state: left-pad local digits to 11 and prepend BL as-is
        local = digits.zfill(11)
        return bundesland_kz + local

    bl_prefix, fa_offset, fa_len = struct
    # rest_expected = digits after FA in the unified number (between '0' and end)
    rest_expected = 13 - len(bl_prefix) - fa_len - 1  # subtract BL, FA, and the '0'

    local = digits[fa_offset:]          # skip leading state-specific digit(s)
    fa = local[:fa_len]                 # Finanzamt digits
    rest = local[fa_len:]               # Bezirk + Prüfziffer
    rest = rest.zfill(rest_expected)    # left-pad if input was short

    return bl_prefix + fa + "0" + rest


# ---------------------------------------------------------------------------
# UStVA Kennzahlen mapping
# ---------------------------------------------------------------------------


def _ustva_kennzahlen(report: USTVAReport) -> dict[str, str]:
    """
    Map USTVAReport figures to UStVA Kennzahlen.

    Amounts for Kz 81/86/35 are rounded DOWN to whole euros per ELSTER spec.
    VAT amounts are rounded to 2 decimal places (cents).

    ⚠  Verify these mappings against the current official UStVA form on www.elster.de.
    """

    def whole(d: Decimal) -> str:
        """Round down to whole euros, return as string without decimal point."""
        return str(int(d.quantize(Decimal("1"), rounding=ROUND_DOWN)))

    def cents(d: Decimal) -> str:
        return f"{d:.2f}"

    kz: dict[str, str] = {}

    # Standard tax rates
    ln19 = report.line_19
    if ln19 and ln19.sale_net > 0:
        kz["Kz81"] = whole(ln19.sale_net)  # Umsätze 19 % — Bemessungsgrundlage

    ln7 = report.line_7
    if ln7 and ln7.sale_net > 0:
        kz["Kz86"] = whole(ln7.sale_net)  # Umsätze 7 % — Bemessungsgrundlage

    # Other rates (Kz 35 / Kz 36)
    for rate_key, ln in report.lines.items():
        if rate_key not in ("19", "7", "unknown") and ln.sale_net > 0:
            kz["Kz35"] = kz.get("Kz35", "")
            kz["Kz36"] = kz.get("Kz36", "")
            # Accumulate if multiple non-standard rates
            prev_net = Decimal(kz["Kz35"]) if kz["Kz35"] else Decimal("0")
            prev_tax = Decimal(kz["Kz36"]) if kz["Kz36"] else Decimal("0")
            kz["Kz35"] = whole(prev_net + ln.sale_net)
            kz["Kz36"] = cents(prev_tax + ln.sale_vat)

    # Input tax (Vorsteuer) — all rates combined in Kz 66
    if report.total_input_vat > 0:
        kz["Kz66"] = cents(report.total_input_vat)

    return kz


# ---------------------------------------------------------------------------
# XML Builder
# ---------------------------------------------------------------------------


class ElsterXMLBuilder:
    """
    Builds the ELSTER XML envelope for a tax form submission.

    The ELSTER v12 envelope structure:
      <Elster>
        <TransferHeader>          — metadata, certificate reference, signature placeholder
        <DatenTeil>
          <Nutzdatenblock>
            <NutzdatenHeader>     — ticket, recipient Finanzamt, product info
            <Nutzdaten>           — the actual form data (UStVA, EÜR, ...)
    """

    def __init__(self, config: ElsterConfig) -> None:
        if not _LXML_AVAILABLE:
            raise ImportError(
                "lxml is required for ELSTER XML generation. "
                "Install with: pip install finamt[elster]"
            )
        self.config = config

    def _ns(self, tag: str) -> str:
        return f"{{{NS}}}{tag}"

    def build_ustva(
        self,
        report: USTVAReport,
        year: int,
        period: int,
        is_berichtigung: bool = False,
        use_test: bool = True,
    ) -> bytes:
        """
        Build the ELSTER XML for a UStVA submission.

        Parameters
        ----------
        report:
            The USTVAReport to submit.
        year:
            Fiscal year, e.g. 2024.
        period:
            Reporting period:
              1–12  → monthly (Monatszahler)
              41    → Q1 (January–March)
              42    → Q2 (April–June)
              43    → Q3 (July–September)
              44    → Q4 (October–December)
        is_berichtigung:
            True if this is an amended return (Berichtigte Voranmeldung).
        use_test:
            True → include Testmerker (test submission, not legally binding).
        """
        ticket = _make_ticket()
        steuernr = normalise_steuernummer(self.config.steuernummer, self.config.bundesland_kz)
        if len(steuernr) != 13:
            raise ValueError(
                f"Cannot normalise Steuernummer '{self.config.steuernummer}' to 13 digits. "
                "Either pass bundesland_kz (e.g. '11' for Berlin) or supply the "
                "13-digit ELSTER form directly (e.g. '1137053950531')."
            )
        # Derive bundesland_kz from the normalised steuernummer prefix if not given
        bund_kz = self.config.bundesland_kz or steuernr[:2]
        # period=0 → annual Umsatzsteuerjahreserklärung (USt 2A)
        # period>0 → Umsatzsteuervoranmeldung (UStVA)
        is_annual = period == 0
        # BUFA = first 4 digits of the 13-digit normalised steuernummer
        # For annual E50, ERiC validates NutzdatenHeader/Empfaenger matches Vorsatz/StNr
        # prefix — always derive from steuernr to guarantee consistency.
        fa_nr = steuernr[:4] if is_annual else (self.config.finanzamt_nr or steuernr[:4])

        # Helper: Clark-notation tag in the ELSTER namespace
        def _t(tag: str) -> str:
            return f"{{{NS}}}{tag}"

        root = etree.Element(_t("Elster"), nsmap={None: NS})

        # ── TransferHeader ────────────────────────────────────────────
        daten_art = "USt" if is_annual else "UStVA"

        # Annual USt uses "ElsterErklaerung"; periodic UStVA uses "ElsterAnmeldung"
        verfahren = "ElsterErklaerung" if is_annual else "ElsterAnmeldung"
        th = etree.SubElement(root, _t("TransferHeader"), version="11")
        etree.SubElement(th, _t("Verfahren")).text = verfahren
        etree.SubElement(th, _t("DatenArt")).text = daten_art
        etree.SubElement(th, _t("Vorgang")).text = "send-Auth"
        etree.SubElement(th, _t("TransferTicket")).text = ticket
        if use_test:
            etree.SubElement(th, _t("Testmerker")).text = TESTMERKER
        emp_th = etree.SubElement(th, _t("Empfaenger"), id="L")  # L = Landesfinanzbehörde
        etree.SubElement(emp_th, _t("Ziel")).text = _bundesland_ziel(bund_kz)
        etree.SubElement(th, _t("HerstellerID")).text = self.config.hersteller_id
        etree.SubElement(th, _t("DatenLieferant")).text = steuernr
        datei = etree.SubElement(th, _t("Datei"))
        etree.SubElement(datei, _t("Verschluesselung")).text = "CMSEncryptedData"
        etree.SubElement(datei, _t("Kompression")).text = "GZIP"
        etree.SubElement(datei, _t("TransportSchluessel"))

        # ── DatenTeil ─────────────────────────────────────────────────
        dt = etree.SubElement(root, _t("DatenTeil"))
        ndb = etree.SubElement(dt, _t("Nutzdatenblock"))

        # NutzdatenHeader
        ndh = etree.SubElement(ndb, _t("NutzdatenHeader"), version="11")
        etree.SubElement(ndh, _t("NutzdatenTicket")).text = ticket
        etree.SubElement(ndh, _t("Empfaenger"), id="F").text = fa_nr

        # Nutzdaten payload
        nd = etree.SubElement(ndb, _t("Nutzdaten"))

        if is_annual:
            self._build_ust_annual_e50(nd, report, year, steuernr)
        else:
            kz = _ustva_kennzahlen(report)
            anm = etree.SubElement(nd, _t("Anmeldungssteuern"), art="UStVA", version=f"{year}01")
            sf = etree.SubElement(anm, _t("Steuerfall"))
            ustva = etree.SubElement(sf, _t("Umsatzsteuervoranmeldung"))
            etree.SubElement(ustva, _t("Jahr")).text = str(year)
            etree.SubElement(ustva, _t("Zeitraum")).text = str(period).zfill(2)
            etree.SubElement(ustva, _t("Steuernummer")).text = steuernr
            etree.SubElement(ustva, _t("Kz09")).text = self.config.finanzamt_nr
            etree.SubElement(ustva, _t("Kz10")).text = "1" if is_berichtigung else "0"
            for kz_name, kz_value in kz.items():
                etree.SubElement(ustva, _t(kz_name)).text = kz_value

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    # ------------------------------------------------------------------
    # E50 — Umsatzsteuerjahreserklärung (annual USt 2A)
    # ------------------------------------------------------------------

    def _build_ust_annual_e50(
        self,
        nd: etree._Element,
        report: USTVAReport,
        year: int,
        steuernr: str,
    ) -> None:
        """Build the E50 annual USt XML subtree directly into *nd* (Nutzdaten element)."""
        cfg = self.config
        e50_ns = f"http://finkonsens.de/elster/elstererklaerung/ust/e50/v{year}"

        def _e(tag: str) -> str:
            return f"{{{e50_ns}}}{tag}"

        e50 = etree.SubElement(nd, _e("E50"), nsmap={None: e50_ns}, version=str(year))

        # ── Vorsatz ───────────────────────────────────────────────────
        # E50 Vorsatz/StNr expects the 13-digit bundeseinheitliche format.
        # ERiC validates that digits 1-4 (= BUFA) match NutzdatenHeader/Empfaenger.
        # e.g. Berlin 1137053950531 → first 4 digits = 1137 = Empfaenger ✓
        vor = etree.SubElement(e50, _e("Vorsatz"))
        etree.SubElement(vor, _e("Unterfallart")).text = "50"
        etree.SubElement(vor, _e("Vorgang")).text = "01"
        etree.SubElement(vor, _e("StNr")).text = steuernr
        etree.SubElement(vor, _e("Zeitraum")).text = str(year)
        etree.SubElement(vor, _e("AbsName")).text = (cfg.company_name or steuernr).strip()[:45]
        abs_str = f"{cfg.street} {cfg.house_number}".strip()[:30]
        etree.SubElement(vor, _e("AbsStr")).text = abs_str
        etree.SubElement(vor, _e("AbsPlz")).text = (cfg.postal_code or "00000")[:5]
        etree.SubElement(vor, _e("AbsOrt")).text = (cfg.city or "")[:29]
        etree.SubElement(vor, _e("Copyright")).text = "finamt"
        etree.SubElement(vor, _e("OrdNrArt")).text = "S"
        rueck = etree.SubElement(vor, _e("Rueckuebermittlung"))
        # Bescheid=2: no Bescheid download — avoids requiring ArtDerAdresse=INTERNET
        etree.SubElement(rueck, _e("Bescheid")).text = "2"

        # ── USt2A ─────────────────────────────────────────────────────
        ust2a = etree.SubElement(e50, _e("USt2A"))

        # Allg / Unternehmen
        allg = etree.SubElement(ust2a, _e("Allg"))
        untern = etree.SubElement(allg, _e("Unternehmen"))
        etree.SubElement(untern, _e("E3000901")).text = (cfg.company_name or "").strip()[:45]
        adr = etree.SubElement(untern, _e("Adr"))
        etree.SubElement(adr, _e("E3001101")).text = cfg.street or ""
        # Hausnummer field exists in all years
        if cfg.house_number:
            etree.SubElement(adr, _e("E3001203")).text = cfg.house_number[:4]
        # PLZ/Ort: 2022 schema uses E3001201 (combined "PLZ Ort");
        # 2023+ schema uses separate E3001206 (PLZ) and E3001207 (Ort)
        if year >= 2023:
            if cfg.postal_code:
                etree.SubElement(adr, _e("E3001206")).text = cfg.postal_code[:5]
            etree.SubElement(adr, _e("E3001207")).text = cfg.city or ""
        else:
            plz_ort = f"{cfg.postal_code} {cfg.city}".strip()
            etree.SubElement(adr, _e("E3001201")).text = plz_ort
        best_art = etree.SubElement(allg, _e("Best_Art"))
        etree.SubElement(best_art, _e("E3002203")).text = cfg.besteuerungsart or "1"

        # ERiC requires Straße + PLZ + Ort to be non-empty together
        if not all([cfg.street, cfg.postal_code, cfg.city]):
            raise ValueError(
                "Annual USt (E50) requires complete company address: "
                "set ElsterConfig.street, .postal_code and .city  "
                "(or pass them via the API request body / taxpayer profile)."
            )

        # Helpers
        def _dec(v: Decimal) -> str:
            return str(v.quantize(Decimal("0.01"))).replace(".", ",")

        def _int(v: Decimal) -> str:
            return str(int(v.to_integral_value(rounding=ROUND_DOWN)))

        # Compute values from report
        ln19 = report.line_19
        basis_19 = (ln19.sale_net if ln19 else Decimal("0")) or Decimal("0")
        vat_19 = (ln19.sale_vat if ln19 else Decimal("0")) or Decimal("0")
        vat_19 = vat_19.quantize(Decimal("0.01"))

        ln7 = report.line_7
        basis_7 = (ln7.sale_net if ln7 else Decimal("0")) or Decimal("0")
        vat_7 = (ln7.sale_vat if ln7 else Decimal("0")) or Decimal("0")
        vat_7 = vat_7.quantize(Decimal("0.01"))

        output_vat = (vat_19 + vat_7).quantize(Decimal("0.01"))
        input_vat = report.total_input_vat.quantize(Decimal("0.01"))
        einfuhr_vat = (report.einfuhr_vat or Decimal("0")).quantize(Decimal("0.01"))
        net = (output_vat - input_vat).quantize(Decimal("0.01"))
        vorausz = cfg.vorauszahlungssoll.quantize(Decimal("0.01"))
        abschluss = (net - vorausz).quantize(Decimal("0.01"))

        # Umsaetze — only write when there are taxable sales
        # The Tabelle wrapper inside Umsaetze/Abz_VoSt/Berech_USt was introduced in
        # the 2023 schema; in 2022 (and earlier) these elements directly contain
        # their children without an intermediate Tabelle element.
        _use_tabelle = year >= 2023
        has_ums_detail = False
        if output_vat > 0:
            umsaetze = etree.SubElement(ust2a, _e("Umsaetze"))
            tab_u = etree.SubElement(umsaetze, _e("Tabelle")) if _use_tabelle else umsaetze
            if basis_19 > 0:
                has_ums_detail = True
                ums_allg = etree.SubElement(tab_u, _e("Ums_allg"))
                etree.SubElement(ums_allg, _e("E3003303")).text = _int(basis_19)
                etree.SubElement(ums_allg, _e("E3003304")).text = _dec(vat_19)
            if basis_7 > 0:
                has_ums_detail = True
                ums_erm = etree.SubElement(tab_u, _e("Ums_erm"))
                etree.SubElement(ums_erm, _e("E3004401")).text = _int(basis_7)
                etree.SubElement(ums_erm, _e("E3004402")).text = _dec(vat_7)
            if has_ums_detail:
                # Ums_Sum only when at least one detail row is present
                ums_sum = etree.SubElement(tab_u, _e("Ums_Sum"))
                etree.SubElement(ums_sum, _e("E3006001")).text = _dec(output_vat)

        # Abz_VoSt — only write when there is input VAT to deduct
        invoice_vat = input_vat - einfuhr_vat
        if input_vat > 0:
            abz = etree.SubElement(ust2a, _e("Abz_VoSt"))
            tab_v = etree.SubElement(abz, _e("Tabelle")) if _use_tabelle else abz
            if invoice_vat > 0:
                etree.SubElement(tab_v, _e("E3006201")).text = _dec(invoice_vat)
            if einfuhr_vat > 0:
                etree.SubElement(tab_v, _e("E3006401")).text = _dec(einfuhr_vat)
            abz_sum = etree.SubElement(tab_v, _e("Abz_VoSt_Sum"))
            etree.SubElement(abz_sum, _e("E3006901")).text = _dec(input_vat)

        # Berech_USt — calculation cross-reference section
        # E3009201 (Zeile 102) = output VAT transferred from Ums_Sum; always written,
        #   even as 0,00 when there are no sales. The ELSTER portal always sends this
        #   field regardless of whether a Umsaetze section exists.
        # E3009801 (Zeile 107) = Zwischensumme; always written alongside E3009201.
        #   ERiC rule 30905/30452: if E3009801 is present, E3009201 must also be present.
        #   Writing both as 0,00 when output_vat=0 matches what the ELSTER portal does.
        # E3009701/E3010001 are §15a adjustment fields — omitted unless §15a data exists.
        if output_vat > 0 or input_vat > 0:
            berech = etree.SubElement(ust2a, _e("Berech_USt"))
            tab_b = etree.SubElement(berech, _e("Tabelle")) if _use_tabelle else berech
            # Always write Zeile 102 + Zeile 107 (both 0,00 when no sales)
            etree.SubElement(tab_b, _e("E3009201")).text = _dec(output_vat)
            etree.SubElement(tab_b, _e("E3009801")).text = _dec(output_vat)
            if input_vat > 0:
                etree.SubElement(tab_b, _e("E3009901")).text = _dec(input_vat)
            etree.SubElement(tab_b, _e("E3010201")).text = _dec(net)
            # Zeile 115 (E3010401) = Überschuss when net < 0
            # Zeile 116 (E3010501) = zu entrichtende USt when net > 0
            # ERiC rules 30910/30914 require the corresponding field to be present
            if net < 0:
                # E3010401 is typed DezimalzahlNichtNeg — must be the absolute value;
                # ERiC rejects negative values and treats the field as absent (→ 30910/30914).
                etree.SubElement(tab_b, _e("E3010401")).text = _dec(abs(net))
            elif net > 0:
                etree.SubElement(tab_b, _e("E3010501")).text = _dec(net)
            verbl = etree.SubElement(tab_b, _e("Verbl_USt"))
            etree.SubElement(verbl, _e("E3011101")).text = _dec(net)
            etree.SubElement(verbl, _e("E3011301")).text = _dec(vorausz)
            zahl = etree.SubElement(tab_b, _e("Zahl_Erstatt"))
            etree.SubElement(zahl, _e("E3011401")).text = _dec(abschluss)


# ---------------------------------------------------------------------------
# Signer
# ---------------------------------------------------------------------------


class ElsterSigner:
    """
    Signs an ELSTER XML document using a PKCS#12 certificate.

    ELSTER uses a simplified XML signature scheme:
      1. Compute SHA-256 digest of the NutzdatenXML (Nutzdaten element).
      2. Sign the digest with the private key from the certificate (RSA-SHA256).
      3. Insert DigestValue, SignatureValue, and the X.509 certificate (DER, base64)
         into the TransferHeader/Signaturen/Signatur element.

    ⚠  This is a simplified implementation of ELSTER's signing protocol.
       The official ERiC library handles additional steps (e.g. challenge-response
       for server-side validation).  For production use, validate against the
       official ELSTER documentation and test portal before filing.
    """

    def __init__(self, config: ElsterConfig) -> None:
        if not _CRYPTO_AVAILABLE:
            raise ImportError(
                "cryptography is required for ELSTER signing. "
                "Install with: pip install finamt[elster]"
            )
        cert_path = Path(config.cert_path).expanduser()
        with open(cert_path, "rb") as f:
            pfx_data = f.read()
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            pfx_data, config.cert_password.encode()
        )
        self._private_key = private_key
        self._certificate = certificate

    def sign(self, xml_bytes: bytes) -> bytes:
        """
        Insert signature values into the ELSTER XML envelope.

        Modifies the placeholder DigestValue / SignatureValue / X509Certificate
        nodes that ElsterXMLBuilder inserts.
        """
        if not _LXML_AVAILABLE:
            raise ImportError("lxml is required for XML signing.")

        tree = etree.fromstring(xml_bytes)

        # Locate the Nutzdaten element — this is what we sign
        nutzdaten_nodes = tree.xpath("//*[local-name()='Nutzdaten']")
        if not nutzdaten_nodes:
            raise ValueError("No <Nutzdaten> element found in XML.")
        nutzdaten_xml = etree.tostring(nutzdaten_nodes[0], encoding="UTF-8")

        # 1. Digest
        digest = hashlib.sha256(nutzdaten_xml).digest()
        digest_b64 = b64encode(digest).decode()

        # 2. Sign digest with private key
        signature = self._private_key.sign(
            digest,
            asym_padding.PKCS1v15(),
            hashes.SHA256(),
        )
        sig_b64 = b64encode(signature).decode()

        # 3. DER-encode certificate, base64
        cert_der = self._certificate.public_bytes(serialization.Encoding.DER)
        cert_b64 = b64encode(cert_der).decode()

        # 4. Fill ALL placeholder nodes (TransferHeader Signatur + SigUser)
        def fill_all(xpath: str, value: str) -> None:
            for node in tree.xpath(f"//*[local-name()='{xpath}']"):
                node.text = value

        fill_all("DigestValue", digest_b64)
        fill_all("SignatureValue", sig_b64)
        fill_all("X509Certificate", cert_b64)

        return etree.tostring(tree, xml_declaration=True, encoding="UTF-8", pretty_print=False)


# ---------------------------------------------------------------------------
# HTTP Client
# ---------------------------------------------------------------------------


class ElsterClient:
    """
    Submits signed ELSTER XML to the ELSTER server and parses the response.

    Parameters
    ----------
    config:
        ElsterConfig instance.
    use_test:
        True  → submit to test endpoint (Testmerker 700000004, not legally binding).
        False → submit to production endpoint — real filing!
    """

    def __init__(self, config: ElsterConfig, use_test: bool = True) -> None:
        if not _REQUESTS_AVAILABLE:
            raise ImportError(
                "requests is required for ELSTER submission. "
                "Install with: pip install finamt[elster]"
            )
        self.config = config
        self.use_test = use_test
        self._builder = ElsterXMLBuilder(config)
        self._signer = ElsterSigner(config)
        self._url = ELSTER_URL_TEST if use_test else ELSTER_URL_PRODUCTION

        if not use_test:
            import warnings

            warnings.warn(
                "ElsterClient is in PRODUCTION mode. Submissions are legally binding.",
                stacklevel=2,
            )

    def submit_ustva(
        self,
        report: USTVAReport,
        year: int,
        period: int,
        is_berichtigung: bool = False,
        timeout: int = 30,
    ) -> SubmissionResult:
        """
        Build, sign, and submit a UStVA.

        Parameters
        ----------
        report:
            Computed USTVAReport for the period.
        year:
            Fiscal year.
        period:
            1–12 (monthly) or 41–44 (quarterly).
        is_berichtigung:
            True = amended return.
        timeout:
            HTTP request timeout in seconds.
        """
        # 1. Build XML
        xml_unsigned = self._builder.build_ustva(
            report,
            year,
            period,
            is_berichtigung=is_berichtigung,
            use_test=self.use_test,
        )

        # 2. Sign
        xml_signed = self._signer.sign(xml_unsigned)

        # 3. Submit
        return self._post(xml_signed, timeout=timeout)

    def _post(self, xml_bytes: bytes, timeout: int) -> SubmissionResult:
        """POST the signed XML and parse the ELSTER Rückmeldung."""
        import os as _os
        import tempfile

        # Always dump to a temp file for debugging
        debug_path = _os.path.join(tempfile.gettempdir(), "elster_last_sent.xml")
        try:
            with open(debug_path, "wb") as _f:
                _f.write(xml_bytes)
        except Exception:
            pass
        try:
            resp = _requests.post(
                self._url,
                data=xml_bytes,
                headers={"Content-Type": "text/xml; charset=UTF-8"},
                timeout=timeout,
            )
            raw = resp.text
        except Exception as exc:
            return SubmissionResult(
                success=False,
                error_code="HTTP_ERROR",
                error_message=str(exc),
            )

        # Detect HTML error page (server rejected the request before XML parsing)
        if raw.lstrip().startswith(("<!DOCTYPE", "<html", "<HTML")):
            return SubmissionResult(
                success=False,
                error_code=f"HTTP_{resp.status_code}",
                error_message=(
                    f"Server returned HTML instead of XML (HTTP {resp.status_code}). "
                    "The ELSTER server rejected the request. "
                    f"Sent XML saved to: {debug_path}"
                ),
            )

        return self._parse_response(raw)

    @staticmethod
    def _parse_response(raw: str) -> SubmissionResult:
        """
        Parse the ELSTER server Rückmeldung XML.

        Success response contains:
          <TransferTicket>  — the Telenummer / filing reference
          <Erfolg>
            <Telenummer>

        Error response contains:
          <Fehler>
            <Code>
            <Meldung>
        """
        if not _LXML_AVAILABLE:
            # Fallback: basic string search
            if "<Telenummer>" in raw:
                start = raw.index("<Telenummer>") + len("<Telenummer>")
                end = raw.index("</Telenummer>")
                return SubmissionResult(success=True, telenummer=raw[start:end], raw_response=raw)
            return SubmissionResult(
                success=False, error_message="Unbekannte Antwort", raw_response=raw
            )

        try:
            tree = etree.fromstring(raw.encode())
        except etree.XMLSyntaxError:
            return SubmissionResult(
                success=False,
                error_code="PARSE_ERROR",
                error_message=f"Ungültige XML-Antwort: {raw[:200]}",
                raw_response=raw,
            )

        def text(xpath: str) -> str | None:
            nodes = tree.xpath(f"//*[local-name()='{xpath}']")
            return nodes[0].text if nodes else None

        telenummer = text("Telenummer")
        error_code = text("Code")
        error_msg = text("Meldung")

        if telenummer:
            return SubmissionResult(success=True, telenummer=telenummer, raw_response=raw)

        return SubmissionResult(
            success=False,
            error_code=error_code or "UNKNOWN",
            error_message=error_msg or "Keine Fehlermeldung in der Antwort",
            raw_response=raw,
        )

    # ------------------------------------------------------------------
    # Convenience: save signed XML without submitting (for inspection)
    # ------------------------------------------------------------------

    def export_ustva_xml(
        self,
        report: USTVAReport,
        year: int,
        period: int,
        path: str | Path,
        is_berichtigung: bool = False,
    ) -> Path:
        """
        Build and sign the UStVA XML, save to file — but do NOT submit.
        Useful for manual review before filing.
        """
        xml_unsigned = self._builder.build_ustva(
            report,
            year,
            period,
            is_berichtigung=is_berichtigung,
            use_test=self.use_test,
        )
        xml_signed = self._signer.sign(xml_unsigned)
        out = Path(path)
        out.write_bytes(xml_signed)
        return out


# ---------------------------------------------------------------------------
# E-Bilanz envelope builder (XBRL wrapped in ELSTER v12)
# ---------------------------------------------------------------------------


class EBilanzEnvelopeBuilder:
    """
    Wraps an XBRL instance document in the ELSTER v12 transmission envelope
    required for E-Bilanz (§ 5b EStG) submission via ERiC.

    The envelope uses:
      Verfahren  →  ElsterBilanz
      DatenArt   →  Bilanz
      ERiC datenartVersion  →  Bilanz_6_9  (HGB taxonomy v6, latest plugin)
    """

    #: ERiC datenartVersion string that selects the Bilanz validation plugin.
    #: Matches libcheckBilanz_6_9.dylib shipped in ERiC 43.x
    DATENART_VERSION = "Bilanz_6_9"

    def __init__(self, config: ElsterConfig) -> None:
        if not _LXML_AVAILABLE:
            raise ImportError(
                "lxml is required for E-Bilanz envelope building. Install with: pip install lxml"
            )
        self.config = config

    def build(
        self,
        xbrl_bytes: bytes,
        year: int,
        use_test: bool = True,
    ) -> bytes:
        """
        Wrap *xbrl_bytes* (a valid XBRL instance) in the ELSTER envelope.

        Parameters
        ----------
        xbrl_bytes:
            UTF-8 encoded XBRL XML produced by ``finamt.tax.ebilanz.build_xbrl``.
        year:
            Fiscal year (used in the NutzdatenHeader Veranlagungszeitraum).
        use_test:
            True → include Testmerker 700000004 (not legally binding).

        Returns
        -------
        UTF-8 bytes of the full Elster XML envelope ready for ERiC.
        """
        ticket = _make_ticket()
        steuernr = normalise_steuernummer(self.config.steuernummer, self.config.bundesland_kz)
        if len(steuernr) != 13:
            raise ValueError(
                f"Cannot normalise Steuernummer '{self.config.steuernummer}' to 13 digits. "
                "Either pass bundesland_kz (e.g. '11' for Berlin) or supply the "
                "13-digit ELSTER form directly (e.g. '1137053950531')."
            )
        # Derive bundesland_kz from the normalised steuernummer prefix if not given
        bund_kz = self.config.bundesland_kz or steuernr[:2]
        # BUFA = first 4 digits of the 13-digit normalised steuernummer
        fa_nr = self.config.finanzamt_nr or steuernr[:4]

        # Helper: Clark-notation tag in the ELSTER namespace
        def _t(tag: str) -> str:
            return f"{{{NS}}}{tag}"

        root = etree.Element(_t("Elster"), nsmap={None: NS})

        # ── TransferHeader ────────────────────────────────────────────
        th = etree.SubElement(root, _t("TransferHeader"), version="11")
        etree.SubElement(th, _t("Verfahren")).text = "ElsterBilanz"
        etree.SubElement(th, _t("DatenArt")).text = "Bilanz"
        etree.SubElement(th, _t("Vorgang")).text = "send-Auth"
        etree.SubElement(th, _t("TransferTicket")).text = ticket
        if use_test:
            etree.SubElement(th, _t("Testmerker")).text = TESTMERKER
        emp_th = etree.SubElement(th, _t("Empfaenger"), id="L")
        etree.SubElement(emp_th, _t("Ziel")).text = _bundesland_ziel(bund_kz)
        etree.SubElement(th, _t("HerstellerID")).text = self.config.hersteller_id
        etree.SubElement(th, _t("DatenLieferant")).text = self.config.steuernummer
        datei = etree.SubElement(th, _t("Datei"))
        etree.SubElement(datei, _t("Verschluesselung")).text = "keine"
        etree.SubElement(datei, _t("Kompression")).text = "keine"
        etree.SubElement(datei, _t("TransportSchluessel"))

        # ── DatenTeil ─────────────────────────────────────────────────
        dt = etree.SubElement(root, _t("DatenTeil"))
        ndb = etree.SubElement(dt, _t("Nutzdatenblock"))

        # NutzdatenHeader
        ndh = etree.SubElement(ndb, _t("NutzdatenHeader"), version="11")
        etree.SubElement(ndh, _t("NutzdatenTicket")).text = ticket
        etree.SubElement(ndh, _t("Empfaenger"), id="F").text = fa_nr
        herst = etree.SubElement(ndh, _t("Hersteller"))
        etree.SubElement(herst, _t("ProduktName")).text = PRODUKT_NAME
        etree.SubElement(herst, _t("ProduktVersion")).text = PRODUKT_VERSION

        # Nutzdaten — XBRL content embedded as child XML
        nd = etree.SubElement(ndb, _t("Nutzdaten"))
        try:
            xbrl_tree = etree.fromstring(xbrl_bytes)
            nd.append(xbrl_tree)
        except etree.XMLSyntaxError as exc:
            raise ValueError(f"Invalid XBRL XML: {exc}") from exc

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ---------------------------------------------------------------------------
# ERiC-based ELSTER client (E-Bilanz)
# ---------------------------------------------------------------------------


class ElsterEricClient:
    """
    Submit an E-Bilanz (XBRL Jahresabschluss, § 5b EStG) to ELSTER via ERiC.

    This class uses the official ERiC shared library (libericapi.dylib on macOS)
    for validation and transmission.  It does NOT use the simple HTTP path used
    by ``ElsterClient`` — ERiC is mandatory for E-Bilanz submissions.

    Parameters
    ----------
    config:
        ``ElsterConfig`` with certificate path/password, Steuernummer, etc.
    eric_home:
        Path to the directory containing libericapi.dylib and plugins/.
        E.g. ``/path/to/ERiC-43.4.6.0/Darwin-universal/lib``.
    use_test:
        True → Testmerker included; submission is not legally binding.
        False → PRODUCTION — real filing.
    log_dir:
        Optional directory for ERiC log output.  When ``None`` (default) no log
        file is written.  The caller should pass a project-specific path to avoid
        log data leaking between projects (e.g. ``~/.finamt/<project>/eric_logs``).

    Usage::

        from finamt.tax.elster import ElsterConfig, ElsterEricClient

        config = ElsterConfig.from_env()
        client = ElsterEricClient(
            config,
            eric_home="/path/to/eric/lib",
            use_test=True,
        )
        result = client.submit_ebilanz(xbrl_bytes, year=2025)
        print(result)
    """

    def __init__(
        self,
        config: ElsterConfig,
        eric_home: str,
        use_test: bool = True,
        log_dir: str | None = None,
    ) -> None:
        self.config = config
        self.eric_home = eric_home
        self.use_test = use_test
        self.log_dir = log_dir  # None means ERiC writes no log file
        self._builder = EBilanzEnvelopeBuilder(config)

        if not use_test:
            import warnings

            warnings.warn(
                "ElsterEricClient is in PRODUCTION mode. Submissions are legally binding.",
                stacklevel=2,
            )

    # ------------------------------------------------------------------

    def validate_ebilanz(self, xbrl_bytes: bytes, year: int) -> SubmissionResult:
        """
        Validate the XBRL instance via ERiC without sending to ELSTER.

        Useful during development to surface any ERiC validation errors
        before attempting a real transmission.
        """
        return self._run(xbrl_bytes, year, send=False)

    def validate_ust(
        self,
        report: USTVAReport,
        year: int,
        period: int = 0,
        is_berichtigung: bool = False,
    ) -> SubmissionResult:
        """Validate the USt/UStVA XML via ERiC without sending to ELSTER."""
        return self._run_ust(report, year, period, is_berichtigung, send=False)

    def submit_ust(
        self,
        report: USTVAReport,
        year: int,
        period: int = 0,
        is_berichtigung: bool = False,
    ) -> SubmissionResult:
        """Validate and transmit the USt/UStVA to ELSTER via ERiC."""
        return self._run_ust(report, year, period, is_berichtigung, send=True)

    def _run_ust(
        self,
        report: USTVAReport,
        year: int,
        period: int,
        is_berichtigung: bool,
        send: bool,
    ) -> SubmissionResult:
        from pathlib import Path as _Path

        from .eric_wrapper import (
            ERIC_SENDE,
            ERIC_VALIDIERE,
            EricBuffer,
            EricCertificate,
            EricError,
            EricSession,
        )

        builder = ElsterXMLBuilder(self.config)
        try:
            envelope_xml = builder.build_ustva(
                report,
                year=year,
                period=period,
                is_berichtigung=is_berichtigung,
                use_test=self.use_test,
            )
        except Exception as exc:
            return SubmissionResult(
                success=False, error_code="XML_BUILD_ERROR", error_message=str(exc)
            )

        # USt_{year} for annual (period==0), UStVA_{year} for periodic
        datenart_version = f"USt_{year}" if period == 0 else f"UStVA_{year}"

        flags = ERIC_VALIDIERE
        if send:
            flags |= ERIC_SENDE

        log_dir = self.log_dir
        if log_dir:
            _Path(log_dir).mkdir(parents=True, exist_ok=True)

        rc: int = 0
        response_xml: bytes = b""
        server_xml: bytes = b""
        eric_text: str = ""
        try:
            with EricSession(self.eric_home, log_dir=log_dir) as eric:
                with EricBuffer(eric) as resp_buf, EricBuffer(eric) as srv_buf:
                    with EricCertificate(
                        eric, str(self.config.cert_path), self.config.cert_password
                    ) as cert:
                        rc, _th = eric.bearbeite_vorgang(
                            xml_bytes=envelope_xml,
                            datenart_version=datenart_version,
                            flags=flags,
                            crypto_params=cert.verschluesselungs_parameter,
                            response_buffer=resp_buf.handle(),
                            server_buffer=srv_buf.handle(),
                        )
                        response_xml = resp_buf.content()
                        server_xml = srv_buf.content()
                        if rc != 0:
                            eric_text = eric.get_error_text(rc)
        except EricError as exc:
            return SubmissionResult(success=False, error_code=str(exc.code), error_message=str(exc))
        except OSError as exc:
            return SubmissionResult(
                success=False,
                error_code="ERIC_LOAD_ERROR",
                error_message=f"Could not load ERiC library from {self.eric_home}: {exc}",
            )
        except Exception as exc:
            return SubmissionResult(success=False, error_code="ERIC_ERROR", error_message=str(exc))

        if rc != 0:
            err_msg = self._extract_eric_error(rc, response_xml, server_xml, eric_text)
            return SubmissionResult(
                success=False,
                error_code=str(rc),
                error_message=err_msg,
                raw_response=(
                    (response_xml or b"")
                    + (b"\n" if response_xml and server_xml else b"")
                    + (server_xml or b"")
                ).decode("utf-8", errors="replace"),
            )

        telenummer = self._extract_telenummer(server_xml)
        return SubmissionResult(
            success=True,
            telenummer=telenummer,
            raw_response=(server_xml or b"").decode("utf-8", errors="replace"),
        )

    def submit_ebilanz(self, xbrl_bytes: bytes, year: int) -> SubmissionResult:
        """
        Validate and transmit the XBRL instance to ELSTER via ERiC.

        Parameters
        ----------
        xbrl_bytes:
            XBRL instance produced by ``finamt.tax.ebilanz.build_xbrl``.
        year:
            The fiscal year of the Jahresabschluss.

        Returns
        -------
        ``SubmissionResult`` with ``success=True`` and a ``telenummer`` on success.
        """
        return self._run(xbrl_bytes, year, send=True)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _run(self, xbrl_bytes: bytes, year: int, send: bool) -> SubmissionResult:
        from .eric_wrapper import (
            ERIC_SENDE,
            ERIC_VALIDIERE,
            EricBuffer,
            EricCertificate,
            EricError,
            EricSession,
        )

        # 1. Build the ELSTER envelope
        try:
            envelope_xml = self._builder.build(xbrl_bytes, year=year, use_test=self.use_test)
        except Exception as exc:
            return SubmissionResult(
                success=False,
                error_code="XML_BUILD_ERROR",
                error_message=str(exc),
            )

        # 2. Prepare flags
        flags = ERIC_VALIDIERE
        if send:
            flags |= ERIC_SENDE

        # 3. Ensure ERiC log directory exists
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)

        # 4. Invoke ERiC
        eric_text: str = ""
        try:
            with EricSession(self.eric_home, log_dir=self.log_dir) as eric:
                with EricBuffer(eric) as resp_buf, EricBuffer(eric) as srv_buf:
                    with EricCertificate(
                        eric, str(self.config.cert_path), self.config.cert_password
                    ) as cert:
                        rc, _th = eric.bearbeite_vorgang(
                            xml_bytes=envelope_xml,
                            datenart_version=EBilanzEnvelopeBuilder.DATENART_VERSION,
                            flags=flags,
                            crypto_params=cert.verschluesselungs_parameter,
                            response_buffer=resp_buf.handle(),
                            server_buffer=srv_buf.handle(),
                        )
                        response_xml = resp_buf.content()
                        server_xml = srv_buf.content()
                        if rc != 0:
                            # Retrieve human-readable text while session is still open
                            eric_text = eric.get_error_text(rc)
                            # Dump validation protocol to log dir for offline inspection
                            if response_xml:
                                _dump = Path(self.log_dir) / "eric_response_last.xml"
                                try:
                                    _dump.write_bytes(response_xml)
                                    logger.debug("ERiC response XML written to %s", _dump)
                                except Exception:
                                    pass
                            logger.error(
                                "ERiC rc=%d  eric_text=%r  response_xml=%s",
                                rc,
                                eric_text,
                                response_xml.decode("utf-8", errors="replace")
                                if response_xml
                                else "<empty>",
                            )

        except EricError as exc:
            return SubmissionResult(
                success=False,
                error_code=str(exc.code),
                error_message=str(exc),
            )
        except OSError as exc:
            return SubmissionResult(
                success=False,
                error_code="ERIC_LOAD_ERROR",
                error_message=f"Could not load ERiC library from {self.eric_home}: {exc}",
            )
        except Exception as exc:
            return SubmissionResult(
                success=False,
                error_code="ERIC_ERROR",
                error_message=str(exc),
            )

        # 5. rc == 0 means success; non-zero is a validation / transmission error
        if rc != 0:
            err_msg = self._extract_eric_error(rc, response_xml, server_xml, eric_text)
            return SubmissionResult(
                success=False,
                error_code=str(rc),
                error_message=err_msg,
                raw_response=(
                    (response_xml or b"")
                    + (b"\n" if response_xml and server_xml else b"")
                    + (server_xml or b"")
                ).decode("utf-8", errors="replace"),
            )

        # 6. Parse Transferticket (Telenummer) from server response
        telenummer = self._extract_telenummer(server_xml)
        return SubmissionResult(
            success=True,
            telenummer=telenummer,
            raw_response=(server_xml or b"").decode("utf-8", errors="replace"),
        )

    @staticmethod
    def _extract_telenummer(xml_bytes: bytes) -> str | None:
        if not xml_bytes:
            return None
        if not _LXML_AVAILABLE:
            raw = xml_bytes.decode("utf-8", errors="replace")
            if "<Telenummer>" in raw:
                s = raw.index("<Telenummer>") + len("<Telenummer>")
                e = raw.index("</Telenummer>")
                return raw[s:e]
            return None
        try:
            tree = etree.fromstring(xml_bytes)
            nodes = tree.xpath("//*[local-name()='Telenummer']")
            return nodes[0].text if nodes else None
        except Exception:
            return None

    @staticmethod
    def _extract_eric_error(
        rc: int,
        response_xml: bytes,
        server_xml: bytes,
        eric_text: str = "",
    ) -> str:
        """Best-effort extraction of a human-readable error message.

        ERiC puts validation rule failures in *response_xml* under
        ``FehlerRegelpruefung/Text``; server-side errors land in *server_xml*
        under ``Meldung``.
        """
        parts: list[str] = []
        if eric_text:
            parts.append(eric_text)

        if _LXML_AVAILABLE:
            # --- validation protocol (local ERiC check, rc 610301xxx) ---
            if response_xml:
                try:
                    tree = etree.fromstring(response_xml)
                    texts = tree.xpath("//*[local-name()='Text']/text()")
                    if texts:
                        parts.extend(texts)
                    # Also look for FachlicheFehlerId + RegelName for context
                    ids = tree.xpath("//*[local-name()='FachlicheFehlerId']/text()")
                    names = tree.xpath("//*[local-name()='RegelName']/text()")
                    for fid, rn in zip(ids, names, strict=False):
                        parts.append(f"[{rn} / FehlerID {fid}]")
                except Exception:
                    if response_xml:
                        parts.append(response_xml.decode("utf-8", errors="replace")[:500])

            # --- server response errors ---
            if server_xml:
                try:
                    tree = etree.fromstring(server_xml)
                    msgs = tree.xpath("//*[local-name()='Meldung']/text()")
                    if msgs:
                        parts.extend(msgs)
                except Exception:
                    parts.append(server_xml.decode("utf-8", errors="replace")[:300])
        else:
            # lxml not available — return raw bytes
            for xml in (response_xml, server_xml):
                if xml:
                    parts.append(xml.decode("utf-8", errors="replace")[:300])

        if parts:
            return f"ERiC {rc}: " + " | ".join(parts)
        return f"ERiC returned code {rc}"

    # ------------------------------------------------------------------
    # Convenience: export envelope XML without sending
    # ------------------------------------------------------------------

    def export_ebilanz_xml(
        self,
        xbrl_bytes: bytes,
        year: int,
        path: str | Path,
    ) -> Path:
        """
        Build the ELSTER envelope and write it to *path* without submitting.
        Useful for manual inspection or debugging.
        """
        xml = self._builder.build(xbrl_bytes, year=year, use_test=self.use_test)
        out = Path(path)
        out.write_bytes(xml)
        return out
