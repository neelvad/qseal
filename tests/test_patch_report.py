from pathlib import Path

from snowprove.dbt.scan import DbtModelScanResult, DbtScanResult
from snowprove.report.patch import write_dbt_scan_patches
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


def test_write_dbt_scan_patches(tmp_path: Path) -> None:
    project = tmp_path / "project"
    output = tmp_path / "patches"
    model = project / "models" / "users.sql"
    result = DbtScanResult(
        project_path=project,
        model_count=1,
        results=(
            DbtModelScanResult(
                path=model,
                scanned_path=model,
                source_path=model,
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

    written = write_dbt_scan_patches(result, output)

    assert written == (output / "models" / "users.sql.remove_redundant_distinct.patch",)
    assert "-SELECT DISTINCT user_id" in written[0].read_text()
    assert "+SELECT user_id" in written[0].read_text()
