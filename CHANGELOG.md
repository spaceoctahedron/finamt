# Changelog

## Version 0.23.0 ()

### KSt — ELSTER submission via ERiC

## Version 0.22.2 (2026-08-08)

### UStVA — ELSTER submission via ERiC

The UStVA panel now supports direct ELSTER transmission for quarterly and monthly VAT pre-returns, matching the USt annual panel feature-for-feature.

- **New backend endpoints** — `POST /tax/ustva/submit` and `POST /tax/ustva/xml` handle period resolution (months 1–12 → ERiC period 1–12; quarters 1–4 → ERiC periods 41–44), receipt aggregation, address/cert fallback from the taxpayer profile, ERiC validation and submission, XML archiving to `submitted_returns/`, and recording the submission in the project DB.
- **Re-submit guard** — loads existing real (`use_test: false`) submissions for the active period on mount; warns before a second prod transmission and requires explicit confirmation.
- **XML archive + overview refresh** — submitted XML is saved as `UStVA_{year}_{Q|M}_{ts}_{prod|test}.xml`; the returns overview checkmark (`ustva_q1`…`ustva_m12`) fills immediately via `onSubmissionChange`.
- **Period hint** — when the sidebar is set to "all years" the submission section shows a hint to select a specific month or quarter instead of the send button.

## Version 0.21.2 (2026-07-26)

### Milestone: end-to-end ELSTER submission confirmed

The annual Umsatzsteuererklärung was submitted directly from the finamt UI to the Finanzamt via ERiC. The Finanzamt acknowledged receipt with a formal confirmation letter — the first fully automated tax submission produced by finamt.

Additional UX hardening shipped alongside:
- Re-submit guard: UStPanel now fetches existing submissions on load and warns before a second real (non-test) transmission.
- Submitted XML is automatically archived in `submitted_returns/` and can be viewed later from the returns overview.
- Returns overview refreshes immediately after a submission without a page reload.


## Version 0.20.2 (2026-06-13)

### ELSTER data consolidation and Steuernummer utilities

- **Fix: ERiC log directory scoped to project** — `eric.log` was written to the global `~/.finamt/eric_logs/` directory, leaking log data across projects and appearing in the database selector. The log path is now derived from the active project layout root (e.g. `~/.finamt/so/eric_logs/`). Both the E-Bilanz and USt/UStVA submission paths are fixed; the fallback to `~/.finamt/eric_logs` in `_run_ust` is removed. `GET /tax/ebilanz/settings` now also falls back to `FINAMT_ELSTER_HERSTELLER_ID` and `FINAMT_ERIC_HOME` environment variables when no project-specific value is stored, so `.env` values are reflected in the UI without a manual save step.

- **Refactor: ELSTER credentials centralised in taxpayer profile** — all ELSTER submission fields (Steuernummer, Finanzamtsnr., Länderkennzeichen, Hersteller-ID, certificate, PIN) that were duplicated inside each tax return panel (UStPanel, JahresabschlussPanel) are removed from those panels. A single **ELSTER-DATEN** collapsible section is added to the taxpayer profile modal ("Bearbeiten"). Credentials are loaded once at the app level via `GET /tax/ebilanz/settings` + `GET /tax/ebilanz/cert` and passed down as an `ElsterSettings` prop, eliminating redundant API calls per panel. The "An ELSTER übermitteln" section in each panel now shows a compact read-only summary of the stored settings with a hint to open the taxpayer profile when data is incomplete.

- **New: 13-digit federal Steuernummer utility (`steuernummer.ts`)** — `finamt-ui/src/utils/steuernummer.ts` implements conversion of a locally-formatted Steuernummer (e.g. `37/539/50531`) to the 13-digit bundeseinheitliche format (e.g. `1137053950531`) for all 16 Bundesländer, including the special-case formats for Bayern (3-digit FA), NRW (4-digit Bezirk + 4-digit UUUU), and the various 2-digit-FA states. Helper functions: `toFederal13()`, `finanzamtNrFromSteuernummer()` (derives the 4-digit Finanzamtsnummer automatically), `bundeslandKzFromState()` (maps free-text state name or abbreviation to the Länderkennzeichen), `is13Digit()`. Finanzamtsnr. and Länder-Kz. fields in the ELSTER-DATEN section are computed and shown read-only — the user never needs to enter them manually.

- **Style: sharp black shadow on all popup / modal / overlay elements** — modal dialogs, dropdowns, and overlay panels now consistently use `border-2 border-black shadow-[4px_4px_0_#000] rounded`, matching the AgentConfig selector style. `shadow-xl` and coloured borders are removed from popup elements. The rule is codified in `.github/copilot-instructions.md`.


## Version 0.20.1 (2026-06-01)

### Annual Umsatzsteuererklärung (USt 2A) — ELSTER submission via ERiC

The `/tax/uste/submit` and `/tax/uste/xml` endpoints now build and transmit a fully valid **E50 annual VAT return** (Umsatzsteuerjahreserklärung, Vordruck USt 2 A) through the official **ERiC native library**.

**What's new**

- **E50 XML structure** — `ElsterXMLBuilder.build_ustva()` with `period=0` now emits a proper `<E50>` document in the `http://finkonsens.de/elster/elstererklaerung/ust/e50/v{year}` namespace, replacing the old (broken) `<Anmeldungssteuern>` wrapper that was only valid for periodic UStVA.
- **Vorsatz** — all mandatory fields populated: `Unterfallart=50`, `Vorgang=01`, `StNr` (11-digit local format, Berlin zero-insertion handled), `Zeitraum`, `AbsName/AbsStr/AbsPlz/AbsOrt`, `OrdNrArt=S`, `Bescheid=2`.
- **USt2A** — full `Allg/Unternehmen/Adr`, `Best_Art/E3002203` (Besteuerungsart), `Umsaetze` (19 %/7 % sales), `Abz_VoSt` (Vorsteuer + Einfuhrumsatzsteuer), `Berech_USt` (output−input, Vorauszahlungssoll, Abschlusszahlung/Erstattungsanspruch) sections with correct German decimal format (`1234,56`).
- **Berlin Steuernummer normalisation fix** — `normalise_steuernummer()` now correctly inserts the zero *after* the 2-digit FA for Berlin (e.g. `37/539/50531` → `1137053950531` instead of the wrong `1103753950531`). A `_BL_FA_LOCAL_LEN` map makes the rule extensible to other 2-digit-FA states.
- **BUFA consistency** — `NutzdatenHeader/Empfaenger` is always derived from `steuernr[:4]` for annual submissions, guaranteeing it matches the `Vorsatz/StNr` prefix that ERiC validates.
- **New `ElsterConfig` fields** — `company_name`, `street`, `house_number`, `postal_code`, `city`, `besteuerungsart` (`"1"`/`"2"`/`"3"`), `vorauszahlungssoll`; all optional with sensible defaults.
- **New `UStESubmitRequest` fields** — same address/tax fields exposed in the API; the submit handler falls back to the taxpayer profile stored in the project database when fields are not provided in the request body.
- **Address validation** — a clear `ValueError` is raised early when `street`, `postal_code`, or `city` are missing, rather than sending an incomplete document that ERiC rejects.


## Version 0.20.0 (2026-05-25)

### Removed system dependency: Ollama → HuggingFace direct inference

- **Ollama removed** — finamt no longer requires a running Ollama server. Models are downloaded automatically from HuggingFace on first use and cached in `~/.cache/huggingface/hub`. No install step, no background daemon, no admin rights needed.
- **Apple Silicon optimisation (mlx-lm)** — on Apple Silicon Macs the inference backend switches to `mlx-lm` with 4-bit quantised MLX models from `mlx-community`. Benchmarks show ~13 % lower wall-clock time per receipt compared to the equivalent Ollama run (mistral:7b: 79 s vs 92 s for 5 receipts; qwen2.5:7b: 79 s vs 90 s), because MLX exploits the unified memory architecture directly.
- **Cross-platform transformers fallback** — on Linux / Windows / Intel Macs the `transformers` pipeline is used with optional 4-bit quantisation via `bitsandbytes` on CUDA hardware.
- **New dependency** — `huggingface-hub>=0.23.0`, `transformers>=4.40.0`, `accelerate>=0.30.0`; `mlx-lm>=0.22.0` added as a conditional dependency for `sys_platform == 'darwin' and platform_machine == 'arm64'`.
- **Supported models** — `mistral:7b` (default) and `qwen2.5:7b-instruct-q4_K_M`; mapped to `mlx-community/Mistral-7B-Instruct-v0.3-4bit` / `mlx-community/Qwen2.5-7B-Instruct-4bit` on Apple Silicon and to `mistralai/Mistral-7B-Instruct-v0.3` / `Qwen/Qwen2.5-7B-Instruct` elsewhere.
- **Config** — `FINAMT_OLLAMA_BASE_URL` environment variable removed; all config dataclass fields referencing Ollama removed.


## Version 0.19.0 (2026-05-25)

### New features / improvements

- **Frontend: KYC / KYS relationship map** — a new collapsible dashboard panel visualises business relationships on an interactive world map. The **KYC** tab plots customers (revenue / sales receipts) and the **KYS** tab plots suppliers (expense / purchase receipts). Each location is represented by a circle whose radius is proportional to the total amount exchanged on a logarithmic scale, keeping visual differences meaningful without outliers dominating. Hovering a dot shows the counterparty name, total amount, and transaction count.

- **Frontend: address geocoding via Nominatim** — counterparty addresses (city + postcode + country) are resolved to coordinates using the OpenStreetMap Nominatim API. To stay within the 1 req/s rate limit, calls are throttled and only fired for addresses that are not already cached. Multiple counterparties sharing the same city are merged into a single dot.

- **Backend + Frontend: persistent geocode cache in project DB** — resolved coordinates are stored in the `project_metadata` table under the key `geocode_cache` via two new API endpoints (`GET /geocode-cache`, `POST /geocode-cache`). On subsequent loads the cache is fetched first, so Nominatim is only called for addresses that have never been seen before; already-resolved addresses render instantly with no network round-trip.

- **Frontend: unmapped amount disclosure** — the panel legend explicitly reports the number of transactions and the total amount that could not be placed on the map due to missing or unresolvable address data, making the gap between the map total and the dashboard expense total transparent.


## Version 0.18.0 (2026-05-17)

### New features / improvements

- **Frontend: financial returns overview with submission tracking** — a new collapsible "Eingereichte Erklärungen" section in the dashboard lists all relevant tax returns (UStVA, UStE, GewStE, KStE, E-Bilanz) for the active reporting year. Each return is represented by a checkbox that the user can tick to mark it as submitted. The state is persisted in the project database and restored across sessions. A progress indicator shows how many of the returns have been filed.

- **Frontend: Agent Config selector in the header** — a new `AgentConfigSelector` component is added to the app header, left of the database selector. It displays the active LLM model name with its brand icon (`IconQwen` / `IconMistral` / `IconAgent` fallback) preceded by a robot `IconAgent` icon and the "Agent Config" label. Clicking the model pill opens a dropdown panel with three sections: **Model** (preset radio buttons for `qwen2.5:7b-instruct-q4_K_M`, `qwen2.5:14b-instruct`, `mistral:7b` plus a free-text custom model input), **Agent settings** (`agent_timeout`, `agent_num_ctx`, `agent_max_retries`, `ollama_base_url`), and **OCR settings** (`ocr_language`, `ocr_timeout`, `ocr_preprocess`, `tesseract_cmd`, `pdf_dpi`). Changes are applied via `PUT /config` and take effect immediately without restarting the server. The panel shows an amber border while unsaved and a "Saved ✓" confirmation on success.

- **Backend: `GET /config` expanded + `PUT /config` endpoint** — `GET /config` now returns all runtime-configurable fields: `agent_model`, `agent_timeout`, `agent_num_ctx`, `agent_max_retries`, `ollama_base_url`, `ocr_language`, `ocr_timeout`, `ocr_preprocess`, `tesseract_cmd`, `pdf_dpi`, `categories`, and `default_db`. A new `PUT /config` endpoint accepts a partial JSON body, validates the keys against the known config schema, merges them into an in-process `_runtime_cfg` dict, and returns the updated effective config. Both `FinanceAgent` call sites now use `_effective_agents_cfg()` and `_effective_ocr_cfg()` helpers that merge the persisted settings with any runtime overrides, so model or OCR changes are picked up immediately for the next receipt processed.

- **Frontend: signature in the footer**.


## Version 0.17.3 (2026-05-17)

