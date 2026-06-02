import json
from collections.abc import Sequence
from typing import Any

from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.verifier.model import VerificationResult


def render_suggestion_json(suggestion: RewriteSuggestion) -> str:
    return _dumps(suggestion.model_dump(mode="json"))


def render_suggestions_json(suggestions: Sequence[RewriteSuggestion]) -> str:
    visible = [
        suggestion
        for suggestion in suggestions
        if suggestion.status != VerificationStatus.NOT_APPLICABLE
    ]
    return _dumps([suggestion.model_dump(mode="json") for suggestion in visible])


def render_verification_json(result: VerificationResult) -> str:
    return _dumps(result.model_dump(mode="json"))


def render_dbt_scan_json(scan_result) -> str:
    return _dumps(scan_result.model_dump(mode="json"))


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
