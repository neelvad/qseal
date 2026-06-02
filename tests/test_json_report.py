import json

from snowprove.dbt.scan import DbtScanResult
from snowprove.report.json import (
    render_dbt_scan_json,
    render_suggestion_json,
    render_suggestions_json,
    render_verification_json,
)
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


def test_render_suggestions_json_omits_not_applicable_results() -> None:
    payload = json.loads(
        render_suggestions_json(
            [
                RewriteSuggestion(
                    rule_name="not_applicable",
                    status=VerificationStatus.NOT_APPLICABLE,
                    original_sql="SELECT 1",
                ),
                RewriteSuggestion(
                    rule_name="proven",
                    status=VerificationStatus.PROVEN_EQUIVALENT,
                    original_sql="SELECT 1",
                    rewritten_sql="SELECT 1;",
                ),
            ]
        )
    )

    assert [item["rule_name"] for item in payload] == ["proven"]


def test_render_dbt_scan_json() -> None:
    payload = json.loads(
        render_dbt_scan_json(DbtScanResult(project_path="/tmp/project", model_count=0))
    )

    assert payload["project_path"] == "/tmp/project"
    assert payload["model_count"] == 0
