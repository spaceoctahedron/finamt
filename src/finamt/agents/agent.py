"""
finamt.agents.agent
~~~~~~~~~~~~~~~
Main entry point for receipt processing.

Pipeline (see agents/pipeline.py for details):
  1. OCR text extraction (PaddleOCR)
  2. Duplicate detection (SHA-256 content hash)
  3. Agent 1 — receipt number, date, category
  4. Agent 2 — counterparty (vendor or client)
  5. Agent 3 — amounts (total, VAT %, VAT amount)
  6. Agent 4 — line items
  7. Python merge of the 4 results → ReceiptData
  8. Validate + auto-save to SQLite

All 4 agents use the same local LLM (configured via FINAMT_AGENT_MODEL).
They run sequentially — not in parallel — for local model compatibility.
Debug output is saved to ~/.finamt/debug/<receipt_id>/.
"""

from __future__ import annotations

import logging
import shutil
import time
from decimal import Decimal
from pathlib import Path

from finamt import progress as _progress

from ..exceptions import InvalidReceiptError, OCRProcessingError
from ..models import ExtractionResult, ReceiptCategory, ReceiptData, _content_hash
from ..ocr_processor import OCRProcessor
from ..storage.project import ProjectLayout, layout_from_db_path, resolve_project
from ..storage.sqlite import SQLiteRepository
from .config import AgentsConfig, Config
from .pipeline import implied_vat_rate, run_pipeline

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_UNSET = object()  # sentinel: distinguish "not passed" from None

# A supplier needs at least this many classified receipts in the DB before its
# historical category/subcategory overrides the AI suggestion.
_SUPPLIER_HISTORY_MIN_RECEIPTS = 2


