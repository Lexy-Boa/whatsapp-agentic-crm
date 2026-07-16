from __future__ import annotations

from src.services.ai.prompts.system import build_system_prompt


def test_system_prompt_includes_business_rules_and_escalation():
    prompt = build_system_prompt(
        store_config={
            "brand_name": "DemoBoutique",
            "brand_voice": "warm and practical",
            "business_profile": {
                "description": "South Indian fashion retail assistant.",
                "demo_truth": "Policy still needs owner confirmation.",
            },
            "service_policies": {
                "returns_exchanges": [
                    "Do not approve refunds automatically.",
                    "Ask for order identifier and product photo.",
                ],
                "payments": ["Do not claim COD unless configured by the owner."],
            },
            "unknown_policy_response": "I will check this with the team.",
            "escalation_rules": [
                "refund request",
                "damaged product",
                "question depends on unconfirmed store policy",
            ],
        },
        language="en",
    )

    assert "Business profile:" in prompt
    assert "returns exchanges:" in prompt
    assert "Do not approve refunds automatically." in prompt
    assert "Do not claim COD unless configured by the owner." in prompt
    assert "Unknown policy response: I will check this with the team." in prompt
    assert "refund request" in prompt
    assert "Never approve refunds, exchanges, discounts, delivery dates" in prompt


def test_system_prompt_keeps_policy_section_out_when_not_configured():
    prompt = build_system_prompt(
        store_config={"brand_name": "DemoBoutique", "brand_voice": "friendly"},
        language="en",
    )

    assert "Business profile:" not in prompt
    assert "Business rules:" not in prompt
