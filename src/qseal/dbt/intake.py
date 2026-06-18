from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from qseal.dbt.scan import DbtModelScanResult, DbtScanResult
from qseal.report.guards import required_guarding_tests
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus
from qseal.rewrites.registry import RewriteRule, rule_names


def build_dbt_intake_report(
    scan_result: DbtScanResult,
    *,
    rules: Sequence[RewriteRule],
    include_all: bool,
    compiled_sql: bool,
    use_compiled_auto: bool,
    chain: bool,
    max_chain_steps: int,
) -> dict[str, Any]:
    """Build a shareable aggregate dbt scan report with no SQL or paths."""
    rows = tuple(_iter_metric_suggestions(scan_result))
    proven_model_count = sum(
        result.has_proven_findings()
        for result in scan_result.results
    )
    apply_ready_model_count = sum(
        result.has_proven_findings() and result.apply_ready()
        for result in scan_result.results
    )
    proven_finding_count = scan_result.proven_finding_count()

    summary = {
        "model_count": scan_result.model_count,
        "result_count": len(scan_result.results),
        "silent_model_count": max(scan_result.model_count - len(scan_result.results), 0),
        "proven_model_count": proven_model_count,
        "proven_finding_count": proven_finding_count,
        "apply_ready_model_count": apply_ready_model_count,
        "result_rate": _ratio(len(scan_result.results), scan_result.model_count),
        "proven_models_per_scanned_model": _ratio(
            proven_model_count,
            scan_result.model_count,
        ),
        "proven_findings_per_scanned_model": _ratio(
            proven_finding_count,
            scan_result.model_count,
        ),
        "status_counts": _status_counts(rows),
        "rule_counts": _rule_counts(rows),
        "reason_category_counts": _reason_category_counts(rows),
        "apply_blocker_category_counts": _apply_blocker_counts(scan_result.results),
        "required_test_category_counts": _required_test_counts(rows),
    }

    return {
        "schema_version": 1,
        "artifact_type": "dbt_intake",
        "dialect": scan_result.dialect,
        "redaction": {
            "level": "aggregate_only",
            "contains_sql": False,
            "contains_file_paths": False,
            "contains_model_names": False,
            "contains_diffs": False,
            "contains_raw_reasons": False,
            "contains_literal_values": False,
        },
        "scan_options": {
            "include_all": include_all,
            "compiled_sql": compiled_sql,
            "use_compiled_auto": use_compiled_auto,
            "chain": chain,
            "max_chain_steps": max_chain_steps if chain else None,
            "rules": list(rule_names(rules)),
        },
        "summary": summary,
        "chain_summary": _chain_summary(scan_result),
        "rule_families": _rule_families(rows),
    }


def _iter_metric_suggestions(
    scan_result: DbtScanResult,
) -> Iterable[tuple[DbtModelScanResult, RewriteSuggestion]]:
    for result in scan_result.results:
        for suggestion in result.metric_suggestions():
            yield result, suggestion


def _status_counts(
    rows: Sequence[tuple[DbtModelScanResult, RewriteSuggestion]],
) -> dict[str, int]:
    counts = Counter(suggestion.status.value for _, suggestion in rows)
    return _sorted_counts(counts)


def _rule_counts(
    rows: Sequence[tuple[DbtModelScanResult, RewriteSuggestion]],
) -> dict[str, int]:
    counts = Counter(suggestion.rule_name for _, suggestion in rows)
    return _sorted_counts(counts)


