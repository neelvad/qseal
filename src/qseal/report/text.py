from rich.text import Text

from qseal.benchmark.model import BenchmarkResult, BenchmarkStatus
from qseal.benchmark.snowflake_suite import SnowflakeFamilySuiteReport
from qseal.candidates.evidence import CandidateEvidenceReport
from qseal.fixtures.model import DuckDbFixtureManifest
from qseal.report.diff import render_rewrite_diff
from qseal.report.guards import required_guarding_tests
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus
from qseal.verifier.model import VerificationResult


def render_duckdb_benchmark_report(result: BenchmarkResult) -> Text:
    output = Text()
    output.append(f"{result.status.value}\n", style="bold")
    if result.status != BenchmarkStatus.COMPLETED:
        output.append(f"{result.reason or 'Benchmark failed.'}\n")
        return output

    output.append(
        f"Original median: {result.original.median_ms:.3f} ms\n"
        f"Rewritten median: {result.rewritten.median_ms:.3f} ms\n"
        f"Executions/sample: {result.original.executions_per_sample} / "
        f"{result.rewritten.executions_per_sample}\n"
        f"Speedup: {result.speedup:.3f}x\n"
        f"Rows: {result.original.row_count} / {result.rewritten.row_count}\n"
        f"Row counts match: {result.row_counts_match}\n"
        f"Timing confident: {result.timing_confident}\n"
    )
    if result.confidence_reason is not None:
        output.append(f"Confidence: {result.confidence_reason}\n")
    return output


def render_snowflake_benchmark_report(result: BenchmarkResult) -> Text:
    output = Text()
    output.append(f"{result.status.value}\n", style="bold")
    if result.status != BenchmarkStatus.COMPLETED:
        output.append(f"{result.reason or 'Benchmark failed.'}\n")
        return output

    output.append(
        f"Original median: {result.original.median_ms:.3f} ms\n"
        f"Rewritten median: {result.rewritten.median_ms:.3f} ms\n"
        f"Speedup: {result.speedup:.3f}x\n"
        f"Rows: {result.original.row_count} / {result.rewritten.row_count}\n"
        f"Row counts match: {result.row_counts_match}\n"
        f"Timing confident: {result.timing_confident}\n"
    )
    if result.original.query_ids or result.rewritten.query_ids:
        output.append(
            "Query IDs: "
            f"{', '.join(result.original.query_ids)} / "
            f"{', '.join(result.rewritten.query_ids)}\n"
        )
    if result.original.bytes_scanned or result.rewritten.bytes_scanned:
        output.append(
            "Bytes scanned: "
            f"{_sum_optional_ints(result.original.bytes_scanned)} / "
            f"{_sum_optional_ints(result.rewritten.bytes_scanned)}\n"
        )
    if result.confidence_reason is not None:
        output.append(f"Confidence: {result.confidence_reason}\n")
    return output


def render_snowflake_family_suite_report(result: SnowflakeFamilySuiteReport) -> Text:
    output = Text()
    output.append("Snowflake benchmark suite\n", style="bold")
    output.append(f"Suite: {result.suite_id}\n")
    output.append(f"Output: {result.output_dir}\n")
    output.append(
        f"Runs: {result.runs}; scales: {', '.join(str(scale) for scale in result.scales)}; "
        f"modes: {', '.join(result.modes)}; warmups/repetitions: "
        f"{result.warmups}/{result.repetitions}\n"
    )
    output.append(
        f"Completed: {result.completed_count}/{result.result_count}; "
        f"classifications: {_format_counts(result.classification_counts)}\n\n"
    )
    output.append(
        "case                     run class          wall speedup "
        "exec speedup bytes orig->rew\n",
        style="bold",
    )
    for summary in result.summaries:
        output.append(
            f"{summary.case_id:<24} "
            f"{summary.run_index:>3} "
            f"{summary.classification:<14} "
            f"{_format_ratio(summary.wall_speedup):>12} "
            f"{_format_ratio(summary.execution_speedup):>12} "
            f"{summary.original_bytes_scanned}->{summary.rewritten_bytes_scanned}\n"
        )
        for note in summary.notes:
            output.append(f"  note: {note}\n")
        if summary.reason:
            output.append(f"  reason: {summary.reason}\n")
        spec = _snowflake_suite_spec_for_summary(result, summary.case_id, summary.run_index)
        if spec is not None:
            for assumption in spec.trusted_assumptions:
                output.append(f"  trusted assumption: {assumption}\n")
            for note in spec.review_notes:
                output.append(f"  context: {note}\n")
    return output


