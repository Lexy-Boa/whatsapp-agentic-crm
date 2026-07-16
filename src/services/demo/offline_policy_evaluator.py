"""
Offline evaluator for DemoBoutique demo policy-safety examples.

This is deliberately deterministic. It does not judge generated AI copy; it
checks whether our documented demo examples map to the expected guardrail
categories before we spend credits on Anthropic/Groq/OpenAI validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXAMPLES_PATH = (
    PROJECT_ROOT / "data" / "demo" / "demoboutique_policy_safe_examples.json"
)

HandoffExpectation = Literal["yes", "no", "optional", "conditional"]

_SKU_RE = re.compile(r"\b[A-Z]{2,5}-\d{3,6}\b")
_BULK_RE = re.compile(r"\b(?:1[5-9]|[2-9]\d|\d{3,})\b")
_PRODUCT_WORDS = frozenset(
    {
        "saree",
        "sarees",
        "churidar",
        "kurta",
        "kidswear",
        "dress",
        "outfit",
    }
)


@dataclass(frozen=True)
class PolicyExample:
    id: str
    customer_message: str
    expected_behavior: str
    expected_handoff: HandoffExpectation
    required_tags: tuple[str, ...]
    forbidden_tags: tuple[str, ...]


@dataclass(frozen=True)
class InferredPolicyBehavior:
    handoff: HandoffExpectation
    tags: frozenset[str]


@dataclass(frozen=True)
class PolicyEvaluationResult:
    case_id: str
    passed: bool
    expected_handoff: HandoffExpectation
    inferred_handoff: HandoffExpectation
    missing_tags: tuple[str, ...]
    forbidden_tags_present: tuple[str, ...]
    inferred_tags: tuple[str, ...]


def load_examples(path: Path | str = DEFAULT_EXAMPLES_PATH) -> list[PolicyExample]:
    """Load policy-safe demo examples from JSON."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = raw.get("cases", [])
    return [
        PolicyExample(
            id=item["id"],
            customer_message=item["customer_message"],
            expected_behavior=item["expected_behavior"],
            expected_handoff=item["expected_handoff"],
            required_tags=tuple(item.get("required_tags", [])),
            forbidden_tags=tuple(item.get("forbidden_tags", [])),
        )
        for item in cases
    ]


def infer_policy_behavior(message: str) -> InferredPolicyBehavior:
    """Infer expected policy behavior from a customer message using simple rules."""
    text = message.lower()
    tags: set[str] = set()
    handoff: HandoffExpectation = "no"

    if "person" in text or "human" in text or "owner" in text or "staff" in text:
        tags.update({"human_requested", "must_escalate"})
        handoff = "yes"

    if "damaged" in text or "damage" in text or "wrong item" in text or "broken" in text:
        tags.update({"damaged_item_claim", "ask_order_id", "ask_photo", "must_escalate"})
        handoff = "yes"

    if "return" in text or "exchange" in text or "does not fit" in text or "doesn't fit" in text:
        tags.update(
            {
                "return_or_exchange_request",
                "must_not_approve_return",
                "ask_order_or_product_context",
                "must_escalate",
            }
        )
        handoff = "yes"

    if "discount" in text or "less price" in text or "best price" in text:
        tags.update({"discount_request", "must_not_offer_discount", "team_must_confirm", "must_escalate"})
        handoff = "yes"

    if "bulk" in text or "wholesale" in text or _looks_like_bulk_quantity(text):
        tags.update({"bulk_order", "must_escalate"})
        handoff = "yes"

    if "cod" in text or "cash on delivery" in text:
        tags.update({"payment_policy_unknown", "must_not_claim_cod", "team_must_confirm"})
        if handoff == "no":
            handoff = "conditional"

    if "payment" in text or "upi" in text or "card" in text or "payment link" in text:
        tags.update({"payment_policy_unknown", "team_must_confirm"})
        if handoff == "no":
            handoff = "conditional"

    if (
        "where is your shop" in text
        or "address" in text
        or "location" in text
        or "map" in text
        or "store hours" in text
        or "open" in text
    ):
        tags.update({"store_detail_unknown", "must_not_invent_location", "team_must_confirm"})
        if handoff == "no":
            handoff = "optional"

    if (
        "order" in text
        or "arrive" in text
        or "delivery" in text
        or "tracking" in text
        or "courier" in text
    ):
        tags.update({"order_or_delivery_question", "ask_order_id", "must_not_promise_delivery_date"})
        if handoff == "no":
            handoff = "conditional"

    if _SKU_RE.search(message):
        tags.update({"inventory_lookup", "must_use_inventory", "must_not_invent_stock"})
        if handoff == "no":
            handoff = "no"

    if _looks_like_product_recommendation(text):
        tags.update({"product_recommendation", "must_use_catalog", "must_not_invent_products"})
        if handoff == "no":
            handoff = "no"

    if not tags:
        tags.add("needs_manual_review")
        handoff = "optional"

    return InferredPolicyBehavior(handoff=handoff, tags=frozenset(tags))