def _reason_category_counts(
    rows: Sequence[tuple[DbtModelScanResult, RewriteSuggestion]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for _, suggestion in rows:
        if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT:
            continue
        if suggestion.reason:
            counts[_reason_category(suggestion.reason)] += 1
    return _sorted_counts(counts)


def _apply_blocker_counts(
    results: Sequence[DbtModelScanResult],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for result in results:
        if not result.has_proven_findings() or result.apply_ready():
            continue
        counts[_apply_blocker_category(result.apply_blocker())] += 1
    return _sorted_counts(counts)


def _required_test_counts(
    rows: Sequence[tuple[DbtModelScanResult, RewriteSuggestion]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for _, suggestion in rows:
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            continue
        for test in required_guarding_tests(suggestion):
            counts[_required_test_category(test)] += 1
    return _sorted_counts(counts)


def _rule_families(
    rows: Sequence[tuple[DbtModelScanResult, RewriteSuggestion]],
) -> list[dict[str, Any]]:
    by_rule: dict[str, dict[str, Any]] = {}
    for result, suggestion in rows:
        family = by_rule.setdefault(
            suggestion.rule_name,
            {
                "rule_name": suggestion.rule_name,
                "count": 0,
                "proven_count": 0,
                "apply_ready_count": 0,
                "status_counts": Counter(),
                "required_test_category_counts": Counter(),
            },
        )
        family["count"] += 1
        family["status_counts"][suggestion.status.value] += 1
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            continue
        family["proven_count"] += 1
        if result.apply_ready():
            family["apply_ready_count"] += 1
        for test in required_guarding_tests(suggestion):
            family["required_test_category_counts"][_required_test_category(test)] += 1

    return [
        {
            **family,
            "status_counts": _sorted_counts(family["status_counts"]),
            "required_test_category_counts": _sorted_counts(
                family["required_test_category_counts"]
            ),
        }
        for family in sorted(by_rule.values(), key=lambda item: item["rule_name"])
    ]


def _chain_summary(scan_result: DbtScanResult) -> dict[str, int]:
    step_counts = [
        result.rewrite_chain.step_count
        for result in scan_result.results
        if result.rewrite_chain is not None
    ]
    return {
        "model_count_with_chain": sum(step_count > 0 for step_count in step_counts),
        "verified_step_count": sum(step_counts),
        "max_observed_steps": max(step_counts, default=0),
    }


def _required_test_category(test: str) -> str:
    if test.startswith("dbt test: unique combination on "):
        return "unique_combination"
    if test.startswith("dbt test: unique on "):
        return "unique"
    if test.startswith("dbt test: not_null on "):
        return "not_null"
    if test.startswith("dbt test: relationships from "):
        return "relationships"
    if test.startswith("dbt test: accepted_values on "):
        return "accepted_values"
    return "other"


def _apply_blocker_category(blocker: str | None) -> str:
    if blocker is None:
        return "none"
    lowered = blocker.lower()
    if "no proven rewrite" in lowered:
        return "no_proven_rewrite"
    if "normalized" in lowered:
        return "source_sql_normalized"
    if "compiled sql" in lowered:
        return "compiled_sql_not_directly_applicable"
    if "no matching source" in lowered:
        return "no_matching_source_model"
    return "other"


def _reason_category(reason: str) -> str:
    lowered = reason.lower()
    if "dbt/jinja block" in lowered:
        return "dbt_jinja_block"
    if "dbt/jinja expression" in lowered:
        return "dbt_jinja_expression"
    if "could not parse sql" in lowered:
        return "sql_parse_error"
    if "not known to reference" in lowered:
        return "missing_relationship_premise"
    if "not known to be a non-null unique key" in lowered:
        return "missing_non_null_unique_premise"
    if "not trusted non-null" in lowered or "trusted non-null" in lowered:
        return "missing_not_null_premise"
    if "not known to be unique" in lowered or "unique key" in lowered:
        return "missing_unique_premise"
    if "no trusted constraints" in lowered:
        return "missing_relation_constraints"
    if "accepted-values" in lowered or "accepted values" in lowered:
        return "accepted_values_shape_or_premise"
    if "cte" in lowered or "with clauses" in lowered or "recursive" in lowered:
        return "cte_unsupported_shape"
    if "join" in lowered:
        return "join_unsupported_shape"
    if "group by" in lowered or "having" in lowered:
        return "grouping_unsupported_shape"
    if "qualify" in lowered:
        return "qualify_unsupported_shape"
    if "where" in lowered or "predicate" in lowered:
        return "predicate_unsupported_shape"
    if "projection" in lowered or "projected" in lowered:
        return "projection_unsupported_shape"
    if "subquery" in lowered:
        return "subquery_unsupported_shape"
    if "direct table" in lowered or "direct tables" in lowered:
        return "relation_unsupported_shape"
    if "distinct" in lowered:
        return "distinct_unsupported_shape"
    if "only select statements" in lowered:
        return "unsupported_statement"
    return "other"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _sorted_counts(counts: Counter[str] | dict[str, int]) -> dict[str, int]:
    return {
        key: counts[key]
        for key in sorted(counts)
        if counts[key]
    }
