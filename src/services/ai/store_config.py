"""
Store configuration loading for the store assistant.

Phase 1 is single-tenant per deployment, so this module keeps the default
DemoBoutique profile local and owner-reviewable instead of adding admin UI or
database-backed template management too early.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BUSINESS_PROFILE_PATH = (
    PROJECT_ROOT / "data" / "demo" / "demoboutique_business_profile.json"
)

_FALLBACK_STORE_CONFIG: dict[str, Any] = {
    "brand_name": "DemoBoutique",
    "brand_voice": "friendly and helpful",
    "languages": ["ml", "ta", "en"],
    "primary_language": "ml",
    "business_profile": {
        "description": "South Indian fashion retail assistant.",
        "demo_truth": "Detailed business policy has not been loaded.",
    },
    "service_policies": {},
    "unknown_policy_response": (
        "I will check this with the DemoBoutique team and get back to you "
        "with the correct details."
    ),
    "escalation_rules": [
        "refund request",
        "return or exchange request",
        "damaged product",
        "payment issue",
        "customer explicitly asks for a person",
    ],
    "fallback_messages": {
        "assistant_unavailable": {
            "en": (
                "Sorry, our assistant is temporarily unavailable. The DemoBoutique "
                "team will follow up shortly."
            )
        }
    },
    "response_settings": {
        "voice_to_voice": True,
        "emoji_style": "minimal_gen_z",
        "max_response_length": 500,
    },
}


def load_store_config(profile_path: Path | str | None = None) -> dict[str, Any]:
    """Load the local store profile, falling back to safe defaults if unavailable."""
    path = Path(profile_path) if profile_path is not None else DEFAULT_BUSINESS_PROFILE_PATH
    config = copy.deepcopy(_FALLBACK_STORE_CONFIG)

    try:
        with path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
    except (OSError, json.JSONDecodeError):
        return config

    if not isinstance(loaded, dict):
        return config

    config.update(loaded)
    return config


DEFAULT_STORE_CONFIG = load_store_config()
