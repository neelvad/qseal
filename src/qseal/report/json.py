import json
from collections.abc import Sequence
from typing import Any

from qseal.benchmark.model import BenchmarkResult
from qseal.benchmark.snowflake_suite import SnowflakeFamilySuiteReport
from qseal.candidates.evidence import CandidateEvidenceReport
from qseal.dialects import DEFAULT_DIALECT
from qseal.fixtures.model import DuckDbFixtureManifest
from qseal.report.guards import required_guarding_tests
from qseal.report.patch import PatchWriteResult
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus
from qseal.verifier.model import VerificationResult


def render_suggestion_json(
    suggestion: RewriteSuggestion,
    *,
    dialect: str = DEFAULT_DIALECT,
) -> str:
    payload = suggestion.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "suggestion"
    payload["dialect"] = dialect
    payload["required_tests"] = list(required_guarding_tests(suggestion))
    return _dumps(payload)


def render_suggestions_json(
    suggestions: Sequence[RewriteSuggestion],
    *,
    dialect: str = DEFAULT_DIALECT,
) -> str:
    visible = [
        suggestion
        for suggestion in suggestions
        if suggestion.status != VerificationStatus.NOT_APPLICABLE
    ]
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "suggestions",
            "dialect": dialect,
            "results": [_suggestion_payload(suggestion) for suggestion in visible],
        }
    )


def render_rewrite_chain_json(
    chain,
    *,
    dialect: str = DEFAULT_DIALECT,
) -> str:
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "rewrite_chain",
            "dialect": dialect,
            **_rewrite_chain_payload(chain),
        }
    )


def render_verification_json(result: VerificationResult) -> str:
    payload = result.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "verification"
    payload["proven"] = result.status == VerificationStatus.PROVEN_EQUIVALENT
    return _dumps(payload)


def render_duckdb_benchmark_json(result: BenchmarkResult) -> str:
    payload = result.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "duckdb_benchmark"
    payload["dialect"] = "duckdb"
    return _dumps(payload)


def render_snowflake_benchmark_json(result: BenchmarkResult) -> str:
    payload = result.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "snowflake_benchmark"
    payload["dialect"] = "snowflake"
    return _dumps(payload)


def render_snowflake_family_suite_json(result: SnowflakeFamilySuiteReport) -> str:
    return _dumps(result.model_dump(mode="json"))


def render_duckdb_fixture_json(manifest: DuckDbFixtureManifest) -> str:
    return _dumps(manifest.model_dump(mode="json"))


def render_candidate_verifications_json(
    results: Sequence[VerificationResult],
    metadata_by_path: dict[str, dict[str, Any]] | None = None,
    *,
    dialect: str = DEFAULT_DIALECT,
) -> str:
    metadata_by_path = metadata_by_path or {}
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "candidate_verifications",
            "dialect": dialect,
            "result_count": len(results),
            "proven_count": sum(
                result.status == VerificationStatus.PROVEN_EQUIVALENT
                for result in results
            ),
            "results": [
                {
                    **result.model_dump(mode="json"),
                    "proven": result.status == VerificationStatus.PROVEN_EQUIVALENT,
                    "candidate_metadata": metadata_by_path.get(
                        result.inputs.get("rewritten_path", "")
                    ),
                }
                for result in results
            ],
        }
    )


def render_candidate_generation_json(
    *,
    original_path: str,
    output_dir: str,
    generated: Sequence[dict[str, str]],
    skipped: Sequence[dict[str, str]],
    dialect: str = DEFAULT_DIALECT,
) -> str:
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "candidate_generation",
            "dialect": dialect,
            "original_path": original_path,
            "output_dir": output_dir,
            "generated_count": len(generated),
            "skipped_count": len(skipped),
            "generated": list(generated),
            "skipped": list(skipped),
        }
    )


def render_candidate_run_json(
    *,
    generation: dict[str, Any],
    verifications: Sequence[VerificationResult],
    dialect: str = DEFAULT_DIALECT,
) -> str:
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "candidate_run",
            "dialect": dialect,
            "generation": generation,
            "verification": {
                "result_count": len(verifications),
                "proven_count": sum(
                    result.status == VerificationStatus.PROVEN_EQUIVALENT
                    for result in verifications
                ),
                "results": [
                    {
                        **result.model_dump(mode="json"),
                        "proven": result.status == VerificationStatus.PROVEN_EQUIVALENT,
                    }
                    for result in verifications
                ],
            },
        }
    )


def render_candidate_evidence_json(report: CandidateEvidenceReport) -> str:
    return _dumps(report.model_dump(mode="json"))


def render_dbt_scan_json(
    scan_result,
    patch_results: Sequence[PatchWriteResult] = (),
) -> str:
    payload = scan_result.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "dbt_scan"
    patches_by_model = _patches_by_model(patch_results)
    for index, result in enumerate(scan_result.results):
        payload["results"][index]["apply_ready"] = result.apply_ready()
        payload["results"][index]["apply_blocker"] = result.apply_blocker()
        payload["results"][index]["patches"] = patches_by_model.get(str(result.display_path()), [])
        payload["results"][index]["suggestions"] = [
            _suggestion_payload(suggestion)
            for suggestion in result.suggestions
        ]
        if result.rewrite_chain is not None:
            payload["results"][index]["rewrite_chain"] = _rewrite_chain_payload(
                result.rewrite_chain
            )
    payload["summary"] = scan_result.summary()
    return _dumps(payload)


def render_dbt_intake_json(report: dict[str, Any]) -> str:
    return _dumps(report)


def _patches_by_model(
    patch_results: Sequence[PatchWriteResult],
) -> dict[str, list[dict[str, str]]]:
    patches: dict[str, list[dict[str, str]]] = {}
    for result in patch_results:
        patches.setdefault(str(result.model_path), []).append(
            {
                "path": str(result.path),
                "rule_name": result.rule_name,
                "required_tests": list(result.required_tests),
            }
        )
    return patches


def _suggestion_payload(suggestion: RewriteSuggestion) -> dict[str, Any]:
    payload = suggestion.model_dump(mode="json")
    payload["required_tests"] = list(required_guarding_tests(suggestion))
    return payload


def _rewrite_chain_payload(chain) -> dict[str, Any]:
    return {
        "status": chain.status,
        "reason": chain.reason,
        "step_count": chain.step_count,
        "original_sql": chain.original_sql,
        "final_sql": chain.final_sql,
        "steps": [
            {
                "step_index": step.step_index,
                "suggestion": _suggestion_payload(step.suggestion),
            }
            for step in chain.steps
        ],
    }


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
