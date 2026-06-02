from snowprove.report.text import render_suggestions_report
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
