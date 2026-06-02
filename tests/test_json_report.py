import json

from snowprove.report.json import render_suggestion_json, render_verification_json
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.verifier.model import VerificationResult


def test_render_suggestion_json() -> None:
    payload = json.loads(
        render_suggestion_json(
            RewriteSuggestion(
                rule_name="rule",
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql="SELECT 1",
                rewritten_sql="SELECT 1;",
            )
        )
    )

    assert payload["rule_name"] == "rule"
    assert payload["status"] == "PROVEN_EQUIVALENT"


def test_render_verification_json() -> None:
    payload = json.loads(
        render_verification_json(
            VerificationResult(
                status=VerificationStatus.UNKNOWN,
                original_sql="SELECT 1",
                rewritten_sql="SELECT 2",
                reason="No rule applies.",
            )
        )
    )

    assert payload["status"] == "UNKNOWN"
    assert payload["reason"] == "No rule applies."
