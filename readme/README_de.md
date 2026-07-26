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
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/yauheniya-ai/d09f6edc7b1928aeea1fbde834a6080b/raw/coverage.json)](https://github.com/spaceoctahedron/finamt/actions/workflows/tests.yml)
[![GitHub last commit](https://img.shields.io/github/last-commit/spaceoctahedron/finamt)](https://github.com/spaceoctahedron/finamt/commits/main)
[![Documentation Status](https://readthedocs.org/projects/finamt/badge/?version=latest)](https://readthedocs.org/projects/finamt/)

![US](https://api.iconify.design/noto-v1:flag-for-flag-united-states.svg?height=16) [English](https://github.com/spaceoctahedron/finamt/blob/main/README.md) | ![DE](https://api.iconify.design/noto-v1:flag-for-flag-germany.svg?height=16) Deutsch

</div>

Eine agentische Python-Bibliothek zur strukturierten Extraktion von Daten aus Belegen und Rechnungen sowie zur Erstellung wesentlicher deutscher Steuererklärungen.

## Funktionen

- **Deutsche Steuerkonformität** — Kategoriensystem und Umsatzsteuerbehandlung ausgerichtet auf die deutsche Buchführungspraxis
- **Lokal & Offline** — Alles läuft vollständig offline; Modelle werden automatisch von HuggingFace heruntergeladen und lokal gecacht, Daten werden in einer lokalen Datenbank gespeichert
- **4-Agenten-Pipeline** — Vier sequenzielle, spezialisierte Agenten für Metadaten, Geschäftspartner, Beträge und Positionen; kurze, fokussierte Prompts für zuverlässige Leistung mit lokalen Modellen
- **Web-Oberfläche** — Vollständige Browseroberfläche zum Hochladen, Prüfen, Bearbeiten und Verwalten von Belegen
- **ELSTER-Übermittlung** — Umsatzsteuerjahreserklärung (USt 2A), E-Bilanz und UStVA werden direkt über die offizielle ERiC-Bibliothek ans Finanzamt übermittelt; Ende-zu-Ende-Funktionalität durch Eingangsbestätigung des Finanzamts belegt

## Technologie-Stack

**Backend**
- ![Python](https://api.iconify.design/devicon:python.svg?height=16) [Python](https://www.python.org) — Paketsprache
- ![FastAPI](https://api.iconify.design/devicon:fastapi.svg?height=16) [FastAPI](https://fastapi.tiangolo.com) — Backend der Web-Oberfläche
- ![PaddleOCR](https://api.iconify.design/simple-icons:paddlepaddle.svg?height=16&color=%23363FE5) [PaddleOCR](https://github.com/PADDLEPADDLE/PADDLEOCR) — OCR für gescannte PDFs
- ![Tesseract](https://api.iconify.design/devicon:google.svg?height=16) [Tesseract](https://github.com/tesseract-ocr/tesseract) — OCR für gescannte PDFs und Bilder als Fallback bei PaddleOCR-Fehlern oder Timeouts
- ![HuggingFace](https://api.iconify.design/simple-icons:huggingface.svg?height=16&color=%23FFD21E) [HuggingFace Hub](https://huggingface.co) — Modelle werden beim ersten Start automatisch heruntergeladen und gecacht; kein separater Server erforderlich
    - ![Mistral](https://api.iconify.design/logos:mistral-ai-icon.svg?height=16) [Mistral](https://mistral.ai) — `mistral:7b` ist das empfohlene Standardmodell (auf Apple Silicon: `mlx-community/Mistral-7B-Instruct-v0.3-4bit`)
    - ![Qwen](https://api.iconify.design/simple-icons:qwen.svg?height=16&color=%237B2FBF) [Qwen](https://qwen.ai/home) — `qwen2.5:7b-instruct-q4_K_M` ist eine gute Alternative (auf Apple Silicon: `mlx-community/Qwen2.5-7B-Instruct-4bit`)
    - ![mlx-lm](https://api.iconify.design/simple-icons:apple.svg?height=16) [mlx-lm](https://github.com/ml-explore/mlx-lm) — 4-Bit-Inferenz auf Apple Silicon (M-Serie) via MLX; ca. 13 % schneller als Ollama
    - ![transformers](https://api.iconify.design/simple-icons:huggingface.svg?height=16&color=%23FFD21E) [transformers](https://huggingface.co/docs/transformers) — Plattformübergreifender Inferenz-Fallback (Linux / Windows / Intel Mac)
- ![SQLite](https://api.iconify.design/devicon:sqlite.svg?height=16) [SQLite](https://sqlite.org) — Lokale Datenbank für Originalbelege und extrahierte Daten

**Frontend**
- ![React](https://api.iconify.design/devicon:react.svg?height=16) [React](https://react.dev) — Interaktives Frontend
- ![Vite](https://api.iconify.design/devicon:vitejs.svg?height=16) [Vite](https://vite.dev) — Schneller Dev-Server und Produktions-Bundler
- ![Tailwind CSS](https://api.iconify.design/devicon:tailwindcss.svg?height=16) [Tailwind CSS](https://tailwindcss.com) — Utility-First-Styling
- ![TypeScript](https://api.iconify.design/devicon:typescript.svg?height=16) [TypeScript](https://www.typescriptlang.org) — Typsichere Komponenten- und API-Code


**CLI**
- ![Typer](https://api.iconify.design/devicon:typer.svg?height=16) [Typer](https://typer.tiangolo.com/) — CLI mit farbiger Fortschrittsausgabe

**Paketierung**
- ![PyPI](https://api.iconify.design/devicon:pypi.svg?height=16) [PyPI](https://pypi.org/project/finamt/) — Als installierbares Python-Paket verteilt

## Installation

```bash
pip install finamt
```

Für die CLI-Nutzung empfiehlt sich die Installation über [pipx](https://pipx.pypa.io/) — das Paket läuft in einer isolierten Umgebung, sodass seine Abhängigkeiten nie mit anderen Projekten kollidieren, während der `finamt`-Befehl systemweit verfügbar bleibt, ohne dass eine virtuelle Umgebung aktiviert werden muss:

```bash
pipx install finamt
```

> **Hinweis für Python 3.14+-Nutzer:** `finamt` erfordert derzeit Python 3.13. Falls das System-Python 3.14 oder neuer ist, kann [uv](https://docs.astral.sh/uv/) zur Verwaltung von Python-Versionen genutzt werden:
> ```bash
> uv python install 3.13
> pipx install finamt --python $(uv python find 3.13)
> ```

### Systemvoraussetzungen

- Python 3.10+
- Tesseract OCR (optionaler Fallback bei PaddleOCR-Timeout)

> **Kein Ollama erforderlich.** LLM-Modelle werden beim ersten Start automatisch von HuggingFace heruntergeladen (ca. 4 GB pro Modell) und unter `~/.cache/huggingface/hub` gecacht. Auf Apple Silicon wird das `mlx-lm`-Backend verwendet; auf anderen Plattformen `transformers`.

#### Tesseract OCR (optionaler Fallback für PaddleOCR)

**Ubuntu / Debian**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-deu
```

**macOS**
```bash
brew install tesseract tesseract-lang
```

**Windows**

Installer herunterladen von https://github.com/UB-Mannheim/tesseract/wiki und zum `PATH` hinzufügen.

## Schnellstart

### Interaktive Oberfläche

```bash
finamt serve
```

<p align="center">
  <img src="https://raw.githubusercontent.com/spaceoctahedron/finamt/main/docs/images/Demo.webp" width="100%" />
  <em>Interaktive Oberfläche zum Hochladen von Belegen und Verwalten von Steuererklärungen</em>
</p>

### Python-API

#### Einzelnen Beleg verarbeiten (Ausgabe)

```python
from finamt import FinanceAgent

agent = FinanceAgent()
result = agent.process_receipt("beleg.pdf")

if result.success:
    data = result.data
    print(f"Geschäftspartner: {data.vendor}")
    print(f"Datum:            {data.receipt_date}")
    print(f"Gesamtbetrag:     {data.total_amount} EUR")
    print(f"MwSt.:            {data.vat_percentage}% ({data.vat_amount} EUR)")
    print(f"Nettobetrag:      {data.net_amount} EUR")
    print(f"Kategorie:        {data.category}")
    print(f"Positionen:       {len(data.items)}")

    # Als JSON serialisieren
    with open("extrahiert.json", "w", encoding="utf-8") as f:
        f.write(data.to_json())
else:
    print(f"Extraktion fehlgeschlagen: {result.error_message}")
```

#### Ausgangsrechnungen

```python
result = agent.process_receipt("rechnung_an_kunden.pdf", receipt_type="sale")
```

#### Stapelverarbeitung

```python
from pathlib import Path
from finamt import FinanceAgent

agent = FinanceAgent()
results = agent.batch_process(list(Path("belege/").glob("*.pdf")))

for path, result in results.items():
    if result.success:
        print(f"{path}: {result.data.total_amount} EUR")
    else:
        print(f"{path}: FEHLER — {result.error_message}")
```

## Konfiguration

Einstellungen werden in folgender Prioritätsreihenfolge eingelesen: Umgebungsvariablen → `.env`-Datei → eingebaute Standardwerte.

```bash
# .env

# OCR und allgemeine Einstellungen
FINAMT_OCR_LANGUAGE=german
FINAMT_OCR_TIMEOUT=60
FINAMT_TESSERACT_CMD=tesseract
FINAMT_OCR_PREPROCESS=true
FINAMT_PDF_DPI=150

# Extraktionsagenten — alle 4 Agenten verwenden dieses Modell
FINAMT_AGENT_MODEL=mistral:7b
FINAMT_AGENT_TIMEOUT=60
FINAMT_AGENT_NUM_CTX=4096
FINAMT_AGENT_MAX_RETRIES=2
```

Konfigurationsobjekte können auch direkt übergeben werden:

```python
from finamt import FinanceAgent
from finamt.agents.config import Config, AgentsConfig

agent = FinanceAgent(
    config=Config(ocr_language="deu+eng", pdf_dpi=150),
    agents_cfg=AgentsConfig(agent_model="mistral:7b"),
)
```

## API-Referenz

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
        receipt_type: str = "purchase",   # "purchase" oder "sale"
    ) -> ExtractionResult: ...

    def batch_process(
        self,
        pdf_paths:    list[str | Path],
        receipt_type: str = "purchase",
    ) -> dict[str, ExtractionResult]: ...
```

### ExtractionResult

`success` sollte immer vor dem Zugriff auf `data` geprüft werden.

```python
@dataclass
class ExtractionResult:
    success:         bool
    data:            ReceiptData | None
    error_message:   str | None
    duplicate:       bool                  # True, wenn bereits in der Datenbank
    existing_id:     str | None            # ID des Originals bei Duplikat
    processing_time: float | None          # Sekunden

    def to_dict(self) -> dict: ...
```

### ReceiptData

```python
@dataclass
class ReceiptData:
    id:               str                  # SHA-256 des OCR-Textes — stabiler Deduplizierungsschlüssel
    receipt_type:     ReceiptType          # "purchase" oder "sale"
    counterparty:     Counterparty | None  # Lieferant (Eingang) oder Kunde (Ausgang)
    receipt_number:   str | None
    receipt_date:     datetime | None
    total_amount:     Decimal | None
    currency:         str | "EUR"
    vat_percentage:   Decimal | None       # z. B. Decimal("19.0")
    vat_amount:       Decimal | None
    net_amount:       Decimal | None       # berechnet: Gesamt minus MwSt.
    category:         ReceiptCategory
    items:            list[ReceiptItem]
    vat_splits:       list[dict]           # für Rechnungen mit gemischten Steuersätzen

    vendor: str | None                     # Alias für counterparty.name

    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
```

### Counterparty

```python
@dataclass
class Counterparty:
    id:          str           # Von der Datenbank vergebene UUID
    name:        str | None
    vat_id:      str | None    # EU-Format, z. B. DE123456789
    tax_number:  str | None    # Deutsche Steuernummer, z. B. 123/456/78901
    address:     Address
    verified:    bool          # Manuell in der Oberfläche bestätigt
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

Eine validierte String-Unterklasse. Ungültige Werte werden stillschweigend auf `"other"` normalisiert.

```python
from finamt.agents.prompts import RECEIPT_CATEGORIES   # list[str]
from finamt.models import ReceiptCategory

cat = ReceiptCategory("software")       # gültig
cat = ReceiptCategory("unbekannter_wert")  # wird auf "other" normalisiert
cat = ReceiptCategory.other()           # expliziter Fallback
```

### Ausnahmen

Alle Ausnahmen erben von `FinanceAgentError`.

| Ausnahme | Wird ausgelöst bei |
|---|---|
| `OCRProcessingError` | PDF kann nicht geöffnet werden oder Textextraktion schlägt fehl |
| `LLMExtractionError` | Modell gibt nach allen Versuchen kein gültiges JSON zurück |
| `InvalidReceiptError` | Extrahierte Daten bestehen die fachliche Validierung nicht |

```python
from finamt.exceptions import FinanceAgentError, OCRProcessingError

try:
    result = agent.process_receipt("scan.pdf")
except OCRProcessingError as e:
    print(e)
```

## Extraktions-Pipeline

Jeder Beleg durchläuft vier sequenzielle LLM-Aufrufe, jeweils mit einem kurzen, fokussierten Prompt:

| Agent | Extrahiert |
|---|---|
| Agent 1 | Belegnummer, Datum, Kategorie |
| Agent 2 | Name des Geschäftspartners, USt-IdNr., Steuernummer, Adresse |
| Agent 3 | Gesamtbetrag, Umsatzsteuersatz, Umsatzsteuerbetrag |
| Agent 4 | Positionen (Beschreibung, MwSt.-Satz, MwSt.-Betrag, Preis) |

Die Ergebnisse werden in Python zusammengeführt — kein zusätzlicher LLM-Validierungsschritt. Die Debug-Ausgabe jedes Agenten (Prompt, Rohantwort, geparste JSON) wird unter `~/.finamt/debug/<beleg_id>/` gespeichert.

## Kategorien und Unterkategorien

Jeder Beleg wird mit einer Kategorie und einer optionalen Unterkategorie versehen. Kategorien entsprechen direkt den Positionen in den deutschen ELSTER-Formularen (EÜR / UStVA), sodass die richtigen Summen ohne manuelle Nachsortierung in die richtigen Felder einfließen.

| Kategorie | Unterkategorien |
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



## Aufgabenliste

**Belegverarbeitung**
- [x] OCR-Pipeline (PaddleOCR + Tesseract-Fallback)
- [x] 4-Agenten-Extraktion (Metadaten, Geschäftspartner, Beträge, Positionen)
- [x] Deduplizierung, Datenbankspeicherung, Stapelverarbeitung

**Steuerberechnung**
- [x] UStVA — Umsatzsteuervoranmeldung (monatlich / vierteljährlich)
- [x] UStE — Jährliche Umsatzsteuererklärung
- [x] EÜR — Einnahmenüberschussrechnung
- [x] KSt 1 — Körperschaftsteuererklärung
- [x] GewSt — Gewerbesteuererklärung
- [x] Jahresabschluss — Jahresabschluss (Bilanz + GuV, § 267a HGB)

**ELSTER-Übermittlung**
- [x] UStVA — ELSTER-XML-Generator + Kennzahlen-Mapper + RSA-Signierung + HTTP-Übermittlung
- [x] E-Bilanz — XBRL-Instanzdokument (HGB-Taxonomie v6, MicroBilG-Schema)
- [ ] E-Bilanz — ERiC-ctypes-Brücke für die eigentliche Übermittlung
- [ ] KSt, GewSt, UStVA, USt — ELSTER-XML-Generator
- [ ] EÜR, ESt — ELSTER-XML-Generator

**Validierung**
- [ ] XSD-Validierung des generierten XBRL gegen die HGB-Taxonomie
- [ ] ELSTER-Probelauf / Testserver-Validierung vor der Live-Übermittlung

## Mitwirken

1. Repository forken
2. Feature-Branch erstellen (`git checkout -b feature/meine-änderung`) und Änderungen vornehmen
3. Testsuite ausführen:
   ```bash
   pytest --cov=src --cov-report=term-missing
   ```
4. Lint und Formatierung mit ![Ruff](https://api.iconify.design/catppuccin:ruff.svg?height=16) Ruff:
   ```bash
   ruff check --fix src/ tests/
   ruff format src/ tests/
   ```
5. Dokumentation aktualisieren
6. Pull Request einreichen

## Lizenz

AGPL-3.0 — siehe [LICENSE](https://raw.githubusercontent.com/spaceoctahedron/finamt/main/LICENSE) für Details.

## Kommerzielle Lizenzierung

finamt ist unter der AGPL-3.0-Lizenz verfügbar.

Wer finamt in einem proprietären Umfeld nutzen möchte, ohne die AGPL-Pflichten zu erfüllen (z. B. ohne Offenlegung des Quellcodes oder für kommerzielle SaaS-Produkte), kann eine kommerzielle Lizenz erwerben.

Anfragen bitte an: info@spaceoctahedron.com

## Drittanbieter-Komponenten und Modelle

Diese Software ist abhängig von externen Bibliotheken und Diensten, darunter:

- PaddleOCR (Apache License 2.0)
- Tesseract OCR (Apache License 2.0)
- HuggingFace Hub / transformers (Apache License 2.0)
- mlx-lm (MIT License, nur Apple Silicon)

finamt lädt Sprachmodelle (z. B. Mistral, Qwen) beim ersten Start von HuggingFace herunter und speichert sie lokal zwischen.

Diese Modelle werden **nicht** mit dieser Software ausgeliefert und unterliegen ihren eigenen Lizenzbedingungen.
Die Nutzerinnen und Nutzer sind dafür verantwortlich, die jeweiligen Nutzungsbedingungen beim Herunterladen und Verwenden dieser Modelle einzuhalten.

## Haftungsausschluss

Diese Software wird ausschließlich zu Informations- und Automatisierungszwecken bereitgestellt.

Sie stellt **keine** steuerliche, rechtliche oder buchhalterische Beratung dar.

Obwohl finamt darauf ausgelegt ist, die Vorbereitung deutscher steuerrelevanter Daten (z. B. Umsatzsteuervoranmeldungen, EÜR, ELSTER-Übermittlungen) zu unterstützen, wird keine Gewähr übernommen für:

- Korrektheit der extrahierten Daten
- Vollständigkeit der Buchführungsunterlagen
- Einhaltung der geltenden Steuergesetze und -vorschriften
- Akzeptanz durch die Steuerbehörden

Die Nutzerinnen und Nutzer sind allein dafür verantwortlich, alle Ausgaben vor der Einreichung bei einer Behörde zu überprüfen.

**Bei rechtlich verbindlichen Fragen wenden Sie sich stets an eine zugelassene Steuerberaterin oder einen zugelassenen Steuerberater.**

Im größtmöglichen gesetzlich zulässigen Umfang übernimmt Space Octahedron GmbH keine Haftung für:

- Fehler bei der OCR- oder KI-gestützten Extraktion
- Fehlerhafte Klassifizierungen oder Berechnungen
- Abgelehnte oder fehlerhafte Steuererklärungen
- Finanzielle Verluste oder Bußgelder, die durch die Nutzung dieser Software entstehen

## Produktinformationen (ELSTER)

- **Produktname:** Space Octahedron® finamt
- **Hersteller:** Space Octahedron GmbH
- **Kontakt:** info@spaceoctahedron.com
