import json
from collections.abc import Sequence
from typing import Any

from snowprove.report.patch import PatchWriteResult
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.verifier.model import VerificationResult


def render_suggestion_json(suggestion: RewriteSuggestion) -> str:
    payload = suggestion.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "suggestion"
    return _dumps(payload)


def render_suggestions_json(suggestions: Sequence[RewriteSuggestion]) -> str:
    visible = [
        suggestion
        for suggestion in suggestions
        if suggestion.status != VerificationStatus.NOT_APPLICABLE
    ]
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "suggestions",
            "results": [suggestion.model_dump(mode="json") for suggestion in visible],
        }
    )


def render_verification_json(result: VerificationResult) -> str:
    payload = result.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "verification"
    payload["proven"] = result.status == VerificationStatus.PROVEN_EQUIVALENT
    return _dumps(payload)


def render_candidate_verifications_json(
    results: Sequence[VerificationResult],
    metadata_by_path: dict[str, dict[str, Any]] | None = None,
) -> str:
    metadata_by_path = metadata_by_path or {}
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "candidate_verifications",
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
) -> str:
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "candidate_generation",
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
) -> str:
    return _dumps(
        {
            "schema_version": 1,
            "artifact_type": "candidate_run",
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
    payload["summary"] = scan_result.summary()
    return _dumps(payload)


def _patches_by_model(
    patch_results: Sequence[PatchWriteResult],
) -> dict[str, list[dict[str, str]]]:
    patches: dict[str, list[dict[str, str]]] = {}
    for result in patch_results:
        patches.setdefault(str(result.model_path), []).append(
            {
                "path": str(result.path),
                "rule_name": result.rule_name,
            }
        )
    return patches


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
