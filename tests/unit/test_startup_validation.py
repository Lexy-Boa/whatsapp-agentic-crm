from __future__ import annotations

import types

from src.config import Environment
from src.main import _missing_required_settings


def _settings(**overrides):
    base = dict(
        environment=Environment.dev,
        anthropic_api_key="anthropic",
        whatsapp_access_token="whatsapp",
        store_id="store",
        openai_api_key="openai",
        whatsapp_app_secret="",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_dev_startup_does_not_require_whatsapp_app_secret():
    missing = _missing_required_settings(_settings(environment=Environment.dev))

    assert "whatsapp_app_secret" not in missing


def test_prod_startup_requires_whatsapp_app_secret():
    missing = _missing_required_settings(_settings(environment=Environment.prod))

    assert "whatsapp_app_secret" in missing


def test_prod_startup_accepts_whatsapp_app_secret_when_present():
    missing = _missing_required_settings(
        _settings(environment=Environment.prod, whatsapp_app_secret="secret")
    )

    assert "whatsapp_app_secret" not in missing
