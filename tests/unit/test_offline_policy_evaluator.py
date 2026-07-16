from __future__ import annotations

from src.services.demo.offline_policy_evaluator import (
    evaluate_examples,
    format_report,
    infer_policy_behavior,
    load_examples,
)


def test_policy_safe_examples_fixture_passes_offline_evaluator():
    examples = load_examples()
    results = evaluate_examples(examples)

    assert len(results) == 10
    assert all(result.passed for result in results)


def test_infer_policy_behavior_detects_refund_guardrails():
    inferred = infer_policy_behavior("Can I return this if it does not fit?")

    assert inferred.handoff == "yes"
    assert "return_or_exchange_request" in inferred.tags
    assert "must_not_approve_return" in inferred.tags
    assert "must_escalate" in inferred.tags


def test_infer_policy_behavior_detects_inventory_lookup_without_handoff():
    inferred = infer_policy_behavior("Is DMB-3001 available?")

    assert inferred.handoff == "no"
    assert "inventory_lookup" in inferred.tags
    assert "must_use_inventory" in inferred.tags
    assert "must_not_invent_stock" in inferred.tags
    assert "must_escalate" not in inferred.tags


def test_infer_policy_behavior_does_not_treat_budget_as_bulk_quantity():
    inferred = infer_policy_behavior("I need a saree under 10000 for wedding.")

    assert inferred.handoff == "no"
    assert "product_recommendation" in inferred.tags
    assert "bulk_order" not in inferred.tags
    assert "must_escalate" not in inferred.tags


def test_infer_policy_behavior_detects_policy_unknowns():
    inferred = infer_policy_behavior("Do you have COD?")

    assert inferred.handoff == "conditional"
    assert "payment_policy_unknown" in inferred.tags
    assert "must_not_claim_cod" in inferred.tags
    assert "team_must_confirm" in inferred.tags


def test_format_report_is_operator_readable():
    results = evaluate_examples(load_examples())
    report = format_report(results)

    assert "DemoBoutique Offline Demo Policy Evaluator" in report
    assert "Result: 10/10 passed" in report
    assert "[PASS] cod_payment_unknown" in report
