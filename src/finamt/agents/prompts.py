"""
finamt.agents.prompts
~~~~~~~~~~~~~~~~~~~~~~~~
Short, focused prompts for the 4-agent sequential extraction pipeline.
Pattern: instruction → schema → text → output reminder (sandwich).
"""

from __future__ import annotations

RECEIPT_CATEGORIES = [
    "services",
    "products",
    "material",
    "equipment",
    "software",
    "licensing",
    "telecommunication",
    "travel",
    "car",
    "education",
    "utilities",
    "insurance",
    "financial",
    "office",
    "marketing",
    "donations",
    "public_fees",
    "tax_settlement",
    "capital_movement",
    "other",
]

_CATS = "|".join(RECEIPT_CATEGORIES)

# ---------------------------------------------------------------------------
# Agent 1 — Metadata: receipt number, date, category
# ---------------------------------------------------------------------------

AGENT1_TEMPLATE = """\
Extract receipt number, date, and category from the text below.
receipt_number = receipt no., Rechnungsnr., invoice no., else Transaction ID.
Return only this JSON, no other text:
{{"receipt_number": null, "receipt_date": "YYYY-MM-DD", "category": "{cats}"}}

TEXT:
{text}

Return only JSON:"""

# ---------------------------------------------------------------------------
# Agent 2 — Counterparty
# ---------------------------------------------------------------------------

AGENT2_TEMPLATE = """\
Extract the {party} from the receipt text below.
{exclusion}
Rules: name = business|person, \
vat_id = USt-IdNr|UID, \
tax_number = Steuernummer, \
Return only this JSON, no other text:
{{"name": null, "vat_id": null, "tax_number": null, "street_and_number": null, \
"address_supplement": null, "postcode": null, "city": null, "state": null, "country": null}}

TEXT:
{text}

Return only JSON:"""

# ---------------------------------------------------------------------------
# Agent 3 — Amounts
# ---------------------------------------------------------------------------

AGENT3_TEMPLATE = """\
Extract the financial amounts from the receipt text below.
Return only this JSON, no other text:
{{"total_amount": null, "vat_percentage": null, "vat_amount": null, "currency": null}}

Rules: all numeric values are numbers, not strings. \
German number format "1.234,56" means 1234.56. \
vat_percentage is the VAT rate printed on the receipt (MwSt, USt, VAT), \
for example 19, 7 or 0. Copy it from the text, never guess or assume 19. \
Use 0 (and vat_amount 0) if the receipt shows no tax, 0%, steuerfrei, \
Kleinunternehmer (§19 UStG), reverse charge or innergemeinschaftliche Lieferung. \
Use null only if no VAT information appears at all. \
vat_amount is the absolute tax amount, not the rate. \
currency is the ISO 4217 code e.g. EUR, USD, GBP.

TEXT:
{text}

Return only JSON:"""

# ---------------------------------------------------------------------------
# Agent 4 — Line items
# ---------------------------------------------------------------------------

AGENT4_TEMPLATE = """\
Extract all line items from the receipt text below.
Return only this JSON, no other text:
{{"items": [{{"description": null, "vat_rate": null, "vat_amount": null, "total_price": null}}]}}

Rules: all numeric values are numbers, not strings. \
German number format "1.234,56" means 1234.56. \
vat_rate is the percentage e.g. 19.0. \
If no line items exist return {{"items": []}}.

TEXT:
{text}

Return only JSON:"""


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int = 3000) -> str:
    """Keep prompts short for local models."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[... truncated ...]"


def _truncate_head_tail(text: str, max_chars: int = 3000, head: int = 1000) -> str:
    """Keep the start and the END of the text.

    Totals and VAT breakdowns sit at the bottom of invoices; cutting only the
    tail would hide them and make the model guess the rate.
    """
    if len(text) <= max_chars:
        return text
    tail = max_chars - head
    return text[:head] + "\n[... truncated ...]\n" + text[-tail:]


def build_agent1_prompt(text: str) -> str:
    return AGENT1_TEMPLATE.format(cats=_CATS, text=_truncate(text))


def build_agent2_prompt(text: str, receipt_type: str, taxpayer_info: dict | None = None) -> str:
    if receipt_type == "purchase":
        party = "vendor/supplier"
    else:
        party = "client/customer"

    exclusion = ""
    if taxpayer_info:
        parts: list[str] = []
        if taxpayer_info.get("name"):
            parts.append(f"Name: {taxpayer_info['name']}")
        if taxpayer_info.get("vat_id"):
            parts.append(f"VAT ID: {taxpayer_info['vat_id']}")
        if taxpayer_info.get("tax_number"):
            parts.append(f"Tax Number: {taxpayer_info['tax_number']}")
        if taxpayer_info.get("address"):
            parts.append(f"Address: {taxpayer_info['address']}")
        if parts:
            exclusion = (
                f"IMPORTANT: The following data belong to the USER not {party} "
                f"— do NOT extract it: "
                + "; ".join(parts)
                + ". Instead, find other suitable data for these fields."
            )

    return AGENT2_TEMPLATE.format(party=party, exclusion=exclusion, text=_truncate(text))


def build_agent3_prompt(text: str) -> str:
    return AGENT3_TEMPLATE.format(text=_truncate_head_tail(text))


def build_agent4_prompt(text: str) -> str:
    return AGENT4_TEMPLATE.format(text=_truncate(text))


__all__ = [
    "RECEIPT_CATEGORIES",
    "build_agent1_prompt",
    "build_agent2_prompt",
    "build_agent3_prompt",
    "build_agent4_prompt",
]
