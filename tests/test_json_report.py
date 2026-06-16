import json

from qseal.dbt.scan import DbtScanResult
from qseal.report.json import (
    render_dbt_scan_json,
    render_suggestion_json,
    render_suggestions_json,
    render_verification_json,
)
from qseal.report.patch import PatchWriteResult
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus
from qseal.verifier.model import VerificationResult


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

    assert payload["schema_version"] == 1
    assert payload["artifact_type"] == "suggestion"
    assert payload["rule_name"] == "rule"
    assert payload["status"] == "PROVEN_EQUIVALENT"


def test_render_verification_json() -> None:
    payload = json.loads(
        render_verification_json(
            VerificationResult(
                status=VerificationStatus.UNKNOWN,
                original_sql="SELECT 1",
                rewritten_sql="SELECT 2",
                inputs={"original_path": "original.sql"},
                reason="No rule applies.",
            )
        )
    )

    assert payload["schema_version"] == 1
    assert payload["artifact_type"] == "verification"
    assert payload["proven"] is False
    assert payload["status"] == "UNKNOWN"
    assert payload["inputs"]["original_path"] == "original.sql"
    assert payload["reason"] == "No rule applies."
    assert payload["safety_claim"] is None
    assert payload["verification_method"] is None


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

    assert payload["schema_version"] == 1
    assert payload["artifact_type"] == "suggestions"
    assert [item["rule_name"] for item in payload["results"]] == ["proven"]


def test_render_dbt_scan_json() -> None:
    payload = json.loads(
        render_dbt_scan_json(
            DbtScanResult(
                project_path="/tmp/project",
                model_count=1,
                results=[
                    {
                        "path": "/tmp/project/models/users.sql",
                        "scanned_path": "/tmp/project/models/users.sql",
                        "source_path": "/tmp/project/models/users.sql",
                        "suggestions": [
                            {
                                "rule_name": "remove_redundant_distinct",
                                "status": "PROVEN_EQUIVALENT",
                                "original_sql": "SELECT DISTINCT user_id FROM users",
                                "rewritten_sql": "SELECT user_id FROM users;",
                            }
                        ],
                    }
                ],
            )
        )
    )

    assert payload["schema_version"] == 1
    assert payload["artifact_type"] == "dbt_scan"
    assert payload["project_path"] == "/tmp/project"
    assert payload["model_count"] == 1
    assert payload["results"][0]["apply_ready"] is True
    assert payload["results"][0]["apply_blocker"] is None
    assert payload["results"][0]["patches"] == []
    assert payload["summary"]["proven_finding_count"] == 1
    assert payload["summary"]["reason_counts"] == {}


def test_render_dbt_scan_json_includes_patch_paths() -> None:
    payload = json.loads(
        render_dbt_scan_json(
            DbtScanResult(
                project_path="/tmp/project",
                model_count=1,
                results=[
                    {
                        "path": "/tmp/project/models/users.sql",
                        "scanned_path": "/tmp/project/models/users.sql",
                        "source_path": "/tmp/project/models/users.sql",
                        "suggestions": [
                            {
                                "rule_name": "remove_redundant_distinct",
                                "status": "PROVEN_EQUIVALENT",
                                "original_sql": "SELECT DISTINCT user_id FROM users",
                                "rewritten_sql": "SELECT user_id FROM users;",
                            }
                        ],
                    }
                ],
            ),
            patch_results=[
                PatchWriteResult(
                    path="/tmp/project/patches/models/users.sql.remove.patch",
                    model_path="/tmp/project/models/users.sql",
                    rule_name="remove_redundant_distinct",
                )
            ],
        )
    )

    assert payload["results"][0]["patches"] == [
        {
            "path": "/tmp/project/patches/models/users.sql.remove.patch",
            "required_tests": [],
            "rule_name": "remove_redundant_distinct",
        }
    ]
