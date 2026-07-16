from __future__ import annotations

import json
from pathlib import Path

from scripts.demo_dry_run_check import (
    build_report,
    compose_has_worker_service,
    format_report,
    parse_env_file,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_env_file_keeps_presence_without_printing_values():
    parsed = parse_env_file(FIXTURES_DIR / "demo_dry_run.env")

    assert parsed["ANTHROPIC_API_KEY"] == "secret-value"
    assert parsed["OPENAI_API_KEY"] == "another-secret"


def test_compose_has_worker_service_detects_worker_command():
    assert compose_has_worker_service(FIXTURES_DIR / "docker-compose-worker.yml") is True


def test_dry_run_report_passes_no_cost_checks_and_redacts_env_values():
    report = build_report()
    text = format_report(report)

    assert report.ok is True
    assert "READY WITHOUT FUNDS" in text
    assert "WAITING FOR FUNDS/CREDITS" in text
    assert "NEEDS OWNER CONFIRMATION" in text
    assert "secret-value" not in text
    assert "sk-" not in text


def test_policy_examples_fixture_has_cases():
    data = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "data"
            / "demo"
            / "demoboutique_policy_safe_examples.json"
        ).read_text(encoding="utf-8")
    )

    assert len(data["cases"]) >= 10
