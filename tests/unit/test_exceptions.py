"""
tests/test_exceptions.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.exceptions — hierarchy, cause chaining, str representation.
"""

from __future__ import annotations

import pytest

from finamt.exceptions import (
    FinanceAgentError,
    InvalidReceiptError,
    LLMExtractionError,
    OCRProcessingError,
)


class TestHierarchy:
    def test_ocr_is_finance_agent_error(self):
        assert issubclass(OCRProcessingError, FinanceAgentError)

    def test_llm_is_finance_agent_error(self):
        assert issubclass(LLMExtractionError, FinanceAgentError)

    def test_invalid_receipt_is_finance_agent_error(self):
        assert issubclass(InvalidReceiptError, FinanceAgentError)

    def test_all_inherit_from_exception(self):
        for cls in (FinanceAgentError, OCRProcessingError, LLMExtractionError, InvalidReceiptError):
            assert issubclass(cls, Exception)


class TestConstruction:
    def test_message_stored(self):
        exc = OCRProcessingError("something went wrong")
        assert exc.message == "something went wrong"
        assert str(exc) == "something went wrong"

    def test_cause_is_none_by_default(self):
        exc = FinanceAgentError("msg")
        assert exc.cause is None

    def test_cause_stored(self):
        original = ValueError("root cause")
        exc = LLMExtractionError("wrapper", cause=original)
        assert exc.cause is original

    def test_str_with_cause(self):
        original = OSError("disk full")
        exc = OCRProcessingError("failed to read PDF", cause=original)
        text = str(exc)
        assert "failed to read PDF" in text
        # In Python 3 IOError is an alias for OSError
        assert any(name in text for name in ("OSError", "IOError"))
        assert "disk full" in text

    def test_str_without_cause(self):
        exc = InvalidReceiptError("bad data")
        assert str(exc) == "bad data"


class TestRaising:
    def test_can_catch_by_base(self):
        with pytest.raises(FinanceAgentError):
            raise OCRProcessingError("oops")

    def test_can_catch_by_specific_type(self):
        with pytest.raises(LLMExtractionError):
            raise LLMExtractionError("timeout")

    def test_cause_available_in_except_block(self):
        root = RuntimeError("root")
        try:
            raise OCRProcessingError("outer", cause=root)
        except FinanceAgentError as exc:
            assert exc.cause is root
