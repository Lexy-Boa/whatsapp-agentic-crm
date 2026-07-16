"""
Run the offline DemoBoutique policy-safe demo evaluator.

Usage:
    python -m scripts.evaluate_demo_policy
    python -m scripts.evaluate_demo_policy --examples data/demo/demoboutique_policy_safe_examples.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.services.demo.offline_policy_evaluator import (  # noqa: E402
    DEFAULT_EXAMPLES_PATH,
    evaluate_examples,
    format_report,
    load_examples,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run offline policy-safe checks for the DemoBoutique demo."
    )
    parser.add_argument(
        "--examples",
        default=str(DEFAULT_EXAMPLES_PATH),
        help="Path to policy-safe demo examples JSON.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    examples = load_examples(args.examples)
    results = evaluate_examples(examples)
    print(format_report(results))

    if not all(result.passed for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
