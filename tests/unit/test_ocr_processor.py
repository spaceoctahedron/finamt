"""
tests/test_ocr_processor.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.ocr_processor — OCRProcessor with PyMuPDF, PaddleOCR,
and Tesseract mocked so tests run without any system dependencies.
"""

from __future__ import annotations

from concurrent.futures import TimeoutError as FuturesTimeout
from unittest.mock import MagicMock, patch

import pytest

from finamt.agents.config import Config
from finamt.exceptions import OCRProcessingError
from finamt.ocr_processor import OCRProcessor, _extract_texts_from_paddle_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pixmap() -> MagicMock:
    """Build a fake fitz.Pixmap."""
    pix = MagicMock()
    pix.save = MagicMock()
    return pix


def _make_mock_page(direct_text: str = "") -> MagicMock:
    """Build a fake fitz.Page."""
    page = MagicMock()
    page.get_text.return_value = direct_text
    page.get_pixmap.return_value = _make_mock_pixmap()
    return page


def _make_mock_pdf(pages: list[MagicMock]) -> MagicMock:
    """Build a fake fitz.Document."""
    doc = MagicMock()
    doc.page_count = len(pages)
    doc.__getitem__ = lambda self, i: pages[i]
    return doc


def _make_paddle_ocr(texts: list[str] | None = None) -> MagicMock:
    """Return a mock PaddleOCR whose predict() yields the given texts."""
    ocr = MagicMock()
    ocr.predict.return_value = [{"rec_texts": texts or []}]
    return ocr


def _patch_tmp(mock_tmp):
    """Configure a NamedTemporaryFile mock to return a usable context manager."""
    mock_tmp.return_value.__enter__.return_value.name = "/tmp/fake_page.png"


# ---------------------------------------------------------------------------
# Tesseract configuration
# ---------------------------------------------------------------------------


class TestConfigureTesseract:
    def test_default_cmd_does_not_call_pytesseract(self):
        """With default path, pytesseract.tesseract_cmd must not be overwritten."""
        with patch("finamt.ocr_processor.Image"):  # stop real PIL import
            OCRProcessor(Config(tesseract_cmd="tesseract"))
        # No assertion needed — just must not raise

    def test_custom_cmd_sets_pytesseract_path(self):
        custom_path = "/usr/local/bin/tesseract"
        mock_pt = MagicMock()
        mock_pt.pytesseract = MagicMock()
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            OCRProcessor(Config(tesseract_cmd=custom_path))
            assert mock_pt.pytesseract.tesseract_cmd == custom_path


# ---------------------------------------------------------------------------
# extract_text_from_pdf — direct text layer
# ---------------------------------------------------------------------------


class TestExtractDirectText:
    def test_returns_direct_text_when_available(self):
        page = _make_mock_page(direct_text="Invoice text here")
        doc = _make_mock_pdf([page])

        with patch("finamt.ocr_processor.fitz.open", return_value=doc):
            result = OCRProcessor().extract_text_from_pdf("receipt.pdf")

        assert "Invoice text here" in result

    def test_direct_text_skips_ocr(self):
        page = _make_mock_page(direct_text="Direct text")
        doc = _make_mock_pdf([page])
        mock_ocr = _make_paddle_ocr()

        with (
            patch("finamt.ocr_processor.fitz.open", return_value=doc),
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(mock_ocr, None)),
        ):
            OCRProcessor().extract_text_from_pdf("receipt.pdf")

        mock_ocr.predict.assert_not_called()

    def test_multiple_pages_concatenated(self):
        pages = [
            _make_mock_page(direct_text="Page one"),
            _make_mock_page(direct_text="Page two"),
        ]
        doc = _make_mock_pdf(pages)

        with patch("finamt.ocr_processor.fitz.open", return_value=doc):
            result = OCRProcessor().extract_text_from_pdf("receipt.pdf")

        assert "Page one" in result
        assert "Page two" in result

    def test_pdf_closed_after_success(self):
        page = _make_mock_page(direct_text="text")
        doc = _make_mock_pdf([page])

        with patch("finamt.ocr_processor.fitz.open", return_value=doc):
            OCRProcessor().extract_text_from_pdf("receipt.pdf")

        doc.close.assert_called_once()


