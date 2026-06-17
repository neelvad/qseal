"""GitHub-comment-friendly markdown rendering of dbt scan findings."""

from pathlib import Path

from qseal.report.diff import render_rewrite_diff
from qseal.report.guards import required_guarding_tests
from qseal.rewrites.base import VerificationStatus

# A stable marker so a CI bot can find and update its own comment idempotently.
COMMENT_MARKER = "<!-- qseal-scan -->"
LEGACY_COMMENT_MARKERS = ("<!-- snowprove-scan -->",)
COMMENT_MARKERS = (COMMENT_MARKER, *LEGACY_COMMENT_MARKERS)


def _relative_path(path: Path, project_path: Path) -> Path:
    try:
        return path.resolve().relative_to(project_path.resolve())
    except ValueError:
        return path


def render_dbt_scan_markdown(scan_result) -> str:
    findings = scan_result.proven_finding_count()
    lines = [COMMENT_MARKER, "## QuerySeal: verified-safe rewrites", ""]

    if findings == 0 and not scan_result.results:
        lines.append(
            f"No proven rewrites in {scan_result.model_count} scanned model"
            f"{'s' if scan_result.model_count != 1 else ''}."
        )
        return "\n".join(lines) + "\n"

    model_count = len({result.display_path() for result in scan_result.results
                       if result.has_proven_findings()})
    if findings:
        lines.append(
            f"Found **{findings}** proven-equivalent rewrite"
            f"{'s' if findings != 1 else ''} across **{model_count}** model"
            f"{'s' if model_count != 1 else ''} "
            f"(scanned {scan_result.model_count})."
        )
    else:
        lines.append(
            f"No proven rewrites in {scan_result.model_count} scanned model"
            f"{'s' if scan_result.model_count != 1 else ''}."
        )
    lines.append("")
    lines.append(
        "Proven rewrites return the same rows under the listed dbt-test "
        "assumptions. No performance claim is made."
    )

    for section, title in _scan_sections():
        rows = [
            (result, suggestion)
            for result in scan_result.results
            for suggestion in result.suggestions
            if _scan_section(result, suggestion) == section
        ]
        if not rows:
            continue
        lines.extend(["", f"### {title} ({len(rows)})"])
        for result, suggestion in rows:
            relative = _relative_path(result.display_path(), scan_result.project_path)
            lines.extend(_render_finding(result, suggestion, relative))

    return "\n".join(lines) + "\n"


def _scan_sections() -> tuple[tuple[str, str], ...]:
    return (
        ("apply_ready", "Safe and apply-ready"),
        ("manual_review", "Safe, manual review needed"),
        ("not_proven", "Rejected, unsupported, or informational"),
    )


def _scan_section(result, suggestion) -> str:
    if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT:
        return "apply_ready" if result.apply_ready() else "manual_review"
    return "not_proven"


def _render_finding(result, suggestion, relative: Path) -> list[str]:
    proven = suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    apply_ready = proven and result.apply_ready()
    if apply_ready:
        apply_state = "yes"
    else:
        apply_state = f"no ({_apply_blocker(result, suggestion)})"
    lines = [
        "",
        f"#### `{relative}`",
        "",
        f"- **Rewrite:** `{suggestion.rule_name}`",
        f"- **Safety:** {suggestion.status.value}",
        f"- **Apply ready:** {apply_state}",
        f"- **Recommendation:** {_recommendation(result, suggestion)}",
    ]
    tests = required_guarding_tests(suggestion)
    if tests:
        lines.append("- **Stays valid while these dbt tests pass:**")
        lines.extend(f"  - {test}" for test in tests)
    elif suggestion.assumptions:
        lines.append("- **Guarding assumptions:**")
        lines.extend(f"  - {assumption}" for assumption in suggestion.assumptions)
    if suggestion.reason:
        lines.append(f"- **Reason:** {suggestion.reason}")

    diff = (
        render_rewrite_diff(relative, suggestion)
        if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
        else None
    )
    if diff:
        lines.extend(["", "```diff", diff.rstrip("\n"), "```"])
    return lines


def _apply_blocker(result, suggestion) -> str:
    if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
        return "rewrite is not proven equivalent"
    return result.apply_blocker() or "unknown"


def _recommendation(result, suggestion) -> str:
    section = _scan_section(result, suggestion)
    if section == "apply_ready":
        return "Review the generated diff; safe to apply while required tests pass."
    if section == "manual_review":
        return "Review manually; the source file is not directly apply-ready."
    return "Do not apply automatically."