### Repository / licensing

- **License changed from MIT to AGPL-3.0** — `pyproject.toml` updated: `license = {text = "AGPL-3.0"}`, PyPI classifier `License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)` added.
- **Repository ownership transferred to Space Octahedron GmbH** — all GitHub URLs updated from `yauheniya-ai/finamt` to `spaceoctahedron/finamt` across `README.md`, `readme/README_de.md`, and `pyproject.toml` project URLs.
- **AGPL-3.0 license badge** added to both `README.md` and `readme/README_de.md`.
- **README.md** — minor copy fix in Features bullet (stray line break removed).
- **readme/README_de.md** — synced with English version: Mistral entry added to backend tech stack, Contributing steps reordered to match English (tests → lint), License section updated to AGPL-3.0, Commercial Licensing section added.

## Version 0.17.2 (2026-05-03)

### Tooling / code quality

- **Linting: Black + flake8 → Ruff** — dev dependencies replaced with `ruff>=0.4`; `[tool.ruff]` config added to `pyproject.toml` (rules: E, W, F, I, UP, B, C4; `line-length = 100`).
- **30 lint errors fixed** across `src/` and `tests/`: unused imports (F401), trailing whitespace (W291), ambiguous variable names (E741), unused variables (F841), missing `from exc` on re-raises (B904), over-broad `pytest.raises(Exception)` (B017), `dict()` → `{}` literal (C408), and minor B007/B008 issues.

## Version 0.17.1 (2026-04-26)

### New features / improvements

- **Frontend: Taxonomie — custom dropdown replaces native `<select>`** — the HGB taxonomy version selector in the E-Bilanz config block is replaced with a styled custom dropdown matching the rest of the UI. Options are labelled "Taxonomie 6.9 vom 01.04.2025" and "Taxonomie 6.8 vom 01.04.2024". An `ElsterTip` tooltip links to `esteuer.de` for the official taxonomy overview.

- **Frontend: `ElsterTip` — link support and hover-gap fix** — `ElsterTip` gains `link` and `linkLabel` props so tooltips can embed a clickable external link. An invisible `after:` pseudo-element bridge between the trigger icon and the tooltip card prevents the tooltip from closing when the cursor moves to click the link.

- **Frontend: ERiC config block — cert + PIN merged, tooltip updated** — the certificate path/upload and PIN field are now grouped in a single white config card instead of two separate boxes. The ERiC tooltip is shortened to one concise sentence with a direct link to the ELSTER developer portal (`esteuer.de`); the redundant "ERiC darf nicht in finamt enthalten sein" note is removed.

- **Frontend: Hersteller-ID — width capped, tooltip shortened** — the Hersteller-ID input is capped at `w-32` to prevent it from stretching across the full config card. The tooltip is shortened to a single sentence and links directly to the correct software-developer registration page on the ELSTER portal.

- **Frontend: company logo in taxpayer profile** — `TaxpayerProfile` gains an optional `logo?: string | null` field (base64 data URL). The taxpayer modal shows a logo upload section above the Unternehmensgegenstand field with Change and Remove buttons. The logo is persisted in the project database via the existing `PUT /taxpayer` endpoint.

- **Frontend: Bilanz PDF — logo in header** — the generated Bilanz PDF header now renders the company logo (if set) above the company name and the "Bilanz zum…" title, in that order.

- **Frontend: Bilanz PDF — `html2canvas` + `jsPDF` download** — `generateBilanzPdf()` no longer relies on `iframe.contentWindow.print()`. It uses `html2canvas` to rasterise the A4 paper sheet and `jsPDF` to produce a clean single-page PDF download, eliminating browser print-dialog artifacts and header/footer chrome. `jspdf` and `html2canvas` added as npm dependencies.

- **Backend: `GET /submissions` + `POST /submissions`** — two new endpoints in `api.py` for tracking E-Bilanz submission history per project. `POST /submissions` records a submission event (year, timestamp, optional note); `GET /submissions` returns the list ordered by date descending.

- **Frontend: submission tracking UI** — the E-Bilanz section gains a "Als eingereicht markieren" button that calls `POST /submissions` and displays a green "Eingereicht am …" badge. A collapsible submission history list shows all past submissions for the active project.

- **Frontend: i18n** — new keys added to `de.json` and `en.json`: `jab_optional`, `jab_mark_submitted`, `jab_submitted_on`, `jab_submission_history`, `jab_bilanz_generating`, `taxpayer_logo_*`, `jab_bilanz_save` updated.


## Version 0.17.0 (2026-04-26)

### New features

- **Backend: ERiC integration — E-Bilanz submission via official ELSTER library** — new module `finamt.tax.eric_wrapper` provides a ctypes bridge to `libericapi.dylib` (ERiC 43.x). `EricSession` / `EricBuffer` / `EricCertificate` context managers handle library lifecycle, buffer allocation, and PKCS#12 certificate loading.

- **Backend: `EBilanzEnvelopeBuilder` + `ElsterEricClient`** — `EBilanzEnvelopeBuilder` wraps an XBRL instance in a schema-valid ELSTER v11 envelope (`Verfahren=ElsterBilanz`, `DatenArt=Bilanz`, `Bilanz_6_9`), deriving `Länderkennzeichen`, BUFA, and `<Ziel>` automatically from the normalised 13-digit Steuernummer. `ElsterEricClient` exposes `validate_ebilanz()` and `submit_ebilanz()`. Required fields `DatenLieferant`, `Datei` (with `CMSEncryptedData`/`GZIP`), and `HerstellerID` are included; the envelope passes ERiC schema validation with zero errors.

- **Backend: `POST /tax/ebilanz/submit`** — transmits the E-Bilanz to ELSTER via ERiC. All ELSTER parameters (`eric_home`, `cert_path`, `cert_password`, `hersteller_id`, `bundesland_kz`) can be supplied in the request body, via environment variables, or are loaded from the project database as a fallback. `bundesland_kz` is auto-derived from the taxpayer profile city/state when not provided. Supports `validate_only=true` for a dry-run ERiC schema check without transmission.

- **Frontend: E-Bilanz submission panel** — the Jahresabschluss panel gains a full ELSTER submission UI: ERiC library path, `.pfx` certificate upload, PIN field, Hersteller-ID field (with tooltip explaining registration at `elster.de/eportal/softwareentwickler`), test-mode toggle, and Validate / Submit buttons. All settings are persisted in the project database and reloaded automatically. `bundesland_kz` is resolved transparently from the stored taxpayer address.

## Version 0.16.2 (2026-04-25)

### Bug fixes / improvements

- **Frontend: Jahresabschluss panel — negative number format** — negative amounts in the GuV and Bilanz tables are now rendered with a `−` prefix in black instead of red accountant parentheses, matching the KSt panel.

## Version 0.16.1 (2026-04-19)

### Bug fixes / improvements

- **Frontend: Bilanz preview — in-app modal replaces `window.open`** — `generateBilanzPdf()` no longer opens the Bilanz in a new browser tab (which rendered full-width with no margins). It now opens an in-app modal overlay (`bilanzPreviewOpen` / `bilanzHtml` state, `bilanzIframeRef`). The modal is exactly 210 mm wide with a light-amber (`#fef3c7`) background; the white paper sheet inside has `padding: 20mm 18mm`, `min-height: 257mm` (full A4), and a drop shadow — matching a classic A4 document look. On print (`@media print`) all decoration is stripped so the printed output is clean.

- **Frontend: Bilanz modal header — Print + Save button** — the modal now has a single combined button showing `[print icon] Drucken / [pdf icon] Speichern` (DE) / `[print icon] Print / [pdf icon] Save PDF` (EN) that triggers `iframe.contentWindow.print()`, which opens the browser print dialog where the user can print or save as PDF. The redundant `↓ HTML` download button was removed.

- **Frontend: `IconPrint` added to `icons.tsx`** — mingcute `print-fill` SVG inlined as `IconPrint` in `frontend/src/constants/icons.tsx` (fills with `currentColor`) for offline use. `IconFilePdf` was already present from v0.16.0.

- **Frontend: Bilanz PDF — negative number format** — negative amounts in the generated Bilanz HTML are now rendered as minus prefix instead of accountant parentheses and without red color. 

- **Frontend: Bilanz PDF — footnote link** — "Erstellt mit finamt" in the footnote is now a clickable `<a href="https://pypi.org/project/finamt/">` with `<strong>` text. Prints in black via `@media print { a { color: #000 } }`.

- **Frontend: E-Bilanz / Bundesanzeiger buttons — icons** — all three action buttons in the Filing Obligations section now show icons alongside their text labels:
  - **XBRL herunterladen** → `mdi:download` icon (via `@iconify/react`)
  - **XBRL-Vorschau** → `mdi:eye-outline` icon
  - **PDF generieren** → `IconFilePdf` icon (inlined, offline-safe); the redundant `(Bilanz)` suffix removed from both `en.json` and `de.json`.

- **Frontend: i18n** — new keys `jab_bilanz_print` ("Drucken" / "Print") and `jab_bilanz_save` ("Speichern" / "Save PDF") added to `en.json` and `de.json`; `jab_bundesanzeiger_pdf` updated (removed `(Bilanz)` suffix in both locales).

## Version 0.16.0 (2026-04-19)

### New features / improvements

- **Backend: `finamt.tax.ebilanz` — XBRL instance builder** — new module `pypi/src/finamt/tax/ebilanz.py` generates a valid HGB XBRL instance document for Kleinstkapitalgesellschaften (§ 267a HGB, MicroBilG schema). Uses the official HGB taxonomy v6 (2025-04-01). Key implementation details:
  - `EBilanzConfig` dataclass holds company master data (Steuernummer, Firmenname, Rechtsform, fiscal year dates, preparer).
  - `build_xbrl(jab, cfg) -> bytes` produces a UTF-8 encoded `.xbrl` file ready for ERiC transmission.
  - `write_xbrl(jab, cfg, path)` convenience wrapper writes to disk.
  - Correct XBRL sign convention: expense concepts (`materialServices`, `staff`, `deprAmort`, `otherCost`, `interestExpense`) are stored as **positive** values; the calculation linkbase carries `weight="-1"` for each, so validators subtract them automatically — negating them in the instance document would cause double-negation and fail calculation validation.
  - `bs.eqLiab.equity.subscribed.unpaidCap` (nicht eingeforderte ausstehende Einlagen) is stored as a **positive** value for the same reason (`weight="-1"` in the balance-sheet calculation linkbase).
  - Balancing identity verified: `subscribed − unpaidCap + netIncome = equity = totalAssets`.
  - `lxml>=4.9.0` added as a core dependency in `pyproject.toml`.

- **Backend: `POST /tax/ebilanz/xbrl` endpoint** — new FastAPI endpoint in `pypi/src/finamt/ui/api.py` accepts an `EBilanzRequest` JSON body (db path + `EBilanzConfig` fields), generates the Jahresabschluss from the database, builds the XBRL instance via `build_xbrl`, and streams the file as a `Content-Disposition: attachment` response with MIME type `application/xml`.

- **Frontend: Jahresabschluss — Filing Obligations section** — `JahresabschlussPanel.tsx` gains a "Pflichten nach Jahresabschluss" block with two filing boxes:
  - **E-Bilanz (§ 5b EStG)** — blue box; 2-step guide: (1) Download XBRL button (calls `POST /tax/ebilanz/xbrl`, triggers browser download of the `.xbrl` file; taxonomy version note: HGB v6 2025-04-01 accepted by ERiC for VZ 2022–2025) and (2) ERiC transmission instructions with links to `elster.de` certificate and ERiC developer download pages.
  - **Bundesanzeiger (§ 325 + § 326 Abs. 2 HGB)** — amber box; 5-step guide covering the online Bundesanzeiger portal flow.
  - `apiBase` and `dbPath` props added to `JahresabschlussPanel`; passed down through `Dashboard` (which receives them from `App.tsx` via `API_BASE` and `activeDb`).

- **Frontend: i18n** — new keys under `jab_filing_section`, `jab_filing_note`, `jab_ebilanz_*`, and `jab_bundesanzeiger_*` added to `en.json` and `de.json`.




## Version 0.15.0 (2026-04-13)

### New features / improvements

- **Frontend: KSt 1 Abschnitt 4 · Steuerberechnung removed** — the KSt/SolZ/Gesamtbelastung rows were mistakenly placed inside the KSt 1 Hauptvordruck section; ELSTER's KSt 1 form does not contain a Steuerberechnung sub-section at this position; the rows and their unused computed variables (`koerperschaftsteuer`, `solidaritaet`, `gesamtbelastung`) are removed entirely.