class FinanceAgent:
    """
    Orchestrates OCR + multi-agent extraction and auto-persists every result.

    Args:
        config:      Optional Config instance (reads .env by default).
        project:     Project name — determines ~/.finamt/<project>/ layout.
                     Default: "default" (or FINAMT_PROJECT env var).
        db_path:     Explicit SQLite path — overrides project layout.
                     Pass None to disable persistence entirely.
        agents_cfg:  Optional AgentsConfig — controls which models are used.
    """

    def __init__(
        self,
        config: Config | None = None,
        project: str | None = None,
        db_path: str | Path | None = _UNSET,
        agents_cfg: AgentsConfig | None = None,
    ) -> None:
        self.config = config or Config()
        self.agents_cfg = agents_cfg or AgentsConfig()
        self.ocr = OCRProcessor(self.config)

        # Resolve project layout
        if db_path is not _UNSET and db_path is not None:
            # Explicit path takes precedence — infer layout from it
            self._layout: ProjectLayout | None = layout_from_db_path(Path(db_path))
            self._db_path: Path | None = Path(db_path)
        elif db_path is None:
            # Explicitly disabled — no persistence
            self._layout = resolve_project(project) if project else None
            self._db_path = None
        else:
            # Normal case — derive everything from project name
            self._layout = resolve_project(project)
            self._db_path = self._layout.db_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_receipt(
        self,
        pdf_path: str | Path | bytes,
        receipt_type: str = "purchase",
        taxpayer_info: dict | None = None,
    ) -> ExtractionResult:
        """
        Process a receipt or invoice PDF through the full pipeline.

        Args:
            pdf_path:      Filesystem path or raw PDF bytes.
            receipt_type:  "purchase" (default) or "sale".
            taxpayer_info: Optional dict with taxpayer's own data so Agent 2
                           does not confuse the taxpayer with the counterparty.
                           Keys: name, vat_id, tax_number, address.

        Returns ExtractionResult — always populated, success flag indicates
        whether the result passed validation and was saved.
        """
        start = time.monotonic()

        try:
            # 1 — OCR -------------------------------------------------------
            name = Path(pdf_path).name if isinstance(pdf_path, (str, Path)) else "<bytes>"
            _progress.emit(f"[finamt] {name}")
            _progress.emit(f"  {time.strftime('[%H:%M:%S]')} → PyMuPDF ...")
            raw_text = self.ocr.extract_text_from_pdf(pdf_path)
            if not raw_text.strip():
                return ExtractionResult(
                    success=False,
                    error_message="No text could be extracted from the PDF.",
                    processing_time=time.monotonic() - start,
                )

            # 2 — Duplicate check -------------------------------------------
            content_id = _content_hash(raw_text)
            if self._db_path:
                with SQLiteRepository(self._db_path) as repo:
                    if repo.exists(content_id):
                        existing = repo.get(content_id)
                        logger.info("Duplicate detected: %s", content_id)
                        return ExtractionResult(
                            success=True,
                            data=existing,
                            duplicate=True,
                            existing_id=content_id,
                            processing_time=time.monotonic() - start,
                        )

            # 3-7 — Multi-agent extraction ----------------------------------
            _progress.emit(f"  {time.strftime('[%H:%M:%S]')} → Extraction pipeline ...")
            pdf_file_path: Path | None = (
                Path(pdf_path) if isinstance(pdf_path, (str, Path)) else None
            )
            receipt_data: ReceiptData = run_pipeline(
                raw_text=raw_text,
                pdf_path=pdf_file_path,
                receipt_type=receipt_type,
                cfg=self.agents_cfg,
                receipt_id=content_id,
                debug_root=self._layout.debug_dir if self._layout else None,
                taxpayer_info=taxpayer_info,
            )

            # 8 — Validate (collects warnings; never blocks) -----------------
            receipt_data.validate()  # populates receipt_data.validation_warnings
            # Receipts with warnings are saved and shown with a warning banner
            # in the UI — the user decides to correct or delete them.

            # 9 — Known-supplier override + Save + PDF copy ------------------
            if self._db_path:
                with SQLiteRepository(self._db_path) as repo:
                    self._apply_supplier_history(repo, receipt_data)
                    repo.save(receipt_data)
                if pdf_file_path:
                    self._store_pdf(pdf_file_path, receipt_data.id)

            return ExtractionResult(
                success=True,
                data=receipt_data,
                processing_time=time.monotonic() - start,
            )

        except (OCRProcessingError, InvalidReceiptError) as exc:
            logger.error("%s: %s", type(exc).__name__, exc)
            return ExtractionResult(
                success=False,
                error_message=str(exc),
                processing_time=time.monotonic() - start,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error processing receipt.")
            return ExtractionResult(
                success=False,
                error_message=f"Unexpected error: {exc}",
                processing_time=time.monotonic() - start,
            )

    def batch_process(
        self,
        pdf_paths: list[str | Path],
        receipt_type: str = "purchase",
    ) -> dict[str, ExtractionResult]:
        """Process multiple receipts sequentially."""
        return {str(p): self.process_receipt(p, receipt_type=receipt_type) for p in pdf_paths}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_supplier_history(repo: SQLiteRepository, receipt: ReceiptData) -> None:
        """Override AI category/subcategory and VAT rate for well-known suppliers.

        When the supplier already has at least ``_SUPPLIER_HISTORY_MIN_RECEIPTS``
        receipts in the DB, the dominant historical values replace the AI
        suggestion.
        """
        name = receipt.counterparty.name if receipt.counterparty else None
        rtype = str(receipt.receipt_type)

        defaults = repo.get_known_supplier_defaults(
            name, receipt_type=rtype, min_receipts=_SUPPLIER_HISTORY_MIN_RECEIPTS
        )
        if defaults:
            logger.info(
                "Known supplier %r (%d receipts): category %s/%s -> %s/%s",
                name,
                defaults["count"],
                receipt.category,
                receipt.subcategory,
                defaults["category"],
                defaults["subcategory"],
            )
            receipt.category = ReceiptCategory(defaults["category"])
            receipt.subcategory = defaults["subcategory"] or None

        known_vat = repo.get_known_supplier_vat(
            name, receipt_type=rtype, min_receipts=_SUPPLIER_HISTORY_MIN_RECEIPTS
        )
        if known_vat:
            FinanceAgent._apply_known_vat(receipt, known_vat["vat_percentage"], name)

    @staticmethod
    def _apply_known_vat(receipt: ReceiptData, rate: Decimal, name: str | None) -> None:
        """Replace the receipt's VAT rate with the supplier's usual one, unless the
        document's own amounts already confirm the extracted rate."""
        current = receipt.vat_percentage
        if current is not None and current == rate:
            return
        # A VAT amount > 0 that matches the extracted rate is hard evidence from
        # the document itself - keep it (e.g. a one-off 19 % invoice).
        if current is not None and receipt.total_amount and receipt.vat_amount:
            implied = implied_vat_rate(float(receipt.total_amount), float(receipt.vat_amount))
            if implied is not None and implied > 0 and implied == float(current):
                return
        logger.info("Known supplier %r: VAT rate %s -> %s", name, current, rate)
        receipt.vat_percentage = rate
        if receipt.total_amount is not None:
            net = receipt.total_amount / (Decimal("1") + rate / Decimal("100"))
            receipt.vat_amount = (receipt.total_amount - net).quantize(Decimal("0.01"))

    def _store_pdf(self, src: Path, receipt_id: str) -> None:
        """Copy the original file to <project>/pdfs/<id>.<ext>, preserving the source extension."""
        if not src.exists():
            return
        try:
            pdf_dir = self._layout.pdfs_dir if self._layout else self._db_path.parent / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            # Preserve original extension so images stay as .png / .jpg etc.
            ext = src.suffix.lower() or ".pdf"
            dest = pdf_dir / f"{receipt_id}{ext}"
            if not dest.exists():
                shutil.copy2(src, dest)
                logger.info("File stored: %s", dest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not store file copy: %s", exc)
