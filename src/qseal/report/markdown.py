"""GitHub-comment-friendly markdown rendering of dbt scan findings."""

from pathlib import Path

from qseal.report.diff import render_rewrite_diff
from qseal.report.guards import required_guarding_tests
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus

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
        rows = _scan_section_rows(scan_result, section)
        if not rows:
            continue
        lines.extend(["", f"### {title} ({len(rows)})"])
        for result, suggestion in rows:
            relative = _relative_path(result.display_path(), scan_result.project_path)
            if suggestion is None:
                lines.extend(_render_chain_finding(result, relative))
            else:
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


def _scan_chain_section(result) -> str:
    return "apply_ready" if result.apply_ready() else "manual_review"


def _scan_section_rows(scan_result, section: str):
    rows = []
    for result in scan_result.results:
        if result.rewrite_chain is not None and result.rewrite_chain.step_count > 0:
            if _scan_chain_section(result) == section:
                rows.append((result, None))
        rows.extend(
            (result, suggestion)
            for suggestion in result.suggestions
            if _scan_section(result, suggestion) == section
        )
    return rows


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


def _render_chain_finding(result, relative: Path) -> list[str]:
    chain = result.rewrite_chain
    if chain is None:
        return []
    apply_ready = result.apply_ready()
    if apply_ready:
        apply_state = "yes"
    else:
        apply_state = f"no ({result.apply_blocker() or 'unknown'})"
    lines = [
        "",
        f"#### `{relative}`",
        "",
        f"- **Rewrite chain:** {chain.step_count} verified {_step_word(chain.step_count)}",
        "- **Safety:** PROVEN_EQUIVALENT",
        f"- **Apply ready:** {apply_state}",
        f"- **Chain status:** {chain.status}",
        f"- **Recommendation:** {_chain_recommendation(result)}",
        "- **Steps:**",
    ]
    for step in chain.steps:
        suggestion = step.suggestion
        lines.append(f"  - `{step.step_index}. {suggestion.rule_name}`")
        if suggestion.fragment_location:
            lines.append(f"    - Fragment: `{suggestion.fragment_location}`")
        tests = required_guarding_tests(suggestion)
        if tests:
            lines.append("    - Stays valid while these dbt tests pass:")
            lines.extend(f"      - {test}" for test in tests)
        if suggestion.reason:
            lines.append(f"    - Reason: {suggestion.reason}")
    if chain.reason:
        lines.append(f"- **Fixed point:** {chain.reason}")

    diff = render_rewrite_diff(
        relative,
        RewriteSuggestion(
            rule_name="rewrite_chain",
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=chain.original_sql,
            rewritten_sql=chain.final_sql,
        ),
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


def _chain_recommendation(result) -> str:
    if result.apply_ready():
        return "Review the final diff; safe to apply while required tests pass."
    return "Review manually; the source file is not directly apply-ready."


def _step_word(count: int) -> str:
    return "step" if count == 1 else "steps"