- **Frontend: Z.9 · Rechtsform reads from taxpayer profile** — the Rechtsform row in KSt 1 Abschnitt 1 now displays the value from `taxpayer.rechtsform` (same as Z.1 · Name); when the profile field is empty it shows a dim `—` with a tooltip directing the user to the taxpayer profile, instead of the generic "manuell in ELSTER" placeholder.

- **Frontend: steuerliches Einlagekonto corrected to 0** — `einlagekontoAnfang` was previously set to `taxpayer.eingezahlt` (the partially paid-in Stammkapital fraction). `eingezahlt` is a partial Nennkapital payment and is already counted as Nennkapital — it does not constitute an entry in the steuerliches Einlagekonto (§ 27 KStG), which only records contributions *above* registered share capital (Agios, Zuzahlungen, etc.). For a standard GmbH with no such extras the Einlagekonto is 0. In a profitable year the old code would have understated ausschüttbarer Gewinn by the `eingezahlt` amount.

- **Frontend: Z.17 Eigenkapital laut Steuerbilanz is now cumulative** — `eigenkapitalApprox` was previously `Stammkapital + current-year Steuerbilanzgewinn`, which reset to Stammkapital at the start of every VZ instead of carrying forward prior-year retained earnings / accumulated losses. It now sums the Steuerbilanzgewinn for every year from `taxpayer.gründungsjahr` through the VZ year-end using `allReceipts`, so the figure compounds correctly across years (e.g. 2022: 25 000 − 12 205 = 12 795; 2023: 12 795 − 318 = 12 477).

- **Frontend: Z.19 explained in tooltip** — the Positiver Bestand des steuerlichen Einlagekontos row in Anlage KSt 1 F Abschnitt 3 gains an ElsterTip explaining that normal Stammkapital payments are *not* Einlagekonto contributions and that the field is 0 for a standard GmbH.

- **Frontend: Z.17 action label simplified** — `kst_kst1_nein_action` changed from `⚠ Nein — aktiv anklicken!` to `☑ Nein`; `kst_manual_zero` changed from `0 € (manuell)` to `0 €` across all panels that use these shared keys.


## Version 0.14.4 (2026-04-08)

### New features

- **Frontend: Collapsible "Unternehmens-/GmbH-Daten" section in taxpayer modal** — the company-facts block (Gegenstand, Rechtsform, Betriebsstätte toggles, Gründungsjahr, Stammkapital, Eingezahlt, Hebesatz) is now hidden behind a chevron toggle (`companyOpen` state, collapsed by default). This keeps the modal compact for sole traders and freelancers who do not need GmbH-specific fields.

- **Frontend: `labelWidth` prop on `FieldRow` in PreviewPanel** — the `FieldRow` component accepts an optional `labelWidth` string (Tailwind class, default `w-28`). The Einfuhrumsatzsteuer row in edit mode uses `labelWidth="w-40"` to prevent the longer label from wrapping, and is placed before the Netto field to match the ELSTER form order.

- **Frontend: ELSTER tooltips across UStVA and UStE panels** — a new `ElsterTip` component renders the ELSTER green-asterisk logo next to a row label and shows a black tooltip on hover. The tooltip accepts a `lines: string[]` prop (rendered with line breaks) and applies `normal-case tracking-normal` to prevent uppercase CSS inheritance from parent table headers. Tooltips are wired in both panels:

  - **UStVA** — "Steuerpflichtige Umsätze" heading (Kapitel 3), line 66 (two-line Kapitel 7 / § 15 citation), line 83 (Kapitel 9).
  - **UStE** — "Steuerpflichtige Umsätze" heading (Kapitel 3); individual sales rows for 19 %, 7 %, and 0 % rates (Zeilen 22, 25, 28); Vorsteuerbeträge row (Kapitel 10, Zeile 79); Vorauszahlungssoll row (Kapitel 12, Zeile 119); Abschlusszahlung row (Zeile 120). Line numbers are removed from the UStE display as they refer to ELSTER form positions, not accounting line codes. The "Verbleibende Jahressteuer" sublabel and the separate line-83 net-liability row are removed from UStE; the Vorauszahlungssoll row always shows the full signed net-liability amount.

  All tooltip strings are stored in `de.json` / `en.json` under `dashboard.elster_tip_*` keys.


## Version 0.14.3 (2026-04-07)

### New features

- **Frontend: Einfuhrumsatzsteuer (§ 15 Abs. 1 Nr. 2 UStG) in UStVA and UStE panels** — the existing `einfuhr_vat: number | null` field on `Receipt` (import VAT on goods from non-EU countries, reported separately by customs) is now surfaced in both tax panels. In the **UStVA** panel, a dedicated line 62 row ("Einfuhrumsatzsteuer") is shown beneath the regular input-VAT row (line 66) whenever the period contains at least one receipt with a non-zero `einfuhr_vat`; the two rows are summed into the total input-VAT figure used for the net-liability calculation. In the annual **UStE** panel the same logic applies: lines 122 (regular Vorsteuer) and 124 (Einfuhrumsatzsteuer) are shown separately, followed by an optional line 131 subtotal when import VAT is present; both feed into the line-83 net-liability total. New i18n keys added: `vat_einfuhr_label` (DE: "Einfuhrumsatzsteuer § 15 Abs. 1 Nr. 2 UStG"; EN: "Import VAT § 15 (1) no. 2 UStG"), `uste_input_sum_label` (DE: "Summe Vorsteuerbeträge"; EN: "Total input VAT").

- **Frontend: GewStE panel expanded with ELSTER-aligned sections and editable Betriebsstätte fields** — the Gewerbesteuererklärung panel is restructured into three labelled sections matching the GewSt 1 A form:

  - **Allgemeine Angaben** (lines 3, 4, 14) — displays Unternehmen/Firma (from `taxpayer.name`), Gegenstand des Unternehmens (line 4, new `gegenstand` field), and Rechtsform (line 14, new `rechtsform` field, defaults to "GmbH"). Both fields are editable in the taxpayer modal and persisted in the project database.

  - **Angaben zur Betriebsstätte** (lines 26–32) — lines 26 ("Betriebsstätten in mehreren Gemeinden"), 27 ("Betriebsstätte erstreckt sich über mehrere Gemeinden"), and 28 ("Einzige Betriebsstätte im Jahresverlauf verlegt") are now **editable Ja/Nein toggles** backed by three new boolean fields on `TaxpayerProfile` (`betriebsstaette_mehrere`, `betriebsstaette_erstreckt`, `betriebsstaette_verlegt`), stored in the project database and restored across sessions. "Ja" is highlighted in amber to draw attention. Lines 31 (PLZ) and 32 (Ort) are read from `taxpayer.postcode` / `taxpayer.city`. A small ✎ link next to each toggle opens the taxpayer modal directly.

  - **Gewinn aus Gewerbebetrieb** — the computation table is unchanged in content but the Gewerbeertrag row is now labelled with ELSTER line number **39** (§ 7 GewStG).

  - **Taxpayer modal** — a new "Betriebsstätte (GewSt 1A Z. 26–28)" section with styled Ja/Nein toggle buttons for the three flags is inserted into the modal's GmbH/Company-facts section; `gegenstand` and `rechtsform` text inputs are also added.

  New i18n keys added (DE and EN): `gewst_allgemeine_angaben`, `gewst_firma`, `gewst_gegenstand`, `gewst_rechtsform`, `gewst_betriebsstaette`, `gewst_mehrere_gemeinden`, `gewst_erstreckt_gemeinden`, `gewst_verlegt`, `gewst_plz`, `gewst_ort`, `gewst_gewinn_section`; sidebar keys: `taxpayer_betriebsstaette_section`, `taxpayer_bs_mehrere`, `taxpayer_bs_erstreckt`, `taxpayer_bs_verlegt`, `taxpayer_gegenstand`, `taxpayer_rechtsform`.


## Version 0.14.2 (2026-04-06)

### New features

- **Frontend + Backend: "Recently uploaded" sidebar filter** — a new filter row is added below the period selector in the sidebar. Four toggle pills (`1h`, `8h`, `Today`, `3 days`) let the user filter the receipt list to entries uploaded within that window, independently of the active year/quarter/month filter. The filter is database-backed: `created_at` (UTC ISO-8601, already stored in the `receipts` table) is now included in `ReceiptData.to_dict()` and propagated through `_row_to_receipt()` in `sqlite.py`, so the filter works across browser sessions and devices. On the frontend, `created_at: string | null` is added to the `Receipt` TypeScript type and a `matchesRecent()` helper compares the timestamp against the selected cutoff. The period controls dim while a recent window is active. A dedicated empty-state message is shown when no receipts fall within the window. Full EN/DE translations added (`sidebar.recent_filter.*`).

- **Frontend: name search across all receipts** — a search input row (magnify icon + transparent field + × clear button) is shown below the recent filter row in the sidebar. Typing any substring filters the receipt list by supplier name (`vendor` or counterparty name) across *all* uploaded receipts, bypassing the active period and recent filters. The priority chain is: name search > recent filter > period filter. The period and recent controls dim while a name query is active. A "no results" empty state with a dedicated message is shown when the query matches nothing. Full EN/DE translations added (`sidebar.search_placeholder`, `sidebar.search_no_results`).

## Version 0.14.1 (2026-04-06)

### New features

- **Frontend + Backend: `public_fees` category with subcategories** — a new top-level expense category "Public Fees" / "Pflichtabgaben" (icon `mdi:gavel`) is added for mandatory contributions such as ARD/ZDF broadcasting fees, IHK/HWK chamber fees, and Berufsgenossenschaft contributions. Four predefined subcategories are included: `broadcasting_fee`, `ihk_hwk`, `berufsgenossenschaft`, `other_public_fee`. The category is registered in `CATEGORY_META` and `CATEGORY_SUBCATEGORIES` (frontend), added to `RECEIPT_CATEGORIES` so the backend validator no longer falls back to `"other"`, and German heuristic keywords (`rundfunkbeitrag`, `ard`, `zdf`, `gez`, `ihk`, `hwk`, `berufsgenossenschaft`, `pflichtbeitrag`, `kammerbeitrag`) are added to `_CATEGORY_KEYWORDS` for offline classification. Full EN/DE translations added; README category tables and the test suite updated.

- **Frontend + Backend: category / subcategory autofill from DB history when selecting a verified counterparty** — in the Manual Entry modal, picking an entry from the "Select from verified" counterparty picker now automatically prefills the Category and Subcategory fields. A new `GET /counterparties/{cp_id}/defaults` endpoint queries the most frequent `(category, subcategory)` pair stored for that counterparty, preferring non-`"other"` values. The frontend fires the request immediately after selection and updates the form fields if the response carries data.

- **Frontend + Backend: "Verified" checkbox in Manual Entry modal** — a checkbox is shown next to the counterparty name field in the manual entry form. When ticked and the entry is saved, the backend sets `verified = 1` on the linked counterparty row via `repo.set_counterparty_verified()`. This mirrors the verified-tick workflow in the Preview Panel and lets users confirm a new supplier's identity in a single step without opening the Counterparty Explorer afterwards.

## Version 0.14.0 (2026-04-05)

### New features

- **Frontend: subcategory and notes in Manual Entry modal** — the "Eintrag erstellen" modal now includes a subcategory dropdown (populated from `CATEGORY_SUBCATEGORIES`, resets when category changes) and a free-text notes field. Both values are sent to `POST /receipts` and persisted in the database. Notes are shown in view mode in the Preview Panel and editable in edit mode alongside the existing subcategory selector.

### Bug fixes / improvements

- **Frontend + Backend: cashflow-only receipts reflected in Bilanz** — `tax_settlement` and `capital_movement` receipts were correctly excluded from the GuV but were also silently dropped from `Kassenbestand`, making tax refunds and capital movements invisible in the balance sheet. A dedicated `cashflowNetCurrent` accumulator now tracks these receipts for the reporting year. The amount is added to `Kassenbestand` (Aktiva) and displayed as a separate **"B. Steuererstattungen/-zahlungen (netto)"** line on the Passiva side, keeping the balance sheet balanced without distorting profit-and-loss. Prior-year cashflow-only amounts are carried into the opening-cash carry-forward as before. The same fix is applied to the Python `bilanz.py` backend (`generate_jahresabschluss`), which previously had no cashflow-only exclusion at all. New i18n key `jab_steuerpositionen` added to both locales.