# ---------------------------------------------------------------------------
# extract_text_from_pdf — OCR path (PaddleOCR primary)
# ---------------------------------------------------------------------------


class TestExtractOcrPath:
    def test_ocr_called_when_no_direct_text(self):
        page = _make_mock_page(direct_text="")
        doc = _make_mock_pdf([page])
        mock_ocr = _make_paddle_ocr(["OCR extracted text"])

        with (
            patch("finamt.ocr_processor.fitz.open", return_value=doc),
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(mock_ocr, None)),
            patch("finamt.ocr_processor.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("finamt.ocr_processor.os.unlink"),
        ):
            _patch_tmp(mock_tmp)
            result = OCRProcessor().extract_text_from_pdf("scanned.pdf")

        mock_ocr.predict.assert_called_once()
        assert "OCR extracted text" in result

    def test_dpi_respected_in_matrix(self):
        """Regression: was hardcoded fitz.Matrix(2,2) = 144 DPI, ignoring config."""
        page = _make_mock_page(direct_text="")
        doc = _make_mock_pdf([page])
        config = Config(pdf_dpi=300)
        expected_scale = 300 / 72.0
        mock_ocr = _make_paddle_ocr()

        with (
            patch("finamt.ocr_processor.fitz.open", return_value=doc),
            patch("finamt.ocr_processor.fitz.Matrix") as mock_matrix,
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(mock_ocr, None)),
            patch("finamt.ocr_processor.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("finamt.ocr_processor.os.unlink"),
        ):
            mock_matrix.return_value = MagicMock()
            _patch_tmp(mock_tmp)
            OCRProcessor(config).extract_text_from_pdf("scanned.pdf")

        mock_matrix.assert_called_with(expected_scale, expected_scale)

    def test_pdf_closed_after_ocr_error(self):
        """File handle must be released even when OCR raises."""
        page = _make_mock_page(direct_text="")
        doc = _make_mock_pdf([page])
        mock_ocr = MagicMock()
        mock_ocr.predict.side_effect = RuntimeError("paddle crash")

        with (
            patch("finamt.ocr_processor.fitz.open", return_value=doc),
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(mock_ocr, None)),
            patch("finamt.ocr_processor.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("finamt.ocr_processor.os.unlink"),
            patch.object(OCRProcessor, "_tesseract_ocr", return_value=""),
        ):
            _patch_tmp(mock_tmp)
            OCRProcessor().extract_text_from_pdf("scanned.pdf")

        doc.close.assert_called_once()


# ---------------------------------------------------------------------------
# Timeout + fallback
# ---------------------------------------------------------------------------


