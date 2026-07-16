"""
System prompt builder for the fashion store assistant.
"""

from __future__ import annotations

_LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "ml": "Always respond in Malayalam. Use natural conversational Malayalam.",
    "ta": "Always respond in Tamil.",
    "en": "Respond in English.",
}


def _format_key(key: str) -> str:
    """Convert profile keys into compact prompt labels."""
    return key.replace("_", " ")


def _format_bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values if value)


def _format_business_context(store_config: dict) -> str:
    sections: list[str] = []

    profile = store_config.get("business_profile") or {}
    if isinstance(profile, dict):
        profile_lines = [
            f"- {_format_key(key)}: {value}"
            for key, value in profile.items()
            if isinstance(value, str) and value
        ]
        if profile_lines:
            sections.append("Business profile:\n" + "\n".join(profile_lines))

    service_policies = store_config.get("service_policies") or {}
    if isinstance(service_policies, dict):
        policy_lines: list[str] = []
        for policy_name, rules in service_policies.items():
            if not isinstance(rules, list):
                continue
            compact_rules = [rule for rule in rules if isinstance(rule, str) and rule]
            if compact_rules:
                policy_lines.append(
                    f"- {_format_key(policy_name)}: " + " ".join(compact_rules)
                )
        if policy_lines:
            sections.append("Business rules:\n" + "\n".join(policy_lines))

    unknown_policy_response = store_config.get("unknown_policy_response")
    if isinstance(unknown_policy_response, str) and unknown_policy_response:
        sections.append(f"Unknown policy response: {unknown_policy_response}")

    escalation_rules = store_config.get("escalation_rules") or []
    if isinstance(escalation_rules, list):
        compact_escalations = [
            rule for rule in escalation_rules if isinstance(rule, str) and rule
        ]
        if compact_escalations:
            sections.append(
                "Escalate to human for:\n" + _format_bullets(compact_escalations)
            )

    if not sections:
        return ""

    guardrails = (
        "Business guardrails:\n"
        "- Never approve refunds, exchanges, discounts, delivery dates, custom "
        "orders, COD/payment methods, or policy exceptions unless the business "
        "profile explicitly confirms them.\n"
        "- If a customer asks for an unconfirmed fact, use the unknown-policy "
        "response and escalate if the answer affects money, delivery, or trust."
    )
    sections.append(guardrails)
    return "\n\n" + "\n\n".join(sections) + "\n"


def build_system_prompt(
    store_config: dict,
    language: str,
    dialect: str | None = None,
) -> str:
    """
    Build a system prompt for the fashion store assistant.

    Args:
        store_config: Store configuration dict with brand_name, brand_voice, etc.
        language:     ISO 639-1 language code (ml, ta, en, …).
        dialect:      Optional dialect name for register matching.

    Returns:
        Formatted system prompt string.
    """
    brand_name = store_config.get("brand_name", "the store")
    brand_voice = store_config.get("brand_voice", "friendly and helpful")

    lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
        language,
        f"Respond in the customer's language (code: {language}).",
    )
    if dialect:
        lang_instruction += (
            f" The customer speaks {dialect} dialect — match their"
            " conversational register naturally."
        )

    business_context = _format_business_context(store_config)

    return f"""You are a helpful assistant for {brand_name}, a fashion store.

Brand voice: {brand_voice}

Language: {lang_instruction}
{business_context}

Tone rules:
- Sound like a knowledgeable friend, not a corporate bot.
- Keep responses 2–4 sentences.
- Never use "valued customer", "we appreciate your patience", or similar corporate phrases.
- Emojis: minimal, gen-z style when appropriate (✨ 💫 🫶 😅). Do NOT use 🎉🔥😍.

Tool usage:
- Use search_products when the customer asks about products, wants recommendations, or describes what they're looking for.
- Use check_inventory when asked about availability of a specific product (especially by SKU).
- Use lookup_order when asked about order status, delivery, or tracking.
- Use escalate_to_human for complaints, refund/return requests, custom/bulk orders, when the customer explicitly asks for a human, or queries beyond product knowledge (account issues, delivery disputes).
- If you are unsure or the customer seems frustrated, escalate rather than guessing.

Products constraint: Only mention products returned by search_products or check_inventory. Never invent stock or prices."""
