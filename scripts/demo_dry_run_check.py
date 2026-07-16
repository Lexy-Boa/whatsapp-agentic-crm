"""
Run no-cost demo readiness checks for the DemoBoutique demo.

This script intentionally avoids paid providers and networked services. It only
checks local files, local configuration presence, deterministic policy examples,
and compose wiring.

Usage:
    python -m scripts.demo_dry_run_check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.services.demo.offline_policy_evaluator import (  # noqa: E402
    evaluate_examples,
    load_examples,
)

READY_WITHOUT_FUNDS = "READY WITHOUT FUNDS"
WAITING_FOR_FUNDS = "WAITING FOR FUNDS/CREDITS"
NEEDS_OWNER_CONFIRMATION = "NEEDS OWNER CONFIRMATION"

REQUIRED_DOCS = (
    "docs/DEMO_RUNBOOK.md",
)
REQUIRED_JSON = (
    "data/demo/demoboutique_mock_catalog.json",
    "data/demo/demoboutique_business_profile.json",
    "data/demo/demoboutique_whatsapp_template_drafts.json",
    "data/demo/demoboutique_policy_safe_examples.json",
)
PAID_OR_LIVE_KEYS = (
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
    "STORE_ID",
)
OWNER_CONFIRMATION_ITEMS = (
    "return/refund/exchange policy",
    "delivery areas and timelines",
    "payment methods/COD/payment links",
    "store address/hours/contact routing",
    "sizing, alteration, and custom-order rules",
    "first WhatsApp templates to submit",
)


@dataclass(frozen=True)
class CheckItem:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class DryRunReport:
    ready_without_funds: list[CheckItem] = field(default_factory=list)
    waiting_for_funds: list[CheckItem] = field(default_factory=list)
    needs_owner_confirmation: list[CheckItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.ready_without_funds)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse simple KEY=value env files without expanding or printing values."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_json_file(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def compose_has_worker_service(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return bool(re.search(r"(?m)^  worker:\s*$", text)) and (
        "python -m src.workers.message_processor" in text
    )


def build_report(root: Path = _PROJECT_ROOT) -> DryRunReport:
    report = DryRunReport()

    for relative in REQUIRED_DOCS:
        path = root / relative
        report.ready_without_funds.append(
            CheckItem(relative, path.exists(), "present" if path.exists() else "missing")
        )

    for relative in REQUIRED_JSON:
        path = root / relative
        try:
            data = load_json_file(path)
            ok = True
            detail = "valid JSON"
            if relative.endswith("demoboutique_mock_catalog.json"):
                ok = isinstance(data, list) and len(data) > 0
                detail = f"{len(data) if isinstance(data, list) else 0} products"
        except Exception as exc:
            ok = False
            detail = f"invalid or missing JSON: {exc}"
        report.ready_without_funds.append(CheckItem(relative, ok, detail))

    for relative in ("docker-compose.yml", "docker-compose.prod.yml"):
        ok = compose_has_worker_service(root / relative)
        report.ready_without_funds.append(
            CheckItem(relative, ok, "worker service present" if ok else "worker service missing")
        )

    try:
        results = evaluate_examples(load_examples(root / "data/demo/demoboutique_policy_safe_examples.json"))
        passed = sum(1 for result in results if result.passed)
        total = len(results)
        report.ready_without_funds.append(
            CheckItem("offline policy evaluator", passed == total, f"{passed}/{total} passed")
        )
    except Exception as exc:
        report.ready_without_funds.append(
            CheckItem("offline policy evaluator", False, str(exc))
        )

    env_values = parse_env_file(root / ".env")
    for key in PAID_OR_LIVE_KEYS:
        present = bool(env_values.get(key))
        report.waiting_for_funds.append(
            CheckItem(key, present, "present" if present else "missing")
        )

    for item in OWNER_CONFIRMATION_ITEMS:
        report.needs_owner_confirmation.append(
            CheckItem(item, False, "owner confirmation still required")
        )

    return report


def format_report(report: DryRunReport) -> str:
    lines = ["DemoBoutique No-Cost Demo Dry Run", ""]
    _append_section(lines, READY_WITHOUT_FUNDS, report.ready_without_funds)
    _append_section(lines, WAITING_FOR_FUNDS, report.waiting_for_funds)
    _append_section(lines, NEEDS_OWNER_CONFIRMATION, report.needs_owner_confirmation)
    lines.append("")
    lines.append("Overall no-cost readiness: PASS" if report.ok else "Overall no-cost readiness: FAIL")
    return "\n".join(lines)


def _append_section(lines: list[str], title: str, items: list[CheckItem]) -> None:
    lines.append(title)
    for item in items:
        status = "OK" if item.ok else "WAIT" if title != READY_WITHOUT_FUNDS else "FAIL"
        detail = f" - {item.detail}" if item.detail else ""
        lines.append(f"  [{status}] {item.label}{detail}")
    lines.append("")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run no-cost DemoBoutique demo readiness checks.")
    parser.add_argument(
        "--root",
        type=Path,
        default=_PROJECT_ROOT,
        help="Project root. Defaults to the current whatsapp-crm workspace.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    report = build_report(args.root)
    print(format_report(report))
    if not report.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