def evaluate_examples(examples: list[PolicyExample]) -> list[PolicyEvaluationResult]:
    """Evaluate examples against deterministic policy behavior rules."""
    results: list[PolicyEvaluationResult] = []
    for example in examples:
        inferred = infer_policy_behavior(example.customer_message)
        missing = tuple(tag for tag in example.required_tags if tag not in inferred.tags)
        forbidden_present = tuple(
            tag for tag in example.forbidden_tags if tag in inferred.tags
        )
        handoff_ok = _handoff_matches(example.expected_handoff, inferred.handoff)
        passed = not missing and not forbidden_present and handoff_ok
        results.append(
            PolicyEvaluationResult(
                case_id=example.id,
                passed=passed,
                expected_handoff=example.expected_handoff,
                inferred_handoff=inferred.handoff,
                missing_tags=missing,
                forbidden_tags_present=forbidden_present,
                inferred_tags=tuple(sorted(inferred.tags)),
            )
        )
    return results


def format_report(results: list[PolicyEvaluationResult]) -> str:
    """Format a concise operator-friendly report."""
    passed = sum(1 for result in results if result.passed)
    total = len(results)
    lines = [
        "DemoBoutique Offline Demo Policy Evaluator",
        f"Result: {passed}/{total} passed",
        "",
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            f"[{status}] {result.case_id} "
            f"(handoff expected={result.expected_handoff}, inferred={result.inferred_handoff})"
        )
        if result.missing_tags:
            lines.append(f"  missing: {', '.join(result.missing_tags)}")
        if result.forbidden_tags_present:
            lines.append(f"  forbidden present: {', '.join(result.forbidden_tags_present)}")
        lines.append(f"  inferred tags: {', '.join(result.inferred_tags)}")
    return "\n".join(lines)


def _handoff_matches(expected: HandoffExpectation, inferred: HandoffExpectation) -> bool:
    if expected == inferred:
        return True
    if expected == "optional" and inferred in {"optional", "conditional"}:
        return True
    if expected == "conditional" and inferred in {"conditional", "yes"}:
        return True
    return False


def _has_product_word(text: str) -> bool:
    words = {word.strip(".,?!") for word in text.split()}
    return bool(words & _PRODUCT_WORDS)


def _looks_like_bulk_quantity(text: str) -> bool:
    if not _has_product_word(text):
        return False
    if any(price_cue in text for price_cue in ("under", "below", "budget", "price", "rs", "inr")):
        return False
    return bool(_BULK_RE.search(text))


def _looks_like_product_recommendation(text: str) -> bool:
    if not _has_product_word(text):
        return False
    return any(
        cue in text
        for cue in (
            "need",
            "looking for",
            "recommend",
            "suggest",
            "under",
            "wedding",
            "festival",
            "function",
        )
    )
