"""
tests/test_llm_caller.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.agents.llm_caller — call_llm and _regex_fallback.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from finamt.agents.config import AgentModelConfig
from finamt.agents.llm_caller import _regex_fallback, call_llm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**kwargs) -> AgentModelConfig:
    defaults = {
        "model": "mistral:7b",
        "temperature": 0.0,
        "top_p": 1.0,
        "num_ctx": 512,
        "timeout": 5,
        "max_retries": 2,
    }
    defaults.update(kwargs)
    return AgentModelConfig(**defaults)


def _backend_resp(data: dict) -> str:
    """Return a JSON string as the backend would generate."""
    return json.dumps(data)


# ---------------------------------------------------------------------------
# _regex_fallback
# ---------------------------------------------------------------------------


class TestRegexFallback:
    def test_extracts_string_value(self):
        raw = '{"name": "Acme GmbH", "other": "x"}'
        result = _regex_fallback(raw, ["name"])
        assert result.get("name") == "Acme GmbH"

    def test_extracts_numeric_value(self):
        raw = '{"amount": 119.99}'
        result = _regex_fallback(raw, ["amount"])
        assert result.get("amount") == 119.99

    def test_extracts_null_value(self):
        raw = '{"date": null}'
        result = _regex_fallback(raw, ["date"])
        assert result.get("date") is None

    def test_extracts_boolean(self):
        raw = '{"verified": true}'
        result = _regex_fallback(raw, ["verified"])
        assert result.get("verified") is True

    def test_missing_key_not_in_result(self):
        raw = '{"name": "Test"}'
        result = _regex_fallback(raw, ["name", "missing"])
        assert "missing" not in result

    def test_empty_raw(self):
        result = _regex_fallback("", ["key"])
        assert result == {}


# ---------------------------------------------------------------------------
# call_llm — success paths
# ---------------------------------------------------------------------------


class TestCallLlm:
    def test_success_returns_dict(self):
        with patch("finamt.agents.llm_backend.generate") as mock_gen:
            mock_gen.return_value = _backend_resp({"key": "value"})
            result = call_llm("prompt", _cfg(), "agent1", ["key"])
        assert result == {"key": "value"}

    def test_debug_files_written(self, tmp_path):
        with patch("finamt.agents.llm_backend.generate") as mock_gen:
            mock_gen.return_value = _backend_resp({"k": "v"})
            call_llm("test prompt", _cfg(), "agent1", ["k"], debug_dir=tmp_path)
        assert (tmp_path / "agent1_prompt.txt").read_text() == "test prompt"
        assert (tmp_path / "agent1_raw.txt").exists()
        assert (tmp_path / "agent1_parsed.json").exists()

    def test_backend_exception_returns_none(self):
        with patch("finamt.agents.llm_backend.generate") as mock_gen:
            mock_gen.side_effect = RuntimeError("model error")
            result = call_llm("prompt", _cfg(max_retries=2), "agent1", ["k"])
        assert result is None

    def test_empty_response_returns_none(self):
        with patch("finamt.agents.llm_backend.generate", return_value=""):
            result = call_llm("prompt", _cfg(), "agent1", ["k"])
        assert result is None

    def test_malformed_json_uses_regex_fallback(self):
        """If the model returns broken JSON, regex fallback must recover key fields."""
        raw = 'Sure here you go: {"total_amount": "119.00" and some garbage'
        with patch("finamt.agents.llm_backend.generate", return_value=raw):
            result = call_llm("prompt", _cfg(), "agent1", ["total_amount"])
        assert result is not None
        assert result.get("total_amount") == "119.00"

    def test_unparsable_response_writes_error_debug(self, tmp_path):
        """Completely unparsable → debug file records parse_failed."""
        with patch(
            "finamt.agents.llm_backend.generate", return_value="no json here whatsoever !!!"
        ):
            call_llm("p", _cfg(), "agent1", ["key"], debug_dir=tmp_path)
        content = (tmp_path / "agent1_parsed.json").read_text()
        assert "_error" in content

    def test_debug_files_written_on_failure(self, tmp_path):
        """When backend raises, raw debug file mentions FAILED."""
        with patch("finamt.agents.llm_backend.generate", side_effect=RuntimeError("fail")):
            call_llm("p", _cfg(max_retries=1), "a1", ["k"], debug_dir=tmp_path)
        raw_content = (tmp_path / "a1_raw.txt").read_text()
        assert "FAILED" in raw_content