class TestPaddleFallback:
    def _proc(self, timeout: int = 5) -> OCRProcessor:
        return OCRProcessor(Config(ocr_timeout=timeout))

    def test_paddle_timeout_falls_back_to_tesseract(self):
        """TimeoutError from the executor triggers Tesseract fallback."""
        mock_ocr = MagicMock()
        proc = self._proc(timeout=5)

        with (
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(mock_ocr, None)),
            patch("finamt.ocr_processor.ThreadPoolExecutor") as mock_pool,
            patch.object(proc, "_tesseract_ocr", return_value="tess text") as mock_tess,
        ):
            mock_future = MagicMock()
            mock_future.result.side_effect = FuturesTimeout()
            mock_pool.return_value.__enter__.return_value.submit.return_value = mock_future

            result = proc._paddle_with_fallback("/tmp/img.png")

        mock_tess.assert_called_once_with("/tmp/img.png")
        assert result == "tess text"

    def test_paddle_exception_falls_back_to_tesseract(self):
        """Any exception from PaddleOCR triggers Tesseract fallback."""
        mock_ocr = MagicMock()
        proc = self._proc()

        with (
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(mock_ocr, None)),
            patch("finamt.ocr_processor.ThreadPoolExecutor") as mock_pool,
            patch.object(proc, "_tesseract_ocr", return_value="tess text") as mock_tess,
        ):
            mock_future = MagicMock()
            mock_future.result.side_effect = MemoryError("OOM")
            mock_pool.return_value.__enter__.return_value.submit.return_value = mock_future

            result = proc._paddle_with_fallback("/tmp/img.png")

        mock_tess.assert_called_once()
        assert result == "tess text"

    def test_paddle_unavailable_falls_back_to_tesseract(self):
        """When PaddleOCR never initialised, Tesseract is used directly."""
        proc = self._proc()

        with (
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(None, "import failed")),
            patch.object(proc, "_tesseract_ocr", return_value="tess text") as mock_tess,
        ):
            result = proc._paddle_with_fallback("/tmp/img.png")

        mock_tess.assert_called_once_with("/tmp/img.png")
        assert result == "tess text"

    def test_paddle_empty_result_falls_back_to_tesseract(self):
        """Empty PaddleOCR output falls through to Tesseract."""
        mock_ocr = _make_paddle_ocr(texts=[])  # empty
        proc = self._proc()

        with (
            patch("finamt.ocr_processor._get_paddle_ocr", return_value=(mock_ocr, None)),
            patch.object(proc, "_tesseract_ocr", return_value="tess text") as mock_tess,
        ):
            result = proc._paddle_with_fallback("/tmp/img.png")

        mock_tess.assert_called_once()
        assert result == "tess text"

    def test_tesseract_ocr_missing_pytesseract_returns_empty(self):
        """If pytesseract is not installed, _tesseract_ocr returns ''."""
        proc = self._proc()
        with patch.dict("sys.modules", {"pytesseract": None}):
            result = proc._tesseract_ocr("/tmp/img.png")
        assert result == ""


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_raises_ocr_error_on_bad_pdf(self):
        with patch("finamt.ocr_processor.fitz.open", side_effect=RuntimeError("corrupt")):
            with pytest.raises(OCRProcessingError):
                OCRProcessor().extract_text_from_pdf("bad.pdf")

    def test_accepts_bytes_input(self):
        page = _make_mock_page(direct_text="bytes text")
        doc = _make_mock_pdf([page])

        with patch("finamt.ocr_processor.fitz.open", return_value=doc) as mock_open:
            OCRProcessor().extract_text_from_pdf(b"%PDF-1.4 bytes content")
            call_kwargs = mock_open.call_args[1]
            assert "stream" in call_kwargs

    def test_returns_stripped_text(self):
        page = _make_mock_page(direct_text="  lots of whitespace  \n\n")
        doc = _make_mock_pdf([page])

        with patch("finamt.ocr_processor.fitz.open", return_value=doc):
            result = OCRProcessor().extract_text_from_pdf("receipt.pdf")

        assert result == result.strip()


# ---------------------------------------------------------------------------
# _extract_texts_from_paddle_result (unit)
# ---------------------------------------------------------------------------


class TestExtractTexts:
    def test_extracts_from_dict_result(self):
        result = [{"rec_texts": ["line one", "line two", ""]}]
        assert _extract_texts_from_paddle_result(result) == ["line one", "line two"]

    def test_extracts_from_attribute_result(self):
        page = MagicMock(spec=["rec_texts"])
        page.rec_texts = ["attr line"]
        assert _extract_texts_from_paddle_result([page]) == ["attr line"]

    def test_empty_result_returns_empty_list(self):
        assert _extract_texts_from_paddle_result([{"rec_texts": []}]) == []
        assert _extract_texts_from_paddle_result([]) == []
