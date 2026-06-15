"""GitHub-comment-friendly markdown rendering of dbt scan findings."""

from pathlib import Path

from snowprove.report.diff import render_rewrite_diff
from snowprove.report.guards import required_guarding_tests
from snowprove.rewrites.base import VerificationStatus

# A stable marker so a CI bot can find and update its own comment idempotently.
COMMENT_MARKER = "<!-- snowprove-scan -->"


def _relative_path(path: Path, project_path: Path) -> Path:
    try:
        return path.resolve().relative_to(project_path.resolve())
    except ValueError:
        return path


def render_dbt_scan_markdown(scan_result) -> str:
    findings = scan_result.proven_finding_count()
    lines = [COMMENT_MARKER, "## Snowprove: verified-safe rewrites", ""]

    if findings == 0:
        lines.append(
            f"No proven rewrites in {scan_result.model_count} scanned model"
            f"{'s' if scan_result.model_count != 1 else ''}."
        )
        return "\n".join(lines) + "\n"

    model_count = len({result.display_path() for result in scan_result.results
                       if result.has_proven_findings()})
    lines.append(
        f"Found **{findings}** proven-equivalent rewrite"
        f"{'s' if findings != 1 else ''} across **{model_count}** model"
        f"{'s' if model_count != 1 else ''} "
        f"(scanned {scan_result.model_count})."
    )
    lines.append("")
    lines.append(
        "Each rewrite returns the same rows under the listed dbt-test "
        "assumptions. No performance claim is made."
    )

    for result in scan_result.results:
        if not result.has_proven_findings():
            continue
        relative = _relative_path(result.display_path(), scan_result.project_path)
        for suggestion in result.suggestions:
            if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
                continue
            lines.extend(_render_finding(result, suggestion, relative))

    return "\n".join(lines) + "\n"


def _render_finding(result, suggestion, relative: Path) -> list[str]:
    apply_state = "yes" if result.apply_ready() else f"no ({result.apply_blocker()})"
    lines = [
        "",
        f"### `{relative}`",
        "",
        f"- **Rewrite:** `{suggestion.rule_name}`",
        f"- **Apply ready:** {apply_state}",
    ]
    tests = required_guarding_tests(suggestion)
    if tests:
        lines.append("- **Stays valid while these dbt tests pass:**")
        lines.extend(f"  - {test}" for test in tests)

    diff = render_rewrite_diff(relative, suggestion)
    if diff:
        lines.extend(["", "```diff", diff.rstrip("\n"), "```"])
    return lines
