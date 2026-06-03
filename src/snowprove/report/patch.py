from pathlib import Path

from snowprove.dbt.scan import DbtScanResult
from snowprove.report.diff import render_rewrite_diff


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


def _patch_filename(project_path: Path, model_path: Path, rule_name: str) -> Path:
    try:
        relative = model_path.relative_to(project_path)
    except ValueError:
        relative = Path(*model_path.parts[1:]) if model_path.is_absolute() else model_path

    return relative.with_name(f"{relative.name}.{rule_name}.patch")