## Version 0.13.2 (2026-04-05)

### New features

- **Frontend: Cashflow-only categories** — two new receipt categories (`tax_settlement`, `capital_movement`) represent balance-sheet cash movements that are not part of profit-and-loss (e.g. tax refunds from Finanzamt, owner capital contributions). A `CASHFLOW_ONLY_CATS` constant (exported from `constants/index.ts`) drives all exclusion logic across the app:
  - **Category dropdowns** — the category picker in `PreviewPanel` and the `ManualEntryModal` in the sidebar now render a visual separator ("Nur Cashflow" / "Cashflow only") above the two cashflow entries via a `flatMap` divider logic over `CATEGORY_META`.
  - **Sidebar cashflow section** — receipts belonging to cashflow categories are shown in a dedicated collapsible "Cashflow" section below the revenue and expense lists. Each cashflow category renders both its sale and purchase sub-groups. A signed total (income positive, expense negative) is displayed in the section header.
  - **Dashboard P&L exclusion** — stat cards, bar charts, and all tax panels (Jahresabschluss / GuV, Gewerbesteuererklärung, Körperschaftsteuererklärung) filter out cashflow receipts. VAT totals and the Umsatzsteuer panels continue to operate on all receipts including cashflow ones.
  - **i18n** — new keys `cashflow_section` ("Cashflow") and `cashflow_only_label` ("Nur Cashflow" / "Cashflow only") added to both `de.json` and `en.json`.

## Version 0.13.1 (2026-04-05)

### New features

- **Frontend: Umsatzsteuer-Voranmeldung (UStVA) panel made collapsible** — the previously static VAT advance-return section is extracted into a dedicated `UStVAPanel` component with a toggle header identical in structure to the Jahresabschluss panel. The subtitle shows the declaration type (Monats-/Quartals-/Jahreserklärung) derived from the active sidebar period filter, followed by a § 18 UStG law link and the period tag (e.g. "Q4 2022"). The panel is collapsed by default and only renders the ELSTER table when open.

- **Frontend: Umsatzsteuererklärung (UStE) panel** — a new collapsible annual VAT return panel (§ 18 Abs. 3 UStG) is added after the UStVA panel and before the Gewerbesteuererklärung. It always covers the full reporting year (derived from the sidebar period, not the active sub-period filter) and shows the same ELSTER-style table (lines 81, 86, 87, 66, 83) as the UStVA but with an annual scope. A year badge with a sidebar hint is shown when the "All" period is active. The net liability row subtitle distinguishes between remaining annual balance (Vorauszahlungen are offset by the tax authority) and annual surplus. A disclaimer reminds users to verify completeness before ELSTER submission.

- **Frontend: Gewerbesteuererklärung (GewStE) panel** — a new collapsible trade-tax panel (§§ 14 ff. GewStG) is added after the UStE panel. It computes: **Gewerbeertrag** from net revenue minus net expenses for the reporting year; **rounded Gewerbeertrag** (truncated down to full €100, § 11 Abs. 1 GewStG); **Steuermessbetrag** = rounded × 3.5 % Steuermesszahl; **Gewerbesteuer** = Steuermessbetrag × Hebesatz. No Freibetrag is applied (GmbH/Kapitalgesellschaft). The Hebesatz is read from the persisted taxpayer profile (`taxpayer.hebesatz ?? 400`) and displayed as a read-only badge with an "Bearbeiten →" link that opens the taxpayer modal. A "no liability" notice is shown when Gewerbeertrag ≤ 0. The disclaimer notes §§ 8/9 GewStG Hinzurechnungen/Kürzungen must be applied manually.

- **Frontend: Körperschaftsteuererklärung (KStE) panel** — a new collapsible panel is added between the Gewerbesteuererklärung and the Jahresabschluss, covering the annual corporate tax return (§ 31 KStG, Formular KSt 1). The panel computes the approximate zu versteuerndes Einkommen (zvE) from net revenue minus net expenses for the reporting year, using the `business_net ?? net_amount` fallback chain. It then derives: **Körperschaftsteuer** = max(zvE, 0) × 15 % (§ 23 KStG flat rate for GmbH/AG); **Solidaritätszuschlag** = KSt × 5.5 %; and **Gesamtbelastung** = KSt + SolZ. A "no liability" notice is shown when zvE ≤ 0. The disclaimer notes that non-deductible expenses (§ 10 KStG), loss carry-forwards (§ 10d EStG), and other manual adjustments must be applied before ELSTER submission. Translations added to both EN and DE locale files (`kst_title`, `kst_subtitle`, `kst_zve`, `kst_rate`, `kst_kst`, `kst_solz`, `kst_solz_rate`, `kst_total`, `kst_no_liability`, `kst_disclaimer`).