def _snowflake_suite_spec_for_summary(
    result: SnowflakeFamilySuiteReport,
    case_id: str,
    run_index: int,
):
    for case_result in result.results:
        if case_result.spec.case_id == case_id and case_result.run_index == run_index:
            return case_result.spec
    return None


def render_candidate_evidence_report(report: CandidateEvidenceReport) -> Text:
    output = Text()
    output.append("Candidate evidence\n", style="bold")
    output.append(f"Candidates: {report.candidate_count}\n")
    output.append(f"Proven: {report.proven_count}\n")
    output.append(f"Benchmarked: {report.benchmarked_count}\n")
    output.append(
        f"Benchmark: {report.benchmark_engine} {report.benchmark_data}, "
        f"rows={report.rows}, warmups/repetitions={report.warmups}/{report.repetitions}\n"
    )
    if report.verification_counts:
        output.append(f"Verification: {_format_counts(report.verification_counts)}\n")
    if report.benchmark_outcomes:
        output.append(f"Benchmark outcomes: {_format_counts(report.benchmark_outcomes)}\n")
    output.append("\n")

    for section, title in _candidate_evidence_sections():
        rows = [row for row in report.results if row.review_section == section]
        output.append(f"{title} ({len(rows)})\n", style="bold")
        if not rows:
            output.append("  None\n")
            continue
        for row in rows:
            _append_candidate_evidence_row(output, row)
    return output


def _candidate_evidence_sections() -> tuple[tuple[str, str], ...]:
    return (
        ("safe_worth_considering", "Safe and worth considering"),
        ("safe_no_clear_speedup", "Safe, but no clear speedup"),
        ("needs_review", "Safe, but evidence needs review"),
        ("rejected_unproven", "Rejected or unproven"),
    )


def _append_candidate_evidence_row(output: Text, row) -> None:
    output.append(f"  {row.candidate_path}\n", style="bold")
    if row.candidate_metadata.get("description"):
        output.append(f"    {row.candidate_metadata['description']}\n")
    output.append(f"    Safety: {row.verification.status.value}\n")
    if row.verification.verification_method or row.verification.rule_name:
        output.append(
            "    Verification: "
            f"{row.verification.verification_method or 'unknown'}"
            f"{_format_rule(row.verification.rule_name)}\n"
        )
    if row.required_tests:
        output.append("    Required tests:\n")
        for required_test in row.required_tests:
            output.append(f"      - {required_test}\n")
    elif row.verification.assumptions:
        output.append("    Assumptions:\n")
        for assumption in row.verification.assumptions:
            output.append(f"      - {assumption}\n")
    if row.benchmark is None:
        output.append(f"    Benchmark: skipped ({row.benchmark_skip_reason})\n")
    else:
        output.append(
            "    Benchmark: "
            f"{row.benchmark.get('outcome', 'unknown')}"
            f"{_format_speedup(row.benchmark.get('speedup'))}"
            f"{_format_benchmark_medians(row.benchmark)}\n"
        )
        if row.benchmark.get("reason"):
            output.append(f"      reason: {row.benchmark['reason']}\n")
    if row.verification.reason:
        output.append(f"    Verification reason: {row.verification.reason}\n")
    output.append(f"    Recommendation: {_format_recommendation(row.recommendation)}\n")
    if row.review_diff:
        output.append("    Diff:\n")
        _append_indented_diff(output, row.review_diff, max_lines=40)


def _sum_optional_ints(values: tuple[int, ...]) -> int:
    return sum(values)


def _format_rule(rule_name: str | None) -> str:
    return "" if not rule_name else f" / {rule_name}"


def _format_speedup(speedup: object) -> str:
    if speedup is None:
        return ""
    return f", speedup={speedup}x"


def _format_benchmark_medians(benchmark: dict) -> str:
    original_ms = benchmark.get("original_ms")
    rewritten_ms = benchmark.get("rewritten_ms")
    if original_ms is None or rewritten_ms is None:
        return ""
    return f", median {original_ms:.3f} -> {rewritten_ms:.3f} ms"


def _format_recommendation(value: str) -> str:
    labels = {
        "consider_applying": "consider applying",
        "safe_but_no_clear_speedup": "safe, but no clear speedup",
        "safe_but_slower": "safe, but benchmarked slower",
        "safe_but_not_benchmarked": "safe, but not benchmarked",
        "recheck_benchmark_premises": "recheck benchmark premises",
        "safe_but_benchmark_failed": "safe, but benchmark failed",
        "do_not_apply_unproven": "do not apply; not proven",
    }
    return labels.get(value, value)


