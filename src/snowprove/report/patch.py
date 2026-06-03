from pathlib import Path

from pydantic import BaseModel, ConfigDict

from snowprove.dbt.scan import DbtScanResult
from snowprove.report.diff import render_rewrite_diff
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


class PatchApplyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    rule_name: str
    applied: bool
    reason: str | None = None


def write_dbt_scan_patches(scan_result: DbtScanResult, output_dir: Path) -> tuple[Path, ...]:
    written = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for result in scan_result.results:
        for suggestion in result.suggestions:
            diff = render_rewrite_diff(result.display_path(), suggestion)
            if diff is None:
                continue

            patch_path = output_dir / _patch_filename(
                scan_result.project_path,
                result.display_path(),
                suggestion.rule_name,
            )
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_text(diff)
            written.append(patch_path)

    return tuple(written)


def apply_dbt_scan_patches(scan_result: DbtScanResult) -> tuple[PatchApplyResult, ...]:
    results = []

    for result in scan_result.results:
        suggestion = _first_proven_rewrite(result.suggestions)
        if suggestion is None:
            continue

        path = result.display_path()
        if result.scanned_from_source():
            results.append(
                PatchApplyResult(
                    path=path,
                    rule_name=suggestion.rule_name,
                    applied=False,
                    reason="Scanned compiled SQL; source file was not verified directly.",
                )
            )
            continue

        if suggestion.rewritten_sql is None:
            continue

        current_sql = path.read_text()
        if current_sql.strip() != suggestion.original_sql.strip():
            results.append(
                PatchApplyResult(
                    path=path,
                    rule_name=suggestion.rule_name,
                    applied=False,
                    reason="Source file no longer matches the verified original SQL.",
                )
            )
            continue

        path.write_text(f"{suggestion.rewritten_sql.strip()}\n")
        results.append(
            PatchApplyResult(
                path=path,
                rule_name=suggestion.rule_name,
                applied=True,
            )
        )

    return tuple(results)


def _patch_filename(project_path: Path, model_path: Path, rule_name: str) -> Path:
    try:
        relative = model_path.relative_to(project_path)
    except ValueError:
        relative = Path(*model_path.parts[1:]) if model_path.is_absolute() else model_path

    return relative.with_name(f"{relative.name}.{rule_name}.patch")


def _first_proven_rewrite(
    suggestions: tuple[RewriteSuggestion, ...],
) -> RewriteSuggestion | None:
    for suggestion in suggestions:
        if (
            suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
            and suggestion.rewritten_sql is not None
        ):
            return suggestion
    return None
