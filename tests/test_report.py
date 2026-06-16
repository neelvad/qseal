from qseal.dbt.scan import DbtModelScanResult, DbtScanResult
from qseal.report.text import render_dbt_scan_diff_report, render_suggestions_report
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus


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
                    scanned_path="/tmp/project/models/users.sql",
                    source_path="/tmp/project/models/users.sql",
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


def test_render_dbt_scan_diff_report_uses_source_path() -> None:
    report = render_dbt_scan_diff_report(
        DbtScanResult(
            project_path="/tmp/project",
            model_count=1,
            results=(
                DbtModelScanResult(
                    path="/tmp/project/target/compiled/project/models/users.sql",
                    scanned_path="/tmp/project/target/compiled/project/models/users.sql",
                    source_path="/tmp/project/models/users.sql",
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

    assert "--- /tmp/project/models/users.sql" in report


def test_render_dbt_scan_report_shows_source_and_scanned_paths() -> None:
    from qseal.report.text import render_dbt_scan_report

    report = render_dbt_scan_report(
        DbtScanResult(
            project_path="/tmp/project",
            model_count=1,
            results=(
                DbtModelScanResult(
                    path="/tmp/project/target/compiled/project/models/users.sql",
                    scanned_path="/tmp/project/target/compiled/project/models/users.sql",
                    source_path="/tmp/project/models/users.sql",
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

    assert "/tmp/project/models/users.sql" in report.plain
    assert "Scanned SQL: /tmp/project/target/compiled/project/models/users.sql" in report.plain
    assert "Apply ready: no" in report.plain
    assert (
        "Apply blocker: Scanned compiled SQL; source file was not verified directly."
        in report.plain
    )
    assert "Summary:" in report.plain
    assert "PROVEN_EQUIVALENT: 1" in report.plain
    assert "remove_redundant_distinct: 1" in report.plain


def test_render_dbt_scan_report_shows_reason_counts() -> None:
    from qseal.report.text import render_dbt_scan_report

    report = render_dbt_scan_report(
        DbtScanResult(
            project_path="/tmp/project",
            model_count=1,
            results=(
                DbtModelScanResult(
                    path="/tmp/project/models/users.sql",
                    scanned_path="/tmp/project/models/users.sql",
                    source_path="/tmp/project/models/users.sql",
                    suggestions=(
                        RewriteSuggestion(
                            rule_name="dbt_scan",
                            status=VerificationStatus.UNSUPPORTED,
                            original_sql="SELECT * FROM {{ ref('users') }}",
                            reason=(
                                "Model contains dbt/Jinja syntax and must be compiled "
                                "before scanning."
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    assert "Reasons:" in report.plain
    assert "1x Model contains dbt/Jinja syntax" in report.plain