def _append_indented_diff(output: Text, diff: str, *, max_lines: int) -> None:
    lines = diff.splitlines()
    visible = lines[:max_lines]
    for line in visible:
        output.append(f"      {line}\n")
    if len(lines) > max_lines:
        output.append(f"      ... {len(lines) - max_lines} more diff lines\n")


def _indent_sql(sql: str, *, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" for line in sql.strip().splitlines())


def _step_word(count: int) -> str:
    return "step" if count == 1 else "steps"


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _format_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}x"


def render_duckdb_fixture_report(manifest: DuckDbFixtureManifest) -> Text:
    output = Text()
    output.append("DuckDB fixture created\n", style="bold")
    output.append(f"Database: {manifest.database_path}\n")
    output.append(f"Seed: {manifest.spec.seed}\n")
    for name, table in manifest.tables.items():
        output.append(f"{name}: {table.row_count} rows\n")
    return output


def render_suggestion_report(suggestion: RewriteSuggestion) -> Text:
    output = Text()
    style = _status_style(suggestion.status)

    output.append("Result: ", style="bold")
    output.append(f"{suggestion.status.value}\n", style=style)
    output.append("Rewrite: ", style="bold")
    output.append(f"{suggestion.rule_name}\n")

    if suggestion.assumptions:
        output.append("Assumptions:\n", style="bold")
        for assumption in suggestion.assumptions:
            output.append(f"  - {assumption}\n")
        tests = required_guarding_tests(suggestion)
        if tests:
            output.append("Required ongoing tests:\n", style="bold")
            for test in tests:
                output.append(f"  - {test}\n")

    if suggestion.reason:
        output.append("Reason: ", style="bold")
        output.append(f"{suggestion.reason}\n")

    if suggestion.rewritten_sql:
        output.append("Rewritten SQL:\n", style="bold")
        output.append(suggestion.rewritten_sql)
        output.append("\n")

    return output


def render_suggestions_report(suggestions: list[RewriteSuggestion]) -> Text:
    output = Text()
    visible = [
        suggestion
        for suggestion in suggestions
        if suggestion.status != VerificationStatus.NOT_APPLICABLE
    ]

    if not visible:
        output.append("Result: ", style="bold")
        output.append(f"{VerificationStatus.NOT_APPLICABLE.value}\n", style="yellow")
        output.append("Reason: ", style="bold")
        output.append("No rewrite rules apply to this query.\n")
        return output

    for index, suggestion in enumerate(visible):
        if index:
            output.append("\n")
        output.append(render_suggestion_report(suggestion))

    return output


def render_rewrite_chain_report(chain) -> Text:
    output = Text()
    output.append("Rewrite chain\n", style="bold")
    output.append(f"Status: {chain.status}\n")
    output.append(f"Steps: {chain.step_count}\n")
    if chain.reason:
        output.append(f"Reason: {chain.reason}\n")
    output.append("\n")

    for step in chain.steps:
        suggestion = step.suggestion
        output.append(
            f"Step {step.step_index}: {suggestion.rule_name} "
            f"({suggestion.status.value})\n",
            style="bold",
        )
        if suggestion.fragment_location:
            output.append(f"  Fragment: {suggestion.fragment_location}\n")
        tests = required_guarding_tests(suggestion)
        if tests:
            output.append("  Required tests:\n")
            for test in tests:
                output.append(f"    - {test}\n")
        if suggestion.reason:
            output.append(f"  Reason: {suggestion.reason}\n")
        if suggestion.rewritten_sql:
            output.append("  Rewritten SQL:\n")
            output.append(_indent_sql(suggestion.rewritten_sql, spaces=4))
            output.append("\n")

    output.append("Final SQL:\n", style="bold")
    output.append(_indent_sql(chain.final_sql, spaces=2))
    output.append("\n")
    return output


