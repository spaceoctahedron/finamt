"""
tests/test_config.py
~~~~~~~~~~~~~~~~~~~~
Tests for finamt.agents.config — Config, AgentsConfig, ModelConfig,
AgentModelConfig dataclasses, and backward-compatible aliases.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from finamt.agents.config import AgentModelConfig, AgentsConfig, Config, ModelConfig, cfg


class TestConfigDefaults:
    def test_model_default(self):
        assert Config(_env_file=None).model == "mistral:7b"  # type: ignore[call-arg]

    def test_ocr_language_default(self):
        assert Config(_env_file=None).ocr_language == "german"  # type: ignore[call-arg]

    def test_ocr_timeout_default(self):
        assert Config(_env_file=None).ocr_timeout == 60  # type: ignore[call-arg]

    def test_ocr_preprocess_default(self):
        assert Config(_env_file=None).ocr_preprocess is True  # type: ignore[call-arg]

    def test_pdf_dpi_default(self):
        assert Config(_env_file=None).pdf_dpi == 150  # type: ignore[call-arg]

    def test_max_retries_default(self):
        assert Config(_env_file=None).max_retries == 3  # type: ignore[call-arg]

    def test_request_timeout_default(self):
        assert Config(_env_file=None).request_timeout == 30  # type: ignore[call-arg]

    def test_temperature_default(self):
        assert Config(_env_file=None).temperature == 0.1  # type: ignore[call-arg]


class TestConfigValidation:
    def test_pdf_dpi_minimum(self):
        with pytest.raises(ValidationError):
            Config(pdf_dpi=10)

    def test_pdf_dpi_maximum(self):
        with pytest.raises(ValidationError):
            Config(pdf_dpi=9999)

    def test_max_retries_negative(self):
        with pytest.raises(ValidationError):
            Config(max_retries=-1)

    def test_max_retries_too_high(self):
        with pytest.raises(ValidationError):
            Config(max_retries=100)

    def test_temperature_out_of_range(self):
        with pytest.raises(ValidationError):
            Config(temperature=3.0)

    def test_top_p_out_of_range(self):
        with pytest.raises(ValidationError):
            Config(top_p=1.5)

    def test_ocr_language_empty_string(self):
        with pytest.raises(ValidationError):
            Config(ocr_language="")

    def test_ocr_language_normalised(self):
        c = Config(ocr_language=" deu + eng ")
        assert c.ocr_language == "deu+eng"

    def test_high_temperature_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Config(temperature=0.9)
            assert any(issubclass(x.category, UserWarning) for x in w)

    def test_low_temperature_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Config(temperature=0.1)
            assert not any(issubclass(x.category, UserWarning) for x in w)


class TestConfigEnvVarOverride:
    def test_env_var_overrides_model(self):
        with patch.dict(os.environ, {"FINAMT_MODEL": "mistral"}):
            assert Config().model == "mistral"

    def test_env_var_overrides_pdf_dpi(self):
        with patch.dict(os.environ, {"FINAMT_PDF_DPI": "150"}):
            assert Config().pdf_dpi == 150

    def test_env_var_overrides_ocr_preprocess(self):
        with patch.dict(os.environ, {"FINAMT_OCR_PREPROCESS": "false"}):
            assert Config().ocr_preprocess is False


class TestModelConfig:
    def test_returns_model_config_dataclass(self):
        assert isinstance(Config().get_model_config(), ModelConfig)

    def test_model_config_fields(self):
        mc = Config(model="phi3", max_retries=5, request_timeout=60).get_model_config()
        assert mc.model == "phi3"
        assert mc.max_retries == 5
        assert mc.timeout == 60

    def test_model_config_is_frozen(self):
        mc = Config().get_model_config()
        with pytest.raises(FrozenInstanceError):
            mc.model = "changed"  # type: ignore[misc]


class TestAgentsConfig:
    def test_single_model_used_for_all_agents(self):
        cfg = AgentsConfig(agent_model="mistral")
        ac = cfg.get_agent_config()
        assert ac.model == "mistral"

    def test_temperature_is_zero(self):
        assert AgentsConfig(_env_file=None).get_agent_config().temperature == 0.0  # type: ignore[call-arg]

    def test_returns_agent_model_config_dataclass(self):
        assert isinstance(AgentsConfig().get_agent_config(), AgentModelConfig)

    def test_env_var_overrides_agent_model(self):
        with patch.dict(os.environ, {"FINAMT_AGENT_MODEL": "llama3.1"}):
            assert AgentsConfig().agent_model == "llama3.1"

    def test_agent_model_config_is_frozen(self):
        ac = AgentsConfig().get_agent_config()
        with pytest.raises(FrozenInstanceError):
            ac.model = "changed"  # type: ignore[misc]


class TestSingleton:
    def test_cfg_is_config_instance(self):
        assert isinstance(cfg, Config)
