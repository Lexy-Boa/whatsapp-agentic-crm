from __future__ import annotations

import json
import re
from pathlib import Path

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "demo"
    / "demoboutique_whatsapp_template_drafts.json"
)

_PLACEHOLDER_RE = re.compile(r"\{\{(\d+)\}\}")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_CATEGORIES = {"UTILITY", "MARKETING", "AUTHENTICATION"}


def _load_template_pack() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_template_pack_is_owner_editable_and_has_expected_templates():
    pack = _load_template_pack()

    assert pack["status"] == "draft_owner_review"
    assert "editing_instructions" in pack
    assert {template["name"] for template in pack["templates"]} == {
        "assistant_unavailable",
        "handoff_followup",
        "order_detail_request",
        "delivery_status_update",
        "promo_opt_in",
    }


def test_template_drafts_have_valid_metadata_and_placeholder_definitions():
    pack = _load_template_pack()

    for template in pack["templates"]:
        assert _NAME_RE.match(template["name"])
        assert template["category"] in _ALLOWED_CATEGORIES
        assert template["status"] == "draft_owner_review"
        assert template["purpose"]
        assert template["message_body"]
        assert template["owner_questions"]
        assert template["submission_notes"]

        placeholders = {
            int(match.group(1))
            for match in _PLACEHOLDER_RE.finditer(template["message_body"])
        }
        variable_indexes = {variable["index"] for variable in template["variables"]}

        assert placeholders == variable_indexes
        for variable in template["variables"]:
            assert variable["meaning"]
            assert variable["example"]
