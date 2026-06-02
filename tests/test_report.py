from snowprove.dbt.scan import DbtModelScanResult, DbtScanResult
from snowprove.report.text import render_dbt_scan_diff_report, render_suggestions_report
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


def test_render_suggestions_report_omits_not_applicable_results() -> None:
    report = render_suggestions_report(
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

    assert "not_applicable" not in report.plain
    assert "proven" in report.plain


def test_render_dbt_scan_diff_report() -> None:
    report = render_dbt_scan_diff_report(
        DbtScanResult(
            project_path="/tmp/project",
            model_count=1,
            results=(
                DbtModelScanResult(
                    path="/tmp/project/models/users.sql",
                    suggestions=(
                        RewriteSuggestion(
                            rule_name="remove_redundant_distinct",
                            status=VerificationStatus.PROVEN_EQUIVALENT,
                            original_sql="SELECT DISTINCT user_id\nFROM users;",
                            rewritten_sql="SELECT user_id\nFROM users;",
                        ),
                    ),
                ),
            ),
        )
    )

    assert "-SELECT DISTINCT user_id" in report
    assert "+SELECT user_id" in report
