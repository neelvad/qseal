from rich.text import Text

from qseal.benchmark.model import BenchmarkResult, BenchmarkStatus
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

    for result in scan_result.results:
        output.append("\n")
        output.append(f"{result.display_path()}\n", style="bold")
        if result.scanned_from_source():
            output.append(f"  Scanned SQL: {result.scanned_path}\n")
        if result.has_proven_findings():
            output.append(f"  Apply ready: {'yes' if result.apply_ready() else 'no'}\n")
            if result.apply_blocker():
                output.append(f"  Apply blocker: {result.apply_blocker()}\n")
        for suggestion in result.suggestions:
            output.append(f"  Result: {suggestion.status.value}\n")
            output.append(f"  Rewrite: {suggestion.rule_name}\n")
            if suggestion.reason:
                output.append(f"  Reason: {suggestion.reason}\n")
            if suggestion.assumptions:
                output.append("  Guarding assumptions:\n")
                for assumption in suggestion.assumptions:
                    output.append(f"    - {assumption}\n")
                tests = required_guarding_tests(suggestion)
                if tests:
                    output.append("  Required ongoing tests:\n")
                    for test in tests:
                        output.append(f"    - {test}\n")
            if suggestion.rewritten_sql:
                output.append("  Rewritten SQL:\n")
                for line in suggestion.rewritten_sql.splitlines():
                    output.append(f"    {line}\n")

    return output


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