def render_verification_report(result: VerificationResult) -> Text:
    output = Text()

    output.append("Result: ", style="bold")
    output.append(f"{result.status.value}\n", style=_status_style(result.status))

    if result.rule_name:
        output.append("Verifier rule: ", style="bold")
        output.append(f"{result.rule_name}\n")
    if result.safety_claim:
        output.append("Safety claim: ", style="bold")
        output.append(f"{result.safety_claim}\n")
    if result.verification_method:
        output.append("Verification method: ", style="bold")
        output.append(f"{result.verification_method}\n")

    if result.assumptions:
        output.append("Assumptions:\n", style="bold")
        for assumption in result.assumptions:
            output.append(f"  - {assumption}\n")

    if result.reason:
        output.append("Reason: ", style="bold")
        output.append(f"{result.reason}\n")

    if result.counterexample:
        output.append("Counterexample:\n", style="bold")
        output.append(f"{result.counterexample}\n")

    return output


def render_candidate_verifications_report(results: list[VerificationResult]) -> Text:
    output = Text()
    output.append("Candidates checked: ", style="bold")
    output.append(f"{len(results)}\n")
    output.append("Proven: ", style="bold")
    output.append(
        f"{sum(result.status == VerificationStatus.PROVEN_EQUIVALENT for result in results)}\n"
    )

    for result in results:
        candidate_path = result.inputs.get("rewritten_path", "<candidate>")
        output.append("\n")
        output.append(f"{candidate_path}\n", style="bold")
        output.append("  Result: ")
        output.append(f"{result.status.value}\n", style=_status_style(result.status))
        if result.rule_name:
            output.append(f"  Verifier rule: {result.rule_name}\n")
        if result.safety_claim:
            output.append(f"  Safety claim: {result.safety_claim}\n")
        if result.verification_method:
            output.append(f"  Verification method: {result.verification_method}\n")
        if result.reason:
            output.append(f"  Reason: {result.reason}\n")
        if result.counterexample:
            output.append("  Counterexample:\n")
            output.append(f"    {result.counterexample}\n")

    return output


def render_dbt_scan_report(scan_result) -> Text:
    output = Text()
    output.append("Scanned models: ", style="bold")
    output.append(f"{scan_result.model_count}\n")
    output.append("Findings: ", style="bold")
    output.append(f"{scan_result.proven_finding_count()}\n")
    output.append("Visible results: ", style="bold")
    output.append(f"{len(scan_result.results)}\n")

    if scan_result.results:
        output.append("\nSummary:\n", style="bold")
        for status, count in scan_result.status_counts().items():
            output.append(f"  {status}: {count}\n")
        output.append("Rules:\n", style="bold")
        for rule_name, count in scan_result.rule_counts().items():
            output.append(f"  {rule_name}: {count}\n")
        if scan_result.reason_counts():
            output.append("Reasons:\n", style="bold")
            for reason, count in scan_result.reason_counts().items():
                output.append(f"  {count}x {reason}\n")

    if not scan_result.results:
        output.append("No rewrite findings.\n")
        return output

    output.append("\nReview sections:\n", style="bold")
    for section, title in _dbt_scan_sections():
        rows = _dbt_scan_section_rows(scan_result, section)
        output.append(f"{title} ({len(rows)})\n", style="bold")
        if not rows:
            output.append("  None\n")
            continue
        for result, suggestion in rows:
            if suggestion is None:
                _append_dbt_scan_chain_row(output, result)
            else:
                _append_dbt_scan_row(output, result, suggestion)

    return output


def _dbt_scan_sections() -> tuple[tuple[str, str], ...]:
    return (
        ("apply_ready", "Safe and apply-ready"),
        ("manual_review", "Safe, manual review needed"),
        ("not_proven", "Rejected, unsupported, or informational"),
    )


def _dbt_scan_section(result, suggestion: RewriteSuggestion) -> str:
    if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT:
        return "apply_ready" if result.apply_ready() else "manual_review"
    return "not_proven"


def _dbt_scan_chain_section(result) -> str:
    return "apply_ready" if result.apply_ready() else "manual_review"


def _dbt_scan_section_rows(scan_result, section: str):
    rows = []
    for result in scan_result.results:
        if result.rewrite_chain is not None and result.rewrite_chain.step_count > 0:
            if _dbt_scan_chain_section(result) == section:
                rows.append((result, None))
        rows.extend(
            (result, suggestion)
            for suggestion in result.suggestions
            if _dbt_scan_section(result, suggestion) == section
        )
    return rows


