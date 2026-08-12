from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORACLE = (
    PROJECT_ROOT / "tests/fixtures/quality/oracle-linux-9.8-noise-oracle.yaml"
)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _records(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _unqualified_hits(
    document: str,
    controls: object,
    *,
    context_characters: int = 240,
) -> list[dict[str, str]]:
    folded = document.casefold()
    failures: list[dict[str, str]] = []
    for control in _records(controls):
        control_id = str(control.get("id", "unknown"))
        qualifiers = tuple(
            qualifier.casefold()
            for qualifier in _strings(control.get("required_qualifiers_if_retained"))
        )
        for literal in _strings(control.get("literals")):
            needle = literal.casefold()
            offset = 0
            while True:
                index = folded.find(needle, offset)
                if index < 0:
                    break
                start = max(0, index - context_characters)
                end = min(len(folded), index + len(needle) + context_characters)
                context = folded[start:end]
                if not qualifiers or not any(item in context for item in qualifiers):
                    failures.append({"id": control_id, "literal": literal})
                offset = index + len(needle)
    return failures


def evaluate(document: str, oracle: Mapping[str, Any]) -> dict[str, Any]:
    folded = document.casefold()
    required = _records(oracle.get("required_current_facts"))
    missing_current_facts: list[str] = []
    for fact in required:
        terms = _strings(fact.get("required_terms"))
        if not terms or not all(term.casefold() in folded for term in terms):
            missing_current_facts.append(str(fact.get("id", "unknown")))

    nontechnical_leaks = [
        literal
        for literal in _strings(oracle.get("nontechnical_forbidden_literals"))
        if literal.casefold() in folded
    ]
    secret_leaks = [
        literal
        for literal in _strings(oracle.get("secret_literals_forbidden"))
        if literal.casefold() in folded
    ]
    rejected_as_current = _unqualified_hits(
        document,
        oracle.get("rejected_claims_not_to_present_as_current"),
    )
    superseded_as_current = _unqualified_hits(
        document,
        oracle.get("superseded_claims_not_to_present_as_current"),
    )
    recall = 1.0 if not required else (len(required) - len(missing_current_facts)) / len(required)
    expected = oracle.get("acceptance_metrics")
    expected_recall = 1.0
    if isinstance(expected, Mapping):
        value = expected.get("current_fact_recall")
        if isinstance(value, (int, float)):
            expected_recall = float(value)

    passed = (
        recall >= expected_recall
        and not nontechnical_leaks
        and not secret_leaks
        and not rejected_as_current
        and not superseded_as_current
    )
    return {
        "passed": passed,
        "metrics": {
            "current_fact_recall": round(recall, 4),
            "nontechnical_literal_leakage": len(nontechnical_leaks),
            "secret_literal_leakage": len(secret_leaks),
            "rejected_claims_presented_as_current": len(rejected_as_current),
            "superseded_claims_presented_as_current": len(superseded_as_current),
        },
        "failures": {
            "missing_current_facts": missing_current_facts,
            "nontechnical_literals": nontechnical_leaks,
            "secret_literals": secret_leaks,
            "unqualified_rejected_claims": rejected_as_current,
            "unqualified_superseded_claims": superseded_as_current,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="노이즈가 포함된 원본으로 생성한 RAG 문서의 품질을 채점합니다."
    )
    parser.add_argument("document", type=Path, help="평가할 최종 Markdown 문서")
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    return parser


def main() -> int:
    args = _parser().parse_args()
    document = args.document.read_text(encoding="utf-8")
    loaded = yaml.safe_load(args.oracle.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("quality oracle must be a mapping")
    result = evaluate(document, loaded)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
