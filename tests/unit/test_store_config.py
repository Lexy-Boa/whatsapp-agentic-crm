from __future__ import annotations

from pathlib import Path

from src.services.ai.store_config import DEFAULT_STORE_CONFIG, load_store_config

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_default_store_config_loads_business_profile():
    assert DEFAULT_STORE_CONFIG["brand_name"] == "DemoBoutique"
    assert "service_policies" in DEFAULT_STORE_CONFIG
    assert "refund request" in DEFAULT_STORE_CONFIG["escalation_rules"]
    assert "assistant_unavailable" in DEFAULT_STORE_CONFIG["fallback_messages"]


def test_load_store_config_uses_safe_fallback_for_missing_file():
    config = load_store_config(FIXTURES_DIR / "missing.json")

    assert config["brand_name"] == "DemoBoutique"
    assert config["unknown_policy_response"].startswith("I will check this")


def test_load_store_config_merges_owner_reviewable_json():
    config = load_store_config(FIXTURES_DIR / "store_profile_override.json")

    assert config["brand_name"] == "Demo Store"
    assert config["service_policies"]["payments"] == ["Do not promise COD."]
    assert config["response_settings"]["max_response_length"] == 500