- **Frontend: LawLink component — clickable § citations in all panel headers** — a new `LawLink` helper renders a law paragraph reference as a dotted-underlined external link to `gesetze-im-internet.de`, with a small `mdi:open-in-new` icon. Click events are stop-propagated so clicking a law link does not toggle the panel. All five tax panels now embed law links in their subtitles:
  - Umsatzsteuer-Voranmeldung: [§ 18 UStG](https://www.gesetze-im-internet.de/ustg_1980/__18.html)
  - Umsatzsteuererklärung: [§ 18 UStG](https://www.gesetze-im-internet.de/ustg_1980/__18.html)
  - Gewerbesteuererklärung: [§§ 14 ff. GewStG](https://www.gesetze-im-internet.de/gewstg/__14.html)
  - Körperschaftsteuererklärung: [§ 31 KStG](https://www.gesetze-im-internet.de/kstg_1977/__31.html)
  - Jahresabschluss: [§§ 242–256a HGB](https://www.gesetze-im-internet.de/hgb/__242.html) and [§ 267a HGB](https://www.gesetze-im-internet.de/hgb/__267a.html)

### Bug fixes / improvements

- **Frontend: VAT totals corrected — `business_vat` used instead of raw `vat_amount`** — the stat cards, UStVA panel, and UStE panel were summing `r.vat_amount`, the raw AI-extracted field. This field is unreliable (the LLM sometimes interchanges net and VAT amounts) and could produce impossible figures (e.g. €878 input VAT from €1,656 total expenses, implying >53 % effective rate). All VAT summations are now computed as `r.business_vat ?? r.vat_amount ?? 0`, where `business_vat = (total_amount − net_amount) × (1 − private_use_share)` is the backend's authoritative computed property — always self-consistent with the stored gross/net pair. Net bases in ELSTER rows likewise use `r.business_net ?? r.net_amount ?? fallback`. The `business_net` and `business_vat` fields were already present in the serialised response and in the TypeScript `Receipt` type.

- **Frontend: Hebesatz persisted in taxpayer profile** — the Gewerbesteuer Hebesatz was previously a local `useState(400)` with `+/−` buttons inside `GewStPanel`, resetting to 400 % on every page reload. It is now part of `TaxpayerProfile` (`hebesatz?: number | null`) and stored in the project database via the existing `PUT /taxpayer` endpoint. The taxpayer modal gains a number input for Hebesatz (min 200, max 900, step 50, placeholder 400) in the GmbH/Company section. The `GewStPanel` reads the value from `taxpayer.hebesatz ?? 400` and shows it as a read-only badge. New i18n key: `taxpayer_hebesatz_field` (EN: "Hebesatz (municipal multiplier)"; DE: "Hebesatz").

- **Frontend: "Gewerbesteuererklärung" and "Umsatzsteuererklärung" preview tiles removed** — the bottom tile grid previously contained four dashed placeholder cards ("coming soon") including `ust` and `gst`. These are now real panels higher on the page; their tiles are removed from the grid. Only the `eur` (Einkommensteuer) and `est` (Einkommensteuer) placeholder tiles remain.

- **Frontend: Country/State modal overflow fixed** — the State and Country inputs in the taxpayer modal are displayed side-by-side in a `flex` row inside a fixed-width `w-80` card. Without a width constraint the inputs could overflow the card boundary. Both inputs now have `min-w-0` applied, allowing them to shrink within the flex container correctly.

- **Frontend: panel headers de-capitalised and standardised** — all five collapsible panel headings previously used the Tailwind `uppercase` CSS class, which is atypical for German UI text. The class is removed and titles are now displayed in natural mixed case with a short abbreviation in parentheses: "Umsatzsteuer-Voranmeldung (UStVA)", "Umsatzsteuererklärung (UStE)", "Gewerbesteuererklärung (GewStE)", "Körperschaftsteuererklärung (KStE)", "Jahresabschluss (JA)". The same titles are used for both EN and DE locales (German tax terms are not translated). The `jab_title` and `jab_subtitle` locale keys are consolidated; the subtitle is now rendered directly in the component with inline `LawLink` references instead of a single i18n string.

- **Frontend: UStVA subtitle shows declaration type and period** — the subtitle of the Umsatzsteuer-Voranmeldung panel previously showed a raw document count ("Basierend auf N Dokumenten in der aktuellen Ansicht"). It now shows the declaration type derived from the sidebar period filter ("Monatserklärung", "Quartalserklärung", or "Jahreserklärung") followed by the § 18 UStG law link and the period tag (e.g. "Q4 2022" or "März 2022"). The `UStVAPanel` component gains a `period: PeriodFilter` prop for this purpose. New i18n keys added: `decl_monthly`, `decl_quarterly`, `decl_annual` (EN: "Monthly return", "Quarterly return", "Annual return"; DE: "Monatserklärung", "Quartalserklärung", "Jahreserklärung").

## Version 0.13.0 (2026-04-04)

### New features

- **Backend: `POST /receipts` — manual receipt entry without a file** — a new endpoint accepts a JSON body (`date`, `vendor`, `receipt_type`, `category`, `net_amount`, `vat_percentage`, `description`, `currency`) and creates a `ReceiptData` record directly in the project database. The receipt ID is a SHA-256 hash of a unique seed (UUID4), so each manual entry is always distinct. Net / total / VAT amounts are computed from `net_amount × (1 + vat_percentage / 100)`. Returns the same response shape as the upload endpoint. Useful for entries that have no file (VAT refunds from Finanzamt, bank fees, cash outlays).

- **Frontend: "Manual Entry" button and modal** — a new amber *Manual Entry* button is shown below the *Upload Receipt* / *Upload Invoice* button in the sidebar. Clicking it opens a modal with fields: type toggle (Ausgabe / Einnahme), date, counterparty, category dropdown, net amount, VAT rate (0 / 7 / 19 %), and optional notes. On save the frontend POSTs to `POST /receipts`, inserts the returned record into the list, and auto-selects it. Works with the active project DB like upload does.

- **Frontend: GmbH company facts persisted in taxpayer profile** — founding year (`gründungsjahr`), registered share capital (`stammkapital`), and paid-in capital at founding (`eingezahlt`) are now part of `TaxpayerProfile` and are stored in the project database via the existing `PUT /taxpayer` endpoint. Previously these values were local React state that reset to hardcoded defaults on every page reload. The taxpayer modal gains a new *Company / GmbH Facts* section with three number inputs for these fields. The *Annual Financial Statements* panel reads the values from the persisted taxpayer profile, shows them as read-only badges, and provides an *Edit →* link that opens the taxpayer modal directly.

### Bug fixes / improvements

- **Frontend: balance sheet badge no longer uses an em dash** — the `jab_balanced` string previously read `"Balance sheet balances — Aktiva = Passiva."` / `"Bilanz ausgeglichen — Aktiva = Passiva."` where the em dash could be misread as a minus sign. Reformulated to `"Balance sheet balanced: Aktiva = Passiva."` / `"Bilanz ausgeglichen: Aktiva = Passiva."`.

- **Frontend: share-capital label corrected in both locales** — the English translation showed `"Stammkapital (reg.)"` (German word); corrected to `"Share capital (reg.)"`. The German label changed from `"Stammkapital (eingetragen)"` to `"Stammkapital (reg.)"` for consistency.

- **Frontend: singular/plural type labels corrected in DE locale** — the type-toggle in the upload section and the manual-entry modal use the singular keys `sidebar.expense` / `sidebar.revenue` (individual transaction type), while the receipt-list section headers use the plural `sidebar.expenses` / `sidebar.revenues`. The German `sidebar.revenue` key was incorrectly set to `"Einnahmen"` (plural); corrected to `"Einnahme"`.

## Version 0.12.6 (2026-04-03)

### Bug fixes

- **Frontend: NETTO shown incorrectly when VAT splits are present** — the net amount field in the Amounts section always displayed `receipt.net_amount` from the DB, even when the receipt had VAT splits. With splits (e.g. 19 % → 12,50 € net and 0 % → 15,79 € net) the correct NETTO is the sum of the split net amounts (28,29 €), not the stored scalar. The field now sums `net_amount` across all `vat_splits` in view mode, and sums the live draft fields in edit mode when split-VAT is active; falls back to `receipt.net_amount` when no splits exist.

- **Frontend: search field added to "Select from verified" counterparty picker** — the verified-counterparty dropdown previously required scrolling through the full alphabetical list to find an entry. A search input (auto-focused on open) is now shown at the top of the dropdown; it filters by name, VAT ID, and tax number as you type. Selecting an entry or closing the dropdown resets the search. A "No results" message is shown when the query matches nothing.

- **Backend: counterparty edits no longer silently set `verified = 1`** — any save that touched counterparty fields (name, address, VAT ID, tax number) automatically forced `verified = 1` in `update_receipt_fields()` and `update_counterparty()` in `sqlite.py`, meaning every routine edit implicitly verified the counterparty without any user action. Both paths now leave the `verified` flag untouched unless it is explicitly included in the request payload. The verified flag is only written when the user ticks the checkbox or selects an entry from the verified-counterparty picker. The orphan-cleanup routine relies on receipt references (not the flag) and is unaffected.

## Version 0.12.5 (2026-04-03)

### Bug fixes

- **Frontend / Backend: historical exchange rate used for foreign-currency receipts** — the currency converter previously always fetched the *current* live rate even when the receipt had an older date, meaning a 2022 GBP receipt would be converted at the 2026 rate, producing an incorrect EUR figure for tax reporting. The `GET /fx-rate` proxy endpoint now accepts an optional `date=YYYY-MM-DD` query parameter and calls the Frankfurter historical endpoint (`/v1/YYYY-MM-DD?from=…&to=EUR`) when it is present, falling back to `/v1/latest` only when no date is available. The `CurrencyConverter` frontend component gains a `receiptDate` prop and appends `&date=…` to the proxy URL when the receipt has a date; the rate resets and re-fetches automatically whenever the receipt or its date changes. The displayed "as of" label now reflects the actual rate date returned by the API (which may be the nearest preceding business day for weekends and holidays).

- **Frontend: missing i18n keys in the currency converter section** — three translation keys used by the currency converter component (`preview.field_currency`, `preview.rate_label`, `preview.rate_as_of`) had no entries in either locale file and were silently falling back to their English `defaultValue` strings in German mode. Keys added: `field_currency` → `Währung` / `Currency`, `rate_label` → `Kurs` / `Rate`, `rate_as_of` → `Stand {{date}}` / `as of {{date}}`.

## Version 0.12.4 (2026-04-03)

### Bug fixes

- **Frontend: exchange-rate fetch hardened and CORS fixed** — browser-side calls to `api.frankfurter.app` were blocked by a CORS policy because the API redirects to `api.frankfurter.dev`, which does not send `Access-Control-Allow-Origin` headers. The request is now made server-side via a new `GET /fx-rate?from=XXX&to=EUR` proxy endpoint in `api.py` (stdlib `urllib.request`, no new dependencies). The frontend `CurrencyConverter` component calls the local backend instead. Additionally: the response is now validated (`res.ok` check plus null-rate check), two distinct error messages are shown (`rate_fetch_failed` vs `rate_no_data`), a **Retry** button re-triggers the fetch without clearing a manually-typed rate, and the placeholder changes from empty to "enter manually" when no live rate is available.

- **Frontend: missing exchange rate now shown as a prominent warning** — when a receipt is in a non-EUR currency and no exchange rate could be resolved (live fetch failed and no manual rate entered), the UI previously displayed amounts silently in the receipt currency while tax reports (`generate_eur`, UStVA) used the raw foreign-currency amounts as if they were EUR, producing incorrect totals. Two warning banners are now rendered: one inside the amounts card (below the converter) and one in the top status-banner area (always visible regardless of scroll position). Both banners disappear automatically as soon as a rate is entered. New i18n keys added: `rate_fetch_failed`, `rate_no_data`, `rate_retry`, `rate_manual_placeholder`, `no_rate_warning`, `no_rate_banner` (German and English).

- **Frontend: edit-mode amount fields now use the locale's decimal separator** — opening edit mode populated numeric fields (GESAMT, MWST. %, MWST. Betrag, item amounts, VAT-split fields) using JavaScript's `.toString()`, which always produces a dot (e.g. `9.76`). In German locale all other values are displayed with a comma, so the inputs appeared inconsistent or confusing. A new `numToInputStr` helper formats numbers with up to 5 significant decimal places, strips trailing zeros, and replaces the dot with a comma when the active language is `de` (e.g. `9.76 → "9,76"`, `0.1 → "0,1"`, `10.0 → "10"`). All `.toString()` calls in `startEditing`, item-draft initialisation, and VAT-split-draft initialisation are replaced with `numToInputStr()`. The existing `parseDecimal` helper already accepts both separators on save, so round-tripping is consistent.

## Version 0.12.3 (2026-04-03)

### Bug fixes

- **Frontend: German decimal separator accepted in amount fields** — entering values with a comma as the decimal separator (e.g. `195,66`) previously caused silent truncation to the integer part (`195.00`) because JavaScript's native `parseFloat` stops at the first non-numeric character. A `parseDecimal` helper is now used throughout `PreviewPanel.tsx` that normalises the comma to a dot before parsing (`195,66 → 195.66`). Affected fields: GESAMT, MWST. %, MWST. Betrag, all item amounts (total price, VAT rate, VAT amount), all VAT-split fields, and the currency-converter custom-rate input.

- **Frontend / Backend: VAT and net amount calculated correctly from gross price** — previously NETTO was derived as `BRUTTO − stored_vat_amount`, which produced wrong results whenever the LLM extracted a slightly inconsistent VAT figure. The formula is now `NETTO = BRUTTO ÷ (1 + MwSt.%/100)` — the only algebraically correct decomposition of a gross (VAT-inclusive) price. For example: 575,66 € gross @ 19 % → 483,75 € net → 91,91 € VAT (instead of the previously displayed 80,95 €). Changes applied in `models.py` (`net_amount` property, `generate_postings`, `business_vat`) and in the `PreviewPanel.tsx` display and private-use preview calculation.

## Version 0.12.2 (2026-04-03)

Rebuild UI and reupload

## Version 0.12.1 (2026-04-03)

Taxpayer profile persisted in project database instead of browser localStorage

- **`project_metadata` table** — new key/value table added to the SQLite schema via the existing idempotent `_migrate()` path (`CREATE TABLE IF NOT EXISTS project_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)`); existing databases are migrated automatically on first open
- **`get_metadata` / `set_metadata` / `delete_metadata`** — three new methods on `SQLiteRepository`; values are stored as JSON; `set_metadata` uses `INSERT … ON CONFLICT DO UPDATE` (upsert) so repeated saves are safe
- **`GET /taxpayer`** — new endpoint returning `{"taxpayer": {...} | null}` for the active project; accepts `?db=` like all other endpoints; returns `{"taxpayer": null}` for projects with no DB yet
- **`PUT /taxpayer`** — saves the request body JSON as the taxpayer profile under the key `"taxpayer"` in `project_metadata`; initialises the DB directory if it does not exist yet
- **`DELETE /taxpayer`** — removes the taxpayer profile from `project_metadata` (204 No Content); no-op when the DB or key is absent
- **Frontend: localStorage removed** — `taxpayerKey()` and `loadTaxpayer()` helpers removed from `App.tsx`; the `taxpayer` state is now initialised to `null` and populated via `GET /taxpayer` whenever `activeDb` changes; saves and clears fire `PUT` / `DELETE` to the API (fire-and-forget, state updated optimistically); taxpayer data is now portable across browsers and devices for the same project


## Version 0.12.0 (2026-04-03)

CLI rewrite: argparse → Typer with Rich colours and ASCII banner

- **argparse replaced by Typer** — the CLI is fully rewritten using [Typer](https://typer.tiangolo.com/); the four top-level actions are now explicit subcommands (`process`, `batch`, `ustva`, `serve`) instead of mutually-exclusive flags; `rich_markup_mode="rich"` is enabled on the app so docstrings and help text support Rich markup natively
- **`finamt process`** — processes a single receipt PDF; accepts `--file`, `--type`, `--db`, and `--verbose`; delegates to `FinamtCLI.process_receipt()`
- **`finamt batch`** — batch-processes all PDFs in a directory; accepts `--dir`, `--type`, `--db`, and `--verbose`; delegates to `FinamtCLI.batch_process()`
- **`finamt ustva`** — generates a UStVA report for a quarter; accepts `--quarter`, `--year`, `--db`, and `--verbose`; delegates to `FinamtCLI.run_ustva()`
- **`finamt serve`** — starts the finamt web UI server; accepts `--host`, `--port`, and `--db`; delegates to `FinamtCLI.serve()`
- **ASCII banner** — invoking `finamt` with no arguments prints a bold-yellow ASCII art banner followed by the help text and exits with code 0; implemented via `invoke_without_command=True` on the `@app.callback()` and `ctx.get_help()`
- **Rich colour output** — `rprint` (from `rich`) replaces `typer.echo` for banner and version output; the version string is rendered as `finamt version <bold-green>x.y.z</bold-green>`; `Console` from `rich.console` is available for future styled output
- **`FinamtCLI` class unchanged** — all business logic (`process_receipt`, `batch_process`, `run_ustva`, `serve`, etc.) remains in the `FinamtCLI` class and is not affected by the CLI layer rewrite
- **Test suite updated** — `test_cli_inprocess.py` migrated from `sys.argv` patching + direct `main()` calls to `typer.testing.CliRunner`; `TestBuildParser` replaced by `TestTyperCLI`; all 54 tests pass

## Version 0.11.4 (2026-03-26)

Batch upload cancellation and taxpayer address supplement

- **Batch upload cancel button** — a small `✕` button appears beside the upload progress indicator while a batch is in progress; clicking it calls `AbortController.abort()`, which cancels the in-flight `fetch` request and stops the loop before the next file begins; `AbortError` is caught silently so no spurious error banner appears; the button disappears automatically once the queue finishes or is cancelled
- **`TaxpayerProfile.address_supplement`** — new `address_supplement: string` field added to the `TaxpayerProfile` type; the `TaxpayerModal` renders a dedicated input between the street and postcode/city rows, labelled `"Address Supplement"` / `"Adresszusatz"`; the field is initialised from `localStorage` and saved back on submit
- **Dashboard taxpayer address display** — the taxpayer address line in the dashboard header now includes `address_supplement` between the street and the postcode/city segment, matching the `formatAddress()` order used elsewhere
- **Upload query string updated** — `App.tsx` includes `taxpayer_address_supplement` in the upload stream URL; `api.py` accepts the new optional query parameter and forwards it in `_taxpayer_info`
- **Localisation** — `taxpayer_address_supplement` key added to both EN (`"Address Supplement"`) and DE (`"Adresszusatz"`) locale files; `cancel_upload` key added (EN: `"Cancel upload"`, DE: `"Upload abbrechen"`)

## Version 0.11.3 (2026-03-26)

Offline-safe icons — inline SVG components replace CDN-fetched icon font

- **`constants/icons.tsx` added** — all icons previously loaded at runtime via `@iconify/react` are now shipped as inline React SVG components (`IconClose`, `IconDelete`, `IconDatabase`, `IconDatabaseCheck`, `IconDatabaseOff`, `IconChevronDown`, `IconRefresh`, `IconPlusCircle`, `IconSpinner`); each component uses `fill="currentColor"` and spreads `SVGProps<SVGSVGElement>` so `className`, `style`, and all other SVG attributes work identically to the Iconify `<Icon>` wrapper
- **`DBSelector.tsx`** — `@iconify/react` import removed; all nine icon usages replaced with inline components
- **`Sidebar.tsx`**, **`PreviewPanel.tsx`**, **`Dashboard.tsx`** — high-frequency icons (`mdi:chevron-down`, `mdi:close`, `mdi:trash-can-outline`, `svg-spinners:12-dots-scale-rotate`, `mdi:plus-circle-outline`) replaced with inline components; remaining low-frequency icons (dynamic category icons, `mdi:upload`, etc.) retain `@iconify/react` for now
- **Motivation** — `@iconify/react` loads icon data from the Iconify CDN when a specific icon has not been bundled; with no network access the icons silently disappeared; inline SVGs are bundled at build time and render correctly offline

Counterparties Explorer — keep receipt visible in background

- **Backdrop removed** — the `CounterpartiesExplorer` overlay no longer renders a `bg-black/70` full-screen backdrop; the outer wrapper uses `pointer-events-none` with no background so the receipt (sidebar list, panel content) stays fully visible behind the sliding panel; the panel itself retains `pointer-events-auto` so all interactions work as before
- **Fullscreen mode fix** — in fullscreen view (PDF on the left, data panel on the right) opening the Counterparties Explorer previously replaced the entire left side with a blank black `div`; the `cpExplorerOpen ? <div className="flex-1 bg-black" /> :` branch is removed so the receipt PDF or image continues to display on the left while the explorer slides in from the right, consistent with non-fullscreen behaviour

## Version 0.11.1 (2026-03-23)

Verified-tick revert

- **Verified-tick revert** — the amber `◎ VERIFIED` read-only badge introduced in 0.11.0 is removed; `isVerified` in `PreviewPanel` reverts to `localVerified !== null ? localVerified : cpVerifiedFromReceipt`, restoring natural inheritance of the DB-stored `verified` state; the 0.11.0 workaround was only needed because of VAT-ID-based counterparty merging, which is now fixed at the backend, so the checkbox once again reflects the actual DB value on load

## Version 0.11.0 (2026-03-23)

Data-integrity fixes, validation-as-warnings, and taxpayer-info cleanup

- **Verified-tick auto-fill removed** — the "Verified" checkbox in `PreviewPanel` no longer inherits the DB-stored `verified` state automatically on first render; `isVerified` is now `localVerified === true`, meaning the tick is only set when the user explicitly activates it in the current session; when a counterparty is already verified in the DB but the user has not yet confirmed in the current session an amber `◎ VERIFIED` read-only badge is shown instead of a pre-checked box
- **VAT-ID-based counterparty merging removed** — `get_or_create_counterparty()` in `sqlite.py` previously merged any counterparty whose VAT ID matched an existing row regardless of name, silently overwriting different companies with the same tax ID (e.g. Deutsche Bank AG clobbering Deutsche Bahn AG data); the VAT-ID match path is removed entirely and deduplication now uses case-insensitive name comparison only
- **Duplicate VAT-ID highlighting** — the Counterparties Explorer in the frontend detects multiple counterparty rows sharing the same non-empty VAT ID and marks each with a red `⚠` icon and a tooltip hint; this surfaces data-quality issues introduced by earlier imports without preventing the user from working with affected records
- **Validation rewritten as warnings** — `ReceiptData.validate()` no longer raises or returns a hard-fail boolean; instead it accumulates all rule violations into a new `validation_warnings: List[str]` field; the method still returns `False` when warnings exist for callers that check the flag, but no code now blocks on it; the `InvalidReceiptError` raise in `agent.py` is removed so **every receipt is always saved** regardless of data quality
- **Validation rules changed** — future-dated receipts were previously a hard block; they now emit `"Receipt date is in the future"` as a warning and save normally; all other rules (total ≤ 0, VAT% out of range, VAT amount > total, private_use_share out of [0, 1]) are likewise demoted to warnings
- **`validation_warnings` persisted** — a new `validation_warnings TEXT` column (JSON array) is added to the `receipts` table via the idempotent migration loop in `sqlite.py`; `save()` serialises the list, `_row_to_receipt()` deserialises it, and `to_dict()` exposes it; pre-existing rows default to `NULL` / empty list
- **UI: validation-warning banner** — when a loaded receipt carries warnings, `PreviewPanel` renders a red banner beneath the header that lists each warning; the sidebar receipt list shows a red `⚠` icon on any receipt with at least one warning
- **Taxpayer-info postprocessing cleanup** — a new `_strip_taxpayer_fields(counterparty, taxpayer_info)` helper in `pipeline.py` silently nulls out any counterparty field (`name`, `vat_id`, `tax_number`) whose value is an exact case-insensitive match for the corresponding taxpayer field; this prevents Agent 2 from defaulting to the taxpayer's own identifiers when no real counterparty data appears in the document; address sub-fields are not checked because `taxpayer_info` carries only a composite address string; no warnings or log entries are emitted
- **Tests** — `test_pipeline.py` added with 11 unit tests covering `_strip_taxpayer_fields` (no taxpayer, empty taxpayer, exact matches per field, case/whitespace normalisation, partial-match safety, multi-field strip, address-fields untouched, immutability of input dict); `test_models.py` updated for future-date warning; `test_storage.py` updated for name-only counterparty deduplication; total suite: 498 tests passing

## Version 0.10.1 (2026-03-21)

Batch upload live sidebar updates
- **Sidebar updates per receipt** — during a batch upload the sidebar list now refreshes after each individual receipt completes rather than waiting for the entire batch to finish; each result is prepended to the list immediately when its SSE `result` event arrives, so receipts appear one by one as processing progresses; the final full re-fetch at the end of the batch still runs to ensure the list is fully in sync with the server

## Version 0.10.0 (2026-03-21)

Taxpayer profile — prevent Agent 2 from confusing the document owner with the counterparty
- **`TaxpayerProfile` type** — new structured profile with `name`, `vat_id`, `tax_number`, `street`, `postcode`, `city`, `state`, and `country` fields; stored per project in `localStorage` under the key `finamt_taxpayer:<db_path>` so each project has independent data and switching databases immediately loads the correct profile
- **Agent 2 prompt injection** — `build_agent2_prompt()` accepts an optional `taxpayer_info` dict; when provided, an `IMPORTANT:` exclusion clause is appended to the prompt instructing the model not to extract the taxpayer's own name, VAT ID, tax number, or address as the counterparty; fixes mis-extraction on self-issued invoices where both parties' data appear on the document
- **Pipeline and agent threading** — `taxpayer_info` is passed from `FinanceAgent.process_receipt()` → `run_pipeline()` → `build_agent2_prompt()`; all intermediary signatures updated with the optional parameter, preserving full backward compatibility
- **API: upload stream endpoint updated** — `POST /receipts/upload/stream` accepts four new optional query parameters: `taxpayer_name`, `taxpayer_vat_id`, `taxpayer_tax_number`, `taxpayer_address`; the address is composited from the structured fields before being forwarded to the pipeline
- **UI: taxpayer data entry** — a `TaxpayerModal` (exported from `Sidebar.tsx`) provides input fields for all profile fields; address section uses a dedicated layout with a full-width street row, a postcode + city row, and a state + country row; the modal is owned by `App.tsx` and opened from two call sites
- **UI: sidebar prompt** — when no taxpayer is set, a short hint with a "Set up my taxpayer data" link appears below the upload button; the block is hidden once data is saved to avoid duplication
- **UI: dashboard header display** — when a taxpayer profile is set, the dashboard header shows `NAME (VATID • TAXNUMBER)` right-aligned on the same line as "Overview", with the formatted address and an inline "Edit" button on the line below

## Version 0.9.2 (2026-03-21)

Subcategory expansion and batch upload
- **Additional subcategories** — `CATEGORY_SUBCATEGORIES` extended with predefined entries for all previously empty categories: `products` (physical_goods, digital_goods, merchandise, samples), `material` (consumables, raw_materials, packaging, low_value_asset), `equipment` (computer, machinery, furniture, tools, low_value_asset), `marketing` (advertising, print_media, trade_fairs, sponsorship), `donations` (charitable, political, church, membership_fees), `other` (sundry, membership_fees); `services` gains `notary`; `travel` gains `per_diem`
- **ELSTER-aligned subcategory codes** — new keys follow German tax terminology where applicable: `per_diem` → Verpflegungspauschale, `low_value_asset` → Geringwertiges Wirtschaftsgut (GWG), `gifts` → Geschenke (§4 V EStG); all new codes are translated in both EN and DE locale files
- **Batch upload** — the file picker in the sidebar now accepts multiple files at once (`multiple` attribute); all selected files are processed sequentially, one SSE stream per file; progress indicator shows position within the batch (e.g. `[2/5] Agent 3/4…`); if a single file fails, processing continues for the remaining files and the error message is prefixed with the filename; the receipt list is refreshed once after all files complete and the last successfully processed receipt is selected

## Version 0.9.1 (2026-03-21)

Counterparty management improvements
- **Case-insensitive sort** — `list_all_counterparties()` and `list_verified_counterparties()` now sort by `LOWER(name)` so the list follows natural alphabetical order (`A a B b …`) instead of ASCII order (`A B … a b …`)
- **Reassign supplier per receipt** — new `relink_counterparty(receipt_id, fields)` method on `SQLiteRepository` runs `get_or_create_counterparty` and relinks only the specified receipt; the previously-linked counterparty row is untouched and cleaned up by the existing orphan-sweep on next open
- **`POST /receipts/{id}/counterparty`** — new API endpoint accepting `name`, `vat_id`, and optional address fields; finds or creates the matching counterparty and relinks only the target receipt, leaving all other receipts unchanged
- **UI: "Assign to different supplier"** — expandable row in the receipt edit form's counterparty section (below "Select from verified"); enter a supplier name and optional VAT-ID and click "Assign to this receipt" to relink just that receipt without affecting others

## Version 0.9.0 (2026-03-21)

Private-use handling with double-entry compatible postings
- **`private_use_share` field** — new `Decimal` field (0–1) added to `ReceiptData`; amounts (net, VAT, gross) are always stored at face value and never reduced directly; the share is applied at the posting and reporting layer so the full audit trail is preserved
- **`generate_postings()` method** — `ReceiptData` now generates a balanced list of double-entry `Posting` objects; purchases book 100 % of expense and input VAT as debits, then add three correction postings when `private_use_share > 0`: credit expense (net × share), credit input_vat (VAT × share), debit private_withdrawal (gross × share); sales generate accounts_receivable / revenue / output_vat entries unchanged
- **`business_net` / `business_vat` properties** — computed properties on `ReceiptData` returning the amounts attributable to the business after deducting the private share; exposed in `to_dict()` alongside `private_use_share`
- **New model types** — `Posting` dataclass, `PostingType` (expense, input_vat, accounts_payable, revenue, output_vat, accounts_receivable, private_withdrawal), and `PostingDirection` (debit, credit) added to `finamt.models` and exported from the top-level package
- **`receipts.private_use_share` column** — new `TEXT DEFAULT '0'` column added to the `receipts` table via the idempotent `ALTER TABLE` migration loop; pre-existing rows default to `0`; persisted and round-tripped through `save()`, `update()`, and `_row_to_receipt()`
- **`postings` table** — new table storing all double-entry journal entries with columns `id`, `receipt_id` (FK cascade), `position`, `posting_type`, `direction`, `amount`, `description`, `created_at`; postings are generated and written automatically on `save()`; regenerated via `_sync_postings()` whenever a financially sensitive field (`total_amount`, `vat_amount`, `vat_percentage`, `currency`, `receipt_type`, `private_use_share`) is updated
- **`get_postings(receipt_id)`** — new `SQLiteRepository` method returning the ordered `Posting` list for a receipt
- **`list_all_postings()`** — new method returning all postings joined with receipt metadata (date, type, category) as dicts; suitable for deriving an EÜR via aggregation
- **`update()` clamps private_use_share** — values outside [0, 1] are silently clamped; invalid strings are ignored
- **UStVA uses business portion only** — `generate_ustva()` now reads `business_vat` / `business_net` for purchase receipts so only the tax-deductible fraction is counted in the VAT pre-return; sales output VAT is unaffected
- **Validation** — `ReceiptData.validate()` rejects `private_use_share` outside [0, 1]
- **UI: Private Use slider** — edit mode for purchase receipts gains a **Private Use** row in the Amounts section with a 0–100 % range slider and a numeric input; a live preview below the slider shows the resulting Business Net and Business VAT as you drag; an ⓘ tooltip explains the accounting effect
- **UI: display mode** — when `private_use_share > 0` on a purchase receipt three read-only rows are shown: Private Use %, Business Net, Business VAT
- **UI: sales receipts unaffected** — the slider is hidden for sales; `private_use_share` is always sent as `0` for sale receipts on save
- **Localisation** — `field_private_use`, `field_business_net`, `field_business_vat`, and `private_use_tooltip` keys added to both EN and DE locale files
- **Test suite** — 63 new tests in `tests/test_private_use.py` covering `PostingDirection`/`PostingType` validation, `generate_postings()` balance and per-account amounts for zero/partial/full private shares on purchases and sales, DB round-trip, posting regeneration on update and cascade delete, `list_all_postings()`, and UStVA business-portion accounting

## Version 0.8.1 (2026-03-20)

Minor fixes to the verified counterparty UX
- **Fix: verified flag auto-ticking on edit** — `localVerified` is now reset to `null` when entering edit mode; previously the flag persisted across successive saves of the same receipt, causing `counterparty_verified: true` to be silently written to the backend without the user ever ticking the box
- **"Manage verified providers" moved to top of dropdown** — the option now appears as the first item in the verified counterparty picker, separated from the supplier list by a horizontal rule; previously it was buried at the bottom and invisible when the list was long
- **Alphabetic sorting in verified counterparty picker** — entries are now sorted case-insensitively and locale-aware (`localeCompare` with `sensitivity: "base"`); previously the list reflected raw database insertion order, with uppercase names appearing before lowercase ones

## Version 0.8.0 (2026-03-20)

Subcategories, category list overhaul, and type-independent category assignment
- **`subcategory` field** — new optional `TEXT` column added to the `receipts` table; existing rows are unaffected (column added via the idempotent `ALTER TABLE` migration loop, defaulting to `NULL`); stored and returned in `ReceiptData.to_dict()` and the API response
- **Category list revised** — `RECEIPT_CATEGORIES` updated to match the frontend: removed `consulting`, `internet`, and `taxes` as top-level categories (values previously assigned to these are normalised to `"other"` on load); added `car`, `financial`, `office`, `marketing`, and `donations`
- **Type-independent categories** — `REVENUE_CATS` constant removed; any category can now appear under either the Revenue or Expenses section of the sidebar depending on receipt type; the sidebar renders a single ordered category list for each section instead of splitting into revenue-only and expense-only subsets
- **Subcategory selector** — editing a receipt in the preview panel now shows a second dropdown below the category picker populated with predefined subcategories for the selected category (e.g. Software → Subscriptions, Pay as you go, Hosting, Domains …); changing the category resets the subcategory; changing the subcategory does not affect the category
- **Custom subcategories** — a `+` button next to the subcategory dropdown opens an inline text input; any custom value entered is added to the dropdown for that category and persisted in `localStorage` so it survives page reloads; custom entries are preserved when switching back to the same category
- **Subcategory in read mode** — the receipt detail panel shows the subcategory row only when a value is set, keeping the view uncluttered for receipts without one
- **Full translations** — all predefined subcategory keys are translated in both EN and DE locale files (e.g. `pay_as_you_go` → "Pay as you go" / "Nutzungsbasiert"); new top-level category labels also added (car/Fahrzeug, financial/Finanzen, office/Büro, marketing/Marketing, donations/Spenden)

## Version 0.7.5 (2026-03-20)

Dashboard collapsible sections and build-time version injection
- **Revenue and Expenses sections now collapsible** — the "Revenue" and "Expenses" headers in the Dashboard are now clickable toggle buttons; clicking a header collapses or expands its category chart and supplier breakdown, reducing visual clutter when only one side of the ledger is relevant
- **Footer version injected at build time** — the version string shown in the footer is no longer hardcoded; Vite reads the `version` field from `pyproject.toml` at build time and injects it as a compile-time constant, so the displayed version always matches the installed package without any manual updates

## Version 0.7.4 (2026-03-17)

Rebuild frontend static assets
- **Frontend bundle updated** — static UI assets rebuilt to include all 0.7.3 changes (single-supplier drill-down, verified counterparty re-linking fix)
- **Sidebar: supplier groups start collapsed** — supplier sub-rows under each category now load closed; click to expand; previously they loaded open which was noisy with many receipts
- **Sidebar: supplier-grouped receipt list** — receipts are grouped by supplier within each category; supplier row shows count (left) and total (right); individual receipts show as a single line with date, truncated receipt number, and amount
- **Sidebar: size hierarchy corrected** — section total > category total > supplier total > per-receipt amount

## Version 0.7.3 (2026-03-17)

- **Dashboard: single-supplier categories now expandable** — category rows in the chart previously showed a chevron and drill-down only when there were multiple suppliers; single-supplier categories showed no chevron and no way to see which supplier the total belonged to; now every category row is clickable and reveals the supplier breakdown regardless of count
- **Fix: "Select from verified" created duplicates instead of re-linking** — selecting a verified counterparty from the picker only copied its field values into the receipt draft; on save, the backend applied those values to the receipt's current (old) counterparty row, leaving the original verified CP untouched but producing a second identical `verified=1` row; now the frontend sends `counterparty_id` of the selected CP, the backend re-points the receipt to that existing row and skips field overwrites, and the old row is cleaned up as an orphan on the next DB open

## Version 0.7.2 (2026-03-17)

Counterparty management completely redesigned — replaced error-prone deduplication with a simple orphan-cleanup model
- **`_deduplicate_counterparties()` removed** — the automatic dedup that ran on every DB open was the source of every regression in this release; it silently discarded user edits and renames by deleting rows it considered duplicates
- **`_cleanup_orphaned_counterparties()` added** — the only automatic housekeeping; runs on DB open and deletes counterparty rows not referenced by any receipt; no silent re-pointing of receipts
- **Clone-on-edit removed** — editing a counterparty through the receipt panel now updates the row directly; all receipts sharing the same counterparty reflect the change (the expected behaviour when correcting a mis-labelled supplier)
- **`list_verified_counterparties()` simplified** — plain `SELECT … WHERE verified = 1 ORDER BY name ASC`; no more complex self-join dedup window
- **`update_counterparty()` simplified** — updates the allowed fields and always sets `verified = 1`; no more SUBSTANTIVE-field detection
- **Explorer save uses DB response** — `handleSave` in the Counterparty Explorer reads the API response body to update local state, so the displayed data always matches the database
- **PDF iframe suppressed when explorer is open** — native browser PDF controls (rendered outside z-index) no longer block the delete-confirmation Yes/No buttons

## Version 0.7.1 (2026-03-17)

Rebuild frontend static assets
- **Frontend bundle updated** — static UI assets were not rebuilt before the 0.7.0 PyPI release; this patch includes the correct production build reflecting all 0.7.0 UI changes (`address_supplement` field, Adresszusatz inputs, updated address display)

## Version 0.7.0 (2026-03-17)

Address supplement field — captures secondary address lines (building name, campus, suite) separately from street and number
- **`address_supplement` field** — new optional field added to the `Address` dataclass; all existing records remain compatible (populated with `NULL` automatically via idempotent `ALTER TABLE` migration)
- **Agent 2 prompt updated** — extraction JSON schema now includes `"address_supplement": null`; the rule instructs the model to extract secondary address lines (e.g. "Citywest Business Campus") and leave it `null` when none is present
- **Pipeline updated** — `_validate_agent2` key list and `expected_keys` for the LLM call include `address_supplement`; `_build_receipt_data` passes it through to `Address`
- **Database migration** — `address_supplement TEXT` column added to `counterparties` via the existing idempotent `ALTER TABLE` loop; all INSERT, SELECT, list, and update paths updated; `update_counterparty()` and `update()` allowed-field sets both include the new column
- **Frontend types** — `Address` type in `Sidebar.tsx` and `VerifiedCp`/`CpDraft` types in `PreviewPanel.tsx` extended with `address_supplement: string | null`
- **UI** — address supplement is shown in the receipt preview address section (between street and postcode/city), in the Counterparty Explorer list view, and in both edit forms (receipt-level and explorer inline); edit draft state and save payloads include the field
- **Localisation** — `cp_field_address_supplement` and `field_address_supplement` keys added (EN: "Address Supplement"; DE: "Adresszusatz")


## Version 0.6.0 (2026-03-15)

Multi-currency support — extraction, storage, and live EUR conversion in the UI
- **`currency` field extracted by Agent 3** — the amounts agent now returns an ISO 4217 currency code alongside totals and VAT; the prompt instructs the model to emit a 2–4 character uppercase code (e.g. `EUR`, `USD`, `GBP`); defaults to `EUR` when absent or invalid
- **Pipeline validation** — `_validate_agent3` enforces the regex `^[A-Z]{2,4}$`; any non-matching value is silently replaced with `EUR` so downstream code always receives a clean code
- **`ReceiptData.currency`** — new `str` field (default `"EUR"`) added to the dataclass and to `to_dict()`
- **Database migration** — `currency TEXT DEFAULT 'EUR'` column added to the `receipts` table via the existing idempotent `ALTER TABLE` loop; all pre-existing rows automatically receive `EUR`; INSERT, SELECT, and `update()` all handle the new column; `update()` validates the value with the same regex before writing
- **`Receipt` type extended** — frontend `Receipt` TypeScript type gains `currency: string`; the draft state, `startEditing()` initialiser, and the PATCH save payload all include currency
- **Currency row in preview panel** — a dedicated row is shown in the Amounts section between the total and the VAT fields; in view mode it displays the ISO code; in edit mode it provides an uppercase-forced text input (max 4 chars)
- **Live EUR conversion widget** — when the receipt currency is not `EUR`, a `CurrencyConverter` component fetches the current rate from `https://api.frankfurter.app/latest?from=<CUR>&to=EUR`, displays the rate date, and provides a manual rate-override input; the rate is reported back to the parent via callback
- **All amounts recalculated** — total, VAT amount, and net amount in the Amounts section are displayed through a `cvt()` helper: if a live (or overridden) rate is available the converted EUR figure is shown; otherwise the original amount is displayed in the receipt's own currency; the widget and all three fields update instantly when the rate changes or the user types a custom rate
- **Dynamic currency symbol in line items** — item rows use a `currSymbol()` helper that resolves `$` for USD, `£` for GBP, `€` for EUR, and the three-letter ISO code for anything else via `Intl.NumberFormat` with `currencyDisplay: "narrowSymbol"`; original item amounts are shown in the receipt currency unchanged; edit-mode column headers (`MwSt. {{sym}}`, `Gesamt {{sym}}`) use i18n interpolation so they update automatically

Supplier drill-down in dashboard category charts
- **Per-supplier breakdown** — each category bar in the expense and revenue charts can now be expanded to reveal a ranked list of individual suppliers and their totals for the active period (e.g. Software → Adobe €499 · Microsoft €499)
- **Toggle on click** — clicking a category row with more than one supplier expands an indented breakdown below the bar; clicking again collapses it; categories with a single supplier remain non-interactive and look unchanged
- **Sorted by amount** — suppliers within the expanded list are ordered by total descending so the largest contributor is always first

## Version 0.5.5 (2026-03-15)

Extended date parsing to handle non-ISO month tokens in extracted receipt dates
- **German month names** — `parse_date()` now recognises Oracle/SAP-style abbreviated tokens (`OKT`, `MRZ`, `DEZ`, `MAI`, `JUN`, `JUL` …) as well as full German names (`OKTOBER`, `DEZEMBER`, `MÄRZ`, `MAERZ` …) and converts them to their two-digit numeric equivalent before parsing; fixes `receipt_date: null` for invoices where the LLM reproduces the raw date string from the document (e.g. `30-OKT-2025` → `2025-10-30`)
- **English month names unaffected** — English abbreviated (`MAY`, `JUL`) and full (`July`, `May`) names continue to be handled by Python's native `strptime` via `%d-%b-%Y` / `%d-%B-%Y`; the German normalisation pass is only applied when those formats do not match, preventing any conflict
- **Whitespace tolerance** — date strings are stripped before all parsing attempts

## Version 0.5.4 (2026-03-14)

Frontend polish: icon category picker, sidebar sorting, and UX fixes
- **Custom category dropdown** — replaced the plain `<select>` in the preview panel with a fully custom dropdown; each option renders the category's Iconify icon alongside its translated label; the trigger button shows the active category icon and a rotating chevron; the list is scrollable and highlights the selected entry
- **Sidebar sorting** — receipts within each category group are now sorted first by counterparty name (the display name visible in the list — vendor, counterparty, or short hash) ascending alphabetically, then by receipt date descending so the most recent entry always appears first for the same counterparty (e.g. Adobe 2025-12 → Adobe 2025-11 → Haufe …)
- **Streaming messages** — upload progress steps shown during extraction are displayed more clearly in the sidebar upload button, reducing visual noise during long OCR/LLM runs
- **Footer link** — corrected the Read the Docs URL in the footer to point to the current documentation site

## Version 0.5.3 (2026-03-10)

Counterparty management overhaul — full inline editing in the UI, startup deduplication, and a new PATCH API endpoint
- **Counterparty Explorer rewritten** — card-style list now shows all fields (name, VAT ID, tax number, full address, verified badge, created date, ID) instead of the previous sparse 6-column table
- **Inline editing** — each entry has an Edit button that expands a two-column form covering all editable fields: name, tax number, VAT ID, verified flag, street & number, postcode, city, state, country; changes are applied in-place without a full reload
- **`PATCH /counterparties/{id}`** — new API endpoint accepting any subset of counterparty fields as a flat body or with a nested `address` sub-object; returns `{"ok": true}` on success, 404 if the ID is unknown
- **`update_counterparty()` storage method** — whitelist-validated `UPDATE` query added to `SQLiteRepository`; only the allowed fields are written, preventing accidental overwrites
- **Lookup-first deduplication in `get_or_create_counterparty`** — matches by VAT ID first, then by name when VAT ID is absent, before inserting; prevents duplicate rows on re-upload of the same receipt
- **Startup deduplication sweep** — `_deduplicate_counterparties()` runs at DB init and merges duplicate rows introduced by earlier versions, keeping the oldest row and re-pointing linked receipts
- **CORS regex** — replaced the static `allow_origins` list with `allow_origin_regex` matching any `localhost` or `127.0.0.1` port, fixing preflight failures on non-standard development ports

## Version 0.5.2 (2026-03-10)

Dependency cleanup and Python version cap
- **Version bounds added** — `paddleocr>=3.0.0`, `paddlepaddle>=3.0.0`, `pydantic>=2.0.0`, and `pydantic-settings>=2.0.0` now carry explicit minimum versions, preventing silent installation of incompatible older releases
- **Python 3.14 blocked** — `requires-python` is capped at `<3.14` because `paddlepaddle` ships no `cp314` wheels yet; users on Python ≥ 3.14 now get a clear resolver error instead of a runtime crash
- **UI dependencies promoted** — `fastapi`, `uvicorn[standard]`, and `python-multipart` moved from the optional `[ui]` extra into core dependencies so the web interface works out of the box with a plain `pip install finamt`


## Version 0.5.1 (2026-03-07)

Full codebase rename from `finanzamt` to `finamt`
- **Package imports updated** — all internal `from finanzamt import …` and `import finanzamt` references replaced with `finamt` throughout source, tests, and examples
- **CLI entry point renamed** — the console script is now `finamt` instead of `finanzamt`; old invocations must be updated after upgrading
- **Config and env-var prefix** — `FINANZAMT_` environment variable prefix changed to `FINAMT_` across all `BaseSettings` fields and documentation

## Version 0.5.0 (2026-03-07)

Name change to finamt
- PyPI release under new name
- Enable `pip install finamt`

## Version 0.4.6 (2026-03-06)

VAT split net amount support
- **`net_amount` field** — added `net_amount` column to `receipt_vat_splits` table; existing databases are migrated automatically on first run
- **Display** — each VAT split row now shows all three values: MwSt. € · MwSt. % · Netto € (tax amount, rate, net amount)
- **Editing** — split rows in edit mode have three equal-width labelled inputs in the same order: MwSt. €, MwSt. %, Netto €
- **Persistence** — `net_amount` is saved and restored correctly on update and re-load## Version 0.4.5 (2026-03-06)

## Version 0.4.5 (2026-03-06)

Switch OCR engine to PaddleOCR with Tesseract fallback
- **PaddleOCR** is the primary OCR engine; model is installed automatically via pip (`paddleocr`, `paddlepaddle`) and loaded once as a singleton
- **Tesseract fallback** — PaddleOCR runs inside a `ThreadPoolExecutor` with a configurable timeout (`FINAMT_OCR_TIMEOUT`, default 60 s); on timeout or any failure the process falls back to Tesseract, preventing OOM kills
- **German language model** — PaddleOCR uses `lang='german'`; Tesseract fallback uses `deu+eng`
- **`FINAMT_OCR_TIMEOUT`** — new config field (int, seconds, default 60) controlling how long to wait for PaddleOCR before switching to Tesseract
- **`FINAMT_TESSERACT_CMD`** — re-introduced so the Tesseract binary path can be customised when not on `PATH`
- **Temp-file approach** — page pixmaps are saved to a temp PNG and passed by path to PaddleOCR; file is deleted in `finally`
- **Event Streaming** – add event streaming to the terminal and the frontend

## Version 0.4.4 (2026-03-01)

Address schema refactor: unified street address and added state field
- **Schema consolidation** — merged `street` and `street_number` into a single `street_and_number` field for cleaner UI and extraction
- **State/province support** — added `state` field to address model for better international address handling (e.g. US states, German Bundesländer)
- **Database migration** — schema maintains backward compatibility; existing `street`/`street_number` data is automatically migrated to `street_and_number` on first run
- **Agent 2 prompt update** — extraction now expects `street_and_number` instead of separate fields; improved extraction rules documentation
- **Frontend address editor** — simplified from 2 address fields to 1; street number is now combined with street name
- **Localization updates** — locale keys updated: `field_street_and_number`, `field_state` added (EN: "Street", "State/Province"; DE: "Straße", "Bundesland")
- **Address display** — `formatAddress()` now correctly handles combined street and optional state in address formatting

## Version 0.4.3 (2026-03-01)

Packaging fix:
- Ensure the static folder (HTML, JS, CSS assets) is included in the PyPI package by adding MANIFEST.in and setting include-package-data = true in pyproject.toml. Now static assets are present after installation from PyPI.

## Version 0.4.2 (2026-03-01)

Improvements of the PreviewPanel and Dashboard
- Add support for previewing images (PNG, SVG, WebP, JPEG, JPG)
- Add go back button for the fullscreen preview
- Add to the dashboard a list of tax return statements that are coming soon

## Version 0.4.1 (2026-03-01)

Multi-project storage and full German UI translation
- **Multi-project storage** — receipts, PDFs, and debug output are now grouped under `~/.finamt/<project>/`; the default project lives at `~/.finamt/default/` (breaking change from the flat layout)
- **Project selector** — create, switch, and delete named projects directly from the header without restarting the server
- **German translation** — complete DE/EN localisation for Sidebar, PreviewPanel, Dashboard, and the project selector; language toggle in the header
- **Dashboard period label** — the subtitle now shows the currently selected time period (e.g. Q1 2025, März 2025) instead of a receipt count
- **Category and type translation** — receipt type (Ausgabe/Einnahme) and all category labels are now translated in the preview panel and category charts
- **DB creation guard** — the database file is created only on first upload, not on the initial page load; prevents stray files in the wrong directory

## Version 0.4.0 (2026-03-01)

Agentic workflow improvement
- **Four-agent pipeline** — metadata, counterparty, amounts, and line items are each extracted by a dedicated agent with a short focused prompt, improving reliability on local models
- **Debug output** — full prompt, raw model response, and parsed JSON are saved per agent to `~/.finamt/debug/<receipt_id>/` for inspection
- **Rule-based extraction removed** — all structured data now comes from the LLM pipeline

UI and database improvements
- **Period filter** — sidebar lets you filter receipts by year, quarter, or month; Dashboard reflects the active selection
- **Sidebar translation** — DE/EN locale support added to the sidebar
- **Counterparty verification** — mark a counterparty as verified in the preview panel and reuse it across receipts via the verified-counterparty picker
- **Address toggle** — full address details in the preview panel are collapsed by default and expanded on demand
- **VAT splitting** — receipts with multiple VAT rates can have each rate entered separately; splits are stored and displayed in the panel
- **Line item editing** — add, edit, and delete line items directly in the preview panel with per-item VAT rate and amount fields

## Version 0.3.2 (2026-02-25)

UI improvements for receipt management and database selection:
- Database selector: users can now choose a database, and all previously processed receipts are loaded automatically.
- Receipt browsing: receipts are grouped and displayed by year, quarter, and month for easier navigation.
- Revenue vs expense categorization: all receipts are classified and summarized per category, with totals shown for each.
- Editable records: editing receipts in the UI updates the corresponding records directly in the database.

## Version 0.3.1 (2026-02-24)

Added internationalisation infrastructure and German/English language toggle to the web UI header.
- DE/EN toggle: header now has a language switcher — amber track for German, red for English, black thumb; purely React-state-driven (no native input conflict)
- react-i18next: i18n infrastructure wired via `src/i18n.ts` with `de.json` and `en.json` locale files; components use `t("key")` and `i18n.changeLanguage()`
- Header localised: subtitle translates on toggle; install command stays hardcoded in English as `pip install finamt` — intentionally not translated
- Copy button: classic two-squares icon next to the install command copies it to clipboard; swaps to a green checkmark for 2s on success

## Version 0.3.0 (2026-02-24)

Full UI for receipt management:
	- Web interface for uploading and extracting receipts
	- Real-time extraction status and results display
	- Drag-and-drop PDF upload with batch support
	- Integrated static assets for responsive layout and branding
	- API endpoints for programmatic access and automation


## Version 0.2.0 (2026-02-23)

Persistent storage layer with content-addressed receipts, counterparty deduplication, and purchase/sale VAT split
- 4-table schema: `receipts`, `receipt_items`, `receipt_content`, `counterparties` — each concern in its own table
- Content-addressed IDs: receipt ID is a SHA-256 hash of OCR text; identical content = automatic duplicate detection with user notification
- Purchase vs sale split: `ReceiptType` distinguishes Eingangsrechnung (Vorsteuer you reclaim) from Ausgangsrechnung (Umsatzsteuer you remit); UStVA liability = output − input
- Counterparty model: replaces flat `vendor` string with structured `Counterparty` (parsed address, Steuernummer, USt-IdNr); deduplication by VAT ID then name
- Auto-save: every successful extraction persists to `~/.finamt/finamt.db` automatically; JSON output is now opt-in via `--output-dir`
- PDF archive: original PDF copied to `~/.finamt/pdfs/<hash>.pdf` for later display alongside extracted data
- Test suite updated: storage, UStVA, agent, CLI, and model tests rewritten for new API; all 250+ tests passing


## Version 0.1.5 (2026-02-22)

Add CLI and tests
- CLI refactor: Introduced a class-based CLI with commands for version reporting, single receipt processing, and batch processing. CLI logic is now testable in-process.
- CLI tests: Added in-process and subprocess tests for CLI functionality, improving coverage and reliability.

## Version 0.1.4 (2026-02-22)

Refactor config and models, unify prompt categories, fix OCR and utils, and update examples for consistent schema alignment
- Config refactor: Replaced scattered `os.getenv` calls with `pydantic-settings.BaseSettings`; all runtime settings are validated, typed, and overridable by `FINAMT_` env vars.  
- Unified model config: Promoted key model params (`temperature`, `top_p`, `num_ctx`) to validated fields; `get_model_config()` now returns a frozen `ModelConfig` dataclass.  
- Prompt separation: Moved extraction templates and category definitions (`RECEIPT_CATEGORIES`, `build_extraction_prompt`) to a new `prompts.py` for cleaner separation of config and prompt logic.  
- Schema alignment: Replaced outdated `ItemCategory` enum with `ReceiptCategory` validated against prompt categories; updated field names (`vendor`, `total_amount`, etc.) for full LLM schema alignment.  
- Validation and serialization: Added computed `net_amount`, VAT validation, and rounded `processing_time` in output.  
- Agent improvements: Fixed crashes from attribute misaccess; unified rule-based and LLM extraction paths; added robust retry and timing logic with structured logging.  
- OCR processor fixes: DPI scaling now respects config, closes PDFs safely on errors, and uses lowercase config fields consistently.  
- Utilities overhaul: Corrected date parsing and German amount handling; improved regex safety and amount extraction heuristics.  
- Exception clarity: Custom exception base now auto-appends cause info, producing cleaner tracebacks.  
- Examples updated: Scripts now use new field names, category logic, output options, and proper exit codes for batch and single receipt processing.  

## Version 0.1.3 (2026-02-21)

Major refactor: package renamed and structure updated
- Renamed package from `ai-finance-agent` to `finanzamt`.
- Updated project structure to `src/finanzamt` for imports and packaging.

## Version 0.1.2 (2025-07-10)

Minor improvements and bug fixes
- Improved extraction logic.
- Fixed minor bugs.

## Version 0.1.1 (2025-07-10)

Initial package upload
- Uploaded ai-finance-agent to PyPI.
- Added basic documentation.

## Version 0.1.0 (2025-07-10)

First release: basic receipt processing
- Implemented receipt parsing and extraction.
- Provided initial agent interface.
