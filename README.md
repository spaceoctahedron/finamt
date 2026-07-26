# finamt

<img src="https://raw.githubusercontent.com/spaceoctahedron/finamt/main/.github/images/finamt-wordmark.svg" width="50%" alt="finamt"/>

<div>
<br>
</div>

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/finamt?color=blue&label=PyPI)](https://pypi.org/project/finamt/)
[![Downloads](https://pepy.tech/badge/finamt)](https://pepy.tech/project/finamt)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://github.com/spaceoctahedron/finamt/blob/main/LICENSE)
[![Tests](https://github.com/spaceoctahedron/finamt/actions/workflows/tests.yml/badge.svg)](https://github.com/spaceoctahedron/finamt/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/spaceoctahedron-user/a44d923694c52f0711d3f84be0aaf644/raw/coverage.json)](https://github.com/spaceoctahedron/finamt/actions/workflows/tests.yml)
[![GitHub last commit](https://img.shields.io/github/last-commit/spaceoctahedron/finamt)](https://github.com/spaceoctahedron/finamt/commits/main)
[![Documentation Status](https://readthedocs.org/projects/finamt/badge/?version=latest)](https://readthedocs.org/projects/finamt/)

![US](https://api.iconify.design/noto-v1:flag-for-flag-united-states.svg?height=16) English | ![DE](https://api.iconify.design/noto-v1:flag-for-flag-germany.svg?height=16) [German](https://github.com/spaceoctahedron/finamt/blob/main/readme/README_de.md)

</div>

An agentic Python library for extracting structured data from receipts and invoices and preparing essential German tax return statements.

## Features

- **German Tax Alignment** — Category taxonomy and VAT handling aligned with German fiscal practice
- **Local-First** — Everything runs completely offline; models are auto-downloaded from HuggingFace and cached locally, data is stored in a local database
- **4-Agent Pipeline** — Sequential specialised agents for metadata, counterparty, amounts, and line items; short focused prompts for reliable local model performance
- **Web UI** — Full browser interface for uploading, reviewing, editing, and managing receipts and invoices and preparing tax returns
- **ELSTER submission** — Annual Umsatzsteuererklärung (USt), E-Bilanz, and UStVA submitted directly to the Finanzamt via the official ERiC library; confirmed working end-to-end with a formal Finanzamt acknowledgement

## Tech Stack

**Backend**
- ![Python](https://api.iconify.design/devicon:python.svg?height=16) [Python](https://www.python.org) — package language
- ![FastAPI](https://api.iconify.design/devicon:fastapi.svg?height=16) [FastAPI](https://fastapi.tiangolo.com) — backend for the web UI
- ![PaddleOCR](https://api.iconify.design/simple-icons:paddlepaddle.svg?height=16&color=%23363FE5) [PaddleOCR](https://github.com/PADDLEPADDLE/PADDLEOCR) — OCR for scanned PDFs 
- ![Tesseract](https://api.iconify.design/devicon:google.svg?height=16) [Tesseract](https://github.com/tesseract-ocr/tesseract) — OCR for scanned PDFs and images when PaddleOCR fails or times out
- ![HuggingFace](https://api.iconify.design/simple-icons:huggingface.svg?height=16&color=%23FFD21E) [HuggingFace Hub](https://huggingface.co) — models downloaded and cached automatically on first use; no separate server required
    - ![Mistral](https://api.iconify.design/logos:mistral-ai-icon.svg?height=16) [Mistral](https://mistral.ai) – `mistral:7b` is the recommended default (maps to `mlx-community/Mistral-7B-Instruct-v0.3-4bit` on Apple Silicon)
    - ![Qwen](https://api.iconify.design/simple-icons:qwen.svg?height=16&color=%237B2FBF) [Qwen](https://qwen.ai/home) – `qwen2.5:7b-instruct-q4_K_M` is a good alternative (maps to `mlx-community/Qwen2.5-7B-Instruct-4bit` on Apple Silicon)
    - ![mlx-lm](https://api.iconify.design/simple-icons:apple.svg?height=16) [mlx-lm](https://github.com/ml-explore/mlx-lm) — 4-bit inference on Apple Silicon (M-series) via the MLX framework; ~13 % faster than Ollama
    - ![transformers](https://api.iconify.design/simple-icons:huggingface.svg?height=16&color=%23FFD21E) [transformers](https://huggingface.co/docs/transformers) — cross-platform inference fallback (Linux / Windows / Intel Mac)
- ![SQLite](https://api.iconify.design/devicon:sqlite.svg?height=16) [SQLite](https://sqlite.org) – local database for original receipts and extracted data

**Frontend**
- ![React](https://api.iconify.design/devicon:react.svg?height=16) [React](https://react.dev) — interactive frontend
- ![Vite](https://api.iconify.design/devicon:vitejs.svg?height=16) [Vite](https://vite.dev) — fast dev server and production bundler
- ![Tailwind CSS](https://api.iconify.design/devicon:tailwindcss.svg?height=16) [Tailwind CSS](https://tailwindcss.com) — utility-first styling
- ![TypeScript](https://api.iconify.design/devicon:typescript.svg?height=16) [TypeScript](https://www.typescriptlang.org) — type-safe component and API code


**CLI**
- ![Typer](https://api.iconify.design/devicon:typer.svg?height=16) [Typer](https://typer.tiangolo.com/) — CLI with coloured progress output

**Packaging**
- ![PyPI](https://api.iconify.design/devicon:pypi.svg?height=16) [PyPI](https://pypi.org/project/finamt/) — distributed as an installable Python package

## Installation

```bash
pip install finamt
```

For CLI usage, installing via [pipx](https://pipx.pypa.io/) is recommended — it places `finamt` into its own dedicated virtual environment, ensuring its dependencies never interfere with your other projects, while still exposing the `finamt` command globally without requiring you to activate a virtualenv:

```bash
pipx install finamt
```

> **Note for Python 3.14+ users:** `finamt` currently requires Python 3.13. If your system Python is 3.14 or newer, install [uv](https://docs.astral.sh/uv/) to manage Python versions and pass the resolved path to pipx:
> ```bash
> uv python install 3.13
> pipx install finamt --python $(uv python find 3.13)
> ```

### System Requirements

- Python 3.10+
- Tesseract OCR (optional fallback when PaddleOCR times out)

> **No Ollama required.** LLM models are downloaded automatically from HuggingFace on first use (~4 GB per model) and cached at `~/.cache/huggingface/hub`. On Apple Silicon the `mlx-lm` backend is used; on other platforms `transformers` is used.

#### Tesseract OCR (optional fallback from PaddleOCR)

**Ubuntu / Debian**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-deu
```

**macOS**
```bash
brew install tesseract tesseract-lang
```

**Windows**

Download the installer from https://github.com/UB-Mannheim/tesseract/wiki and add it to your `PATH`.

## Quick Start

### Interactive UI

```bash
finamt serve
```

<p align="center">
  <img src="https://raw.githubusercontent.com/spaceoctahedron/finamt/main/docs/images/Demo.webp" width="100%" />
  <em>Interactive UI to upload receipts and manage tax statements</em>
</p>

### Python API

#### Process a single receipt (expense)

```python
from finamt import FinanceAgent

agent = FinanceAgent()
result = agent.process_receipt("receipt.pdf")

if result.success:
    data = result.data
    print(f"Counterparty: {data.vendor}")
    print(f"Date:         {data.receipt_date}")
    print(f"Total:        {data.total_amount} EUR")
    print(f"VAT:          {data.vat_percentage}% ({data.vat_amount} EUR)")
    print(f"Net:          {data.net_amount} EUR")
    print(f"Category:     {data.category}")
    print(f"Items:        {len(data.items)}")

    # Serialise to JSON
    with open("extracted.json", "w", encoding="utf-8") as f:
        f.write(data.to_json())
else:
    print(f"Extraction failed: {result.error_message}")
```

#### Sale invoices (outgoing)

```python
result = agent.process_receipt("invoice_to_client.pdf", receipt_type="sale")
```

#### Batch processing

```python
from pathlib import Path
from finamt import FinanceAgent

agent = FinanceAgent()
results = agent.batch_process(list(Path("receipts/").glob("*.pdf")))

for path, result in results.items():
    if result.success:
        print(f"{path}: {result.data.total_amount} EUR")
    else:
        print(f"{path}: ERROR — {result.error_message}")
```

## Configuration

Settings are read in priority order from: environment variables → `.env` file → built-in defaults.

```bash
# .env

# OCR and general settings
FINAMT_OCR_LANGUAGE=german
FINAMT_OCR_TIMEOUT=60
FINAMT_TESSERACT_CMD=tesseract
FINAMT_OCR_PREPROCESS=true
FINAMT_PDF_DPI=150

# Extraction agents — all 4 agents use this model
FINAMT_AGENT_MODEL=mistral:7b
FINAMT_AGENT_TIMEOUT=60
FINAMT_AGENT_NUM_CTX=4096
FINAMT_AGENT_MAX_RETRIES=2
```

You can also pass config objects directly:

```python
from finamt import FinanceAgent
from finamt.agents.config import Config, AgentsConfig

agent = FinanceAgent(
    config=Config(ocr_language="deu+eng", pdf_dpi=150),
    agents_cfg=AgentsConfig(agent_model="mistral:7b"),
)
```

## API Reference

### FinanceAgent

```python
class FinanceAgent:
    def __init__(
        self,
        config:     Config | None = None,
        db_path:    str | Path | None = "~/.finamt/default/finamt.db",
        agents_cfg: AgentsConfig | None = None,
    ) -> None: ...

    def process_receipt(
        self,
        pdf_path:     str | Path | bytes,
        receipt_type: str = "purchase",   # "purchase" or "sale"
    ) -> ExtractionResult: ...

    def batch_process(
        self,
        pdf_paths:    list[str | Path],
        receipt_type: str = "purchase",
    ) -> dict[str, ExtractionResult]: ...
```

### ExtractionResult

Always check `success` before accessing `data`.

```python
@dataclass
class ExtractionResult:
    success:         bool
    data:            ReceiptData | None
    error_message:   str | None
    duplicate:       bool                  # True if already in the database
    existing_id:     str | None            # ID of the original if duplicate
    processing_time: float | None          # seconds

    def to_dict(self) -> dict: ...
```

### ReceiptData

```python
@dataclass
class ReceiptData:
    id:               str                  # SHA-256 of OCR text — stable dedup key
    receipt_type:     ReceiptType          # "purchase" or "sale"
    counterparty:     Counterparty | None  # vendor (purchase) or client (sale)
    receipt_number:   str | None
    receipt_date:     datetime | None
    total_amount:     Decimal | None
    currency:         str | "EUR"
    vat_percentage:   Decimal | None       # e.g. Decimal("19.0")
    vat_amount:       Decimal | None
    net_amount:       Decimal | None       # computed: total - vat
    category:         ReceiptCategory
    items:            list[ReceiptItem]
    vat_splits:       list[dict]           # for mixed-rate invoices

    vendor: str | None                     # alias for counterparty.name

    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
```

### Counterparty

```python
@dataclass
class Counterparty:
    id:          str           # UUID assigned by the database
    name:        str | None
    vat_id:      str | None    # EU format, e.g. DE123456789
    tax_number:  str | None    # German Steuernummer, e.g. 123/456/78901
    address:     Address
    verified:    bool          # manually confirmed in the UI
```

### ReceiptItem

```python
@dataclass
class ReceiptItem:
    position:    int | None
    description: str
    quantity:    Decimal | None
    unit_price:  Decimal | None
    total_price: Decimal | None
    vat_rate:    Decimal | None
    vat_amount:  Decimal | None
    category:    ReceiptCategory

    def to_dict(self) -> dict: ...
```

### ReceiptCategory

A validated string subclass. Invalid values are silently normalised to `"other"`.

```python
from finamt.agents.prompts import RECEIPT_CATEGORIES   # list[str]
from finamt.models import ReceiptCategory

cat = ReceiptCategory("software")       # valid
cat = ReceiptCategory("unknown_value")  # normalised to "other"
cat = ReceiptCategory.other()           # explicit fallback
```

### Exceptions

All exceptions inherit from `FinanceAgentError`.

| Exception | Raised when |
|---|---|
| `OCRProcessingError` | PDF cannot be opened or text extraction fails |
| `LLMExtractionError` | Model returns invalid JSON after all retries |
| `InvalidReceiptError` | Extracted data fails business-logic validation |

```python
from finamt.exceptions import FinanceAgentError, OCRProcessingError

try:
    result = agent.process_receipt("scan.pdf")
except OCRProcessingError as e:
    print(e)
```

## Extraction Pipeline

Each receipt goes through four sequential LLM calls, each with a short focused prompt:

| Agent | Extracts |
|---|---|
| Agent 1 | Receipt number, date, category |
| Agent 2 | Counterparty name, VAT ID, Steuernummer, address |
| Agent 3 | Total amount, VAT percentage, VAT amount |
| Agent 4 | Line items (description, VAT rate, VAT amount, price) |

Results are merged in Python — no additional LLM validation step. Debug output for every agent (prompt, raw response, parsed JSON) is saved to `~/.finamt/debug/<receipt_id>/`.

## Categories and Subcategories

Every receipt is tagged with a category and optional subcategory. Categories map directly to line items in the German ELSTER tax forms (EÜR / UStVA), so the correct totals land in the right fields without manual re-sorting.

| Category | Subcategories |
|---|---|
| ![services](https://api.iconify.design/mdi:briefcase.svg?height=16&color=%23EF4444) `services` | `freelance` `consulting` `legal` `accounting` `notary` |
| ![products](https://api.iconify.design/ant-design:product-filled.svg?height=16&color=%23EF4444) `products` | `physical_goods` `digital_goods` `merchandise` `samples` |
| ![material](https://api.iconify.design/solar:box-bold.svg?height=16&color=%23EF4444) `material` | `consumables` `raw_materials` `packaging` `merchandise` |
| ![equipment](https://api.iconify.design/streamline-plump:computer-pc-desktop-solid.svg?height=16&color=%23EF4444) `equipment` | `low_value_asset` `computer` `machinery` `furniture` `tools` |
| ![software](https://api.iconify.design/heroicons:cpu-chip-16-solid.svg?height=16&color=%23EF4444) `software` | `subscriptions` `pay_as_you_go` `licenses` `hosting` `domains` |
| ![licensing](https://api.iconify.design/mdi:file-certificate.svg?height=16&color=%23EF4444) `licensing` | `software_licenses` `media_licenses` `other_ip` |
| ![telecommunication](https://api.iconify.design/streamline-flex:satellite-dish-solid.svg?height=16&color=%23EF4444) `telecommunication` | `phone` `internet` `bundled` |
| ![travel](https://api.iconify.design/mdi:airplane.svg?height=16&color=%23EF4444) `travel` | `transport` `accommodation` `meals` `per_diem` `incidental` |
| ![car](https://api.iconify.design/boxicons:car-filled.svg?height=16&color=%23EF4444) `car` | `fuel` `parking` `garage` `repair` `maintenance` `insurance` `leasing` `rental` |
| ![education](https://api.iconify.design/wpf:books.svg?height=16&color=%23EF4444) `education` | `courses` `books` `conferences` `certifications` |
| ![utilities](https://api.iconify.design/roentgen:electricity.svg?height=16&color=%23EF4444) `utilities` | `electricity` `heating` `water` `waste` |
| ![insurance](https://api.iconify.design/fa:shield.svg?height=16&color=%23EF4444) `insurance` | `liability` `health` `vehicle` `property` |
| ![financial](https://api.iconify.design/boxicons:bank-filled.svg?height=16&color=%23EF4444) `financial` | `bank_fees` `interest` `loan_costs` `payment_fees` |
| ![office](https://api.iconify.design/vaadin:office.svg?height=16&color=%23EF4444) `office` | `rent` `coworking` `storage` `cleaning` `security` |
| ![marketing](https://api.iconify.design/mdi:loudspeaker.svg?height=16&color=%23EF4444) `marketing` | `advertising` `print_media` `trade_fairs` `sponsorship` `gifts` |
| ![donations](https://api.iconify.design/mdi:donation.svg?height=16&color=%23EF4444) `donations` | `charitable` `political` `church` |
| ![public_fees](https://api.iconify.design/mdi:gavel.svg?height=16&color=%23EF4444) `public_fees` | `broadcasting_fee` `ihk_hwk` `berufsgenossenschaft` `other_public_fee` |
| ![other](https://api.iconify.design/flowbite:folder-plus-solid.svg?height=16&color=%23EF4444) `other` | `membership_fees` `sundry` |



## TODO

**Receipt processing**
- [x] OCR pipeline (PaddleOCR + Tesseract fallback)
- [x] 4-agent extraction (metadata, counterparty, amounts, line items)
- [x] Deduplication, database storage, batch processing

**Tax calculation**
- [x] UStVA — VAT pre-return (monthly / quarterly)
- [x] UStE — annual VAT return
- [x] EÜR — income-surplus statement
- [x] KSt 1 — corporate income tax return
- [x] GewSt — trade tax return
- [x] Jahresabschluss — annual accounts (Bilanz + GuV, § 267a HGB)

**ELSTER transmission**
- [x] UStVA — ELSTER XML builder + Kennzahlen mapper + RSA signing + HTTP submission
- [x] E-Bilanz — XBRL instance document (HGB taxonomy v6, MicroBilG schema)
- [ ] E-Bilanz — ERiC ctypes bridge for actual transmission
- [ ] KSt, GewSt, UStVA, USt — ELSTER XML builder
- [ ] EÜR, ESt — ELSTER XML builder

**Validation**
- [ ] XSD validation of generated XBRL against HGB taxonomy
- [ ] ELSTER dry-run / test-server validation before live submission

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`) and make your changes
3. Run the test suite:
   ```bash
   pytest --cov=src --cov-report=term-missing
   ```
4. Lint and format with ![Ruff](https://api.iconify.design/catppuccin:ruff.svg?height=16) Ruff:
   ```bash
   ruff check --fix src/ tests/
   ruff format src/ tests/
   ```
5. Update the documentation
6. Submit a pull request

## License

AGPL-3.0 — see [LICENSE](https://raw.githubusercontent.com/spaceoctahedron/finamt/main/LICENSE) for details.

## Commercial Licensing

finamt is available under the AGPL-3.0 license.

If you wish to use finamt in a proprietary setting, without the obligations of the AGPL (e.g. without releasing source code or for use in a commercial SaaS product), a commercial license is available.

For inquiries, contact: info@spaceoctahedron.com

## Third-Party Components and Models

This software depends on external libraries and services, including:

- PaddleOCR (Apache License 2.0)
- Tesseract OCR (Apache License 2.0)
- HuggingFace Hub / transformers (Apache License 2.0)
- mlx-lm (MIT License, Apple Silicon only)

finamt downloads language models from HuggingFace (e.g. Mistral, Qwen) on first use and caches them locally.

These models are **not distributed** with this software and are subject to their own licenses.
Users are responsible for complying with the respective terms when downloading and using such models.

## Disclaimer

This software is provided for informational and automation purposes only.

It does **not** constitute tax, legal, or accounting advice.

While finamt is designed to assist with the preparation of German tax-related data (e.g. VAT returns, EÜR, ELSTER submissions), no guarantee is made regarding:

- correctness of extracted data
- completeness of financial records
- compliance with applicable tax laws and regulations
- acceptance by tax authorities

Users are solely responsible for verifying all outputs before submission to any authority.

**Always consult a qualified tax advisor (Steuerberater) for legally binding guidance.**

To the maximum extent permitted by law, Space Octahedron GmbH assumes no liability for:

- errors in OCR or LLM-based extraction
- incorrect classifications or calculations
- rejected or incorrect tax filings
- financial losses or penalties arising from use of this software

## Product Information (ELSTER)

- **Produktname:** Space Octahedron® finamt  
- **Hersteller:** Space Octahedron GmbH  
- **Kontakt:** info@spaceoctahedron.com
