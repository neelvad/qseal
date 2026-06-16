from pathlib import Path

from qseal.dbt.scan import DbtModelScanResult, DbtScanResult
from qseal.report.patch import (
    apply_dbt_scan_patches,
    write_dbt_scan_patch_results,
    write_dbt_scan_patches,
)
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus


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


def test_write_dbt_scan_patch_results(tmp_path: Path) -> None:
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

    written = write_dbt_scan_patch_results(result, output)

    assert len(written) == 1
    assert written[0].path == output / "models" / "users.sql.remove_redundant_distinct.patch"
    assert written[0].model_path == model
    assert written[0].rule_name == "remove_redundant_distinct"


def test_apply_dbt_scan_patches_rewrites_matching_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    model = project / "models" / "users.sql"
    model.parent.mkdir(parents=True)
    model.write_text("SELECT DISTINCT user_id\nFROM users\n")
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
                        original_sql="SELECT DISTINCT user_id\nFROM users",
                        rewritten_sql="SELECT user_id\nFROM users;",
                    ),
                ),
            ),
        ),
    )

    applied = apply_dbt_scan_patches(result)

    assert len(applied) == 1
    assert applied[0].applied is True
    assert model.read_text() == "SELECT user_id\nFROM users;\n"


def test_apply_dbt_scan_patches_skips_mismatched_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    model = project / "models" / "users.sql"
    model.parent.mkdir(parents=True)
    model.write_text("SELECT user_id\nFROM users\n")
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
                        original_sql="SELECT DISTINCT user_id\nFROM users",
                        rewritten_sql="SELECT user_id\nFROM users;",
                    ),
                ),
            ),
        ),
    )

    applied = apply_dbt_scan_patches(result)

    assert applied[0].applied is False
    assert "no longer matches" in str(applied[0].reason)
    assert model.read_text() == "SELECT user_id\nFROM users\n"


def test_apply_dbt_scan_patches_skips_compiled_scan_results(tmp_path: Path) -> None:
    project = tmp_path / "project"
    model = project / "models" / "users.sql"
    compiled = project / "target" / "compiled" / "project" / "models" / "users.sql"
    model.parent.mkdir(parents=True)
    compiled.parent.mkdir(parents=True)
    model.write_text("{{ ref('users') }}\n")
    result = DbtScanResult(
        project_path=project,
        model_count=1,
        results=(
            DbtModelScanResult(
                path=compiled,
                scanned_path=compiled,
                source_path=model,
                suggestions=(
                    RewriteSuggestion(
                        rule_name="remove_redundant_distinct",
                        status=VerificationStatus.PROVEN_EQUIVALENT,
                        original_sql="SELECT DISTINCT user_id\nFROM users",
                        rewritten_sql="SELECT user_id\nFROM users;",
                    ),
                ),
            ),
        ),
    )

    applied = apply_dbt_scan_patches(result)

    assert applied[0].applied is False
    assert "compiled SQL" in str(applied[0].reason)
    assert model.read_text() == "{{ ref('users') }}\n"


def test_apply_dbt_scan_patches_skips_compiled_result_without_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    compiled = project / "target" / "compiled" / "dbt_utils" / "models" / "users.sql"
    compiled.parent.mkdir(parents=True)
    compiled.write_text("SELECT DISTINCT user_id\nFROM users\n")
    result = DbtScanResult(
        project_path=project,
        model_count=1,
        results=(
            DbtModelScanResult(
                path=compiled,
                scanned_path=compiled,
                source_path=None,
                suggestions=(
                    RewriteSuggestion(
                        rule_name="remove_redundant_distinct",
                        status=VerificationStatus.PROVEN_EQUIVALENT,
                        original_sql="SELECT DISTINCT user_id\nFROM users",
                        rewritten_sql="SELECT user_id\nFROM users;",
                    ),
                ),
            ),
        ),
    )

    applied = apply_dbt_scan_patches(result)

    assert applied[0].applied is False
    assert applied[0].reason == "No matching source model file."
    assert compiled.read_text() == "SELECT DISTINCT user_id\nFROM users\n"