def _append_dbt_scan_chain_row(output: Text, result) -> None:
    chain = result.rewrite_chain
    if chain is None:
        return
    output.append(f"  {result.display_path()}\n", style="bold")
    if result.scanned_from_source():
        output.append(f"    Scanned SQL: {result.scanned_path}\n")
    output.append("    Safety: PROVEN_EQUIVALENT\n")
    output.append(
        f"    Rewrite chain: {chain.step_count} verified {_step_word(chain.step_count)}\n"
    )
    output.append(f"    Apply ready: {'yes' if result.apply_ready() else 'no'}\n")
    apply_blocker = result.apply_blocker()
    if apply_blocker:
        output.append(f"    Apply blocker: {apply_blocker}\n")
    if chain.reason:
        output.append(f"    Chain status: {chain.status} ({chain.reason})\n")
    else:
        output.append(f"    Chain status: {chain.status}\n")
    output.append("    Steps:\n")
    for step in chain.steps:
        suggestion = step.suggestion
        output.append(f"      {step.step_index}. {suggestion.rule_name}\n")
        if suggestion.fragment_location:
            output.append(f"         Fragment: {suggestion.fragment_location}\n")
        tests = required_guarding_tests(suggestion)
        if tests:
            output.append("         Required tests:\n")
            for test in tests:
                output.append(f"           - {test}\n")
        if suggestion.reason:
            output.append(f"         Reason: {suggestion.reason}\n")
    output.append(f"    Recommendation: {_dbt_scan_chain_recommendation(result)}\n")
    output.append("    Final SQL:\n")
    output.append(_indent_sql(chain.final_sql, spaces=6))
    output.append("\n")
    diff = render_rewrite_diff(
        result.display_path(),
        RewriteSuggestion(
            rule_name="rewrite_chain",
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=chain.original_sql,
            rewritten_sql=chain.final_sql,
        ),
    )
    if diff:
        output.append("    Final diff:\n")
        _append_indented_diff(output, diff, max_lines=80)


def _append_dbt_scan_row(output: Text, result, suggestion: RewriteSuggestion) -> None:
    output.append(f"  {result.display_path()}\n", style="bold")
    if result.scanned_from_source():
        output.append(f"    Scanned SQL: {result.scanned_path}\n")
    output.append(f"    Safety: {suggestion.status.value}\n")
    output.append(f"    Rewrite: {suggestion.rule_name}\n")
    apply_ready = (
        suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
        and result.apply_ready()
    )
    output.append(f"    Apply ready: {'yes' if apply_ready else 'no'}\n")
    apply_blocker = _dbt_scan_apply_blocker(result, suggestion)
    if apply_blocker:
        output.append(f"    Apply blocker: {apply_blocker}\n")
    tests = required_guarding_tests(suggestion)
    if tests:
        output.append("    Required tests:\n")
        for test in tests:
            output.append(f"      - {test}\n")
    elif suggestion.assumptions:
        output.append("    Guarding assumptions:\n")
        for assumption in suggestion.assumptions:
            output.append(f"      - {assumption}\n")
    if suggestion.reason:
        output.append(f"    Reason: {suggestion.reason}\n")
    output.append(
        f"    Recommendation: {_dbt_scan_recommendation(result, suggestion)}\n"
    )
    diff = (
        render_rewrite_diff(result.display_path(), suggestion)
        if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
        else None
    )
    if diff:
        output.append("    Diff:\n")
        _append_indented_diff(output, diff, max_lines=60)


def _dbt_scan_apply_blocker(result, suggestion: RewriteSuggestion) -> str | None:
    if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
        return "Rewrite is not proven equivalent."
    return result.apply_blocker()


def _dbt_scan_recommendation(result, suggestion: RewriteSuggestion) -> str:
    section = _dbt_scan_section(result, suggestion)
    if section == "apply_ready":
        return "review generated diff; safe to apply while required tests pass"
    if section == "manual_review":
        return "review manually; source file is not directly apply-ready"
    return "do not apply automatically"


def _dbt_scan_chain_recommendation(result) -> str:
    if result.apply_ready():
        return "review final diff; safe to apply final SQL while all required tests pass"
    return "review chain manually; source file is not directly apply-ready"


def render_dbt_scan_diff_report(scan_result) -> str:
    output = []
    diff_count = 0

    for result in scan_result.results:
        for suggestion in result.suggestions:
            diff = render_rewrite_diff(result.display_path(), suggestion)
            if diff is None:
                continue
            if diff_count:
                output.append("")
            output.append(diff)
            diff_count += 1

    if diff_count == 0:
        return "No rewrite diffs.\n"

    return "\n".join(output)


def _status_style(status: VerificationStatus) -> str:
    if status == VerificationStatus.PROVEN_EQUIVALENT:
        return "green"
    if status == VerificationStatus.NOT_EQUIVALENT:
        return "red"
    return "yellow"
