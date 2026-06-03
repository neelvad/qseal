import json
from collections.abc import Sequence
from typing import Any

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


def render_dbt_scan_json(scan_result) -> str:
    payload = scan_result.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "dbt_scan"
    for index, result in enumerate(scan_result.results):
        payload["results"][index]["apply_ready"] = result.apply_ready()
        payload["results"][index]["apply_blocker"] = result.apply_blocker()
    payload["summary"] = scan_result.summary()
    return _dumps(payload)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
