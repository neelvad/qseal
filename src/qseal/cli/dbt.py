import json
from pathlib import Path

import click
from rich.console import Console

from qseal.cli.types import (
    DialectChoice,
    FailOn,
    OutputFormat,
    RuleChoice,
    ScanFormat,
)
from qseal.dbt.git_diff import GitDiffError, changed_model_paths
from qseal.dbt.intake import build_dbt_intake_report
from qseal.dbt.project import (
    DbtProjectDiscoveryError,
    discover_compiled_sql_path,
    discover_dbt_project,
)
from qseal.dbt.scan import _load_project_constraints, scan_dbt_project
from qseal.dialects import DEFAULT_DIALECT
from qseal.report.json import (
    render_dbt_intake_json,
    render_dbt_scan_json,
)
from qseal.report.markdown import render_dbt_scan_markdown
from qseal.report.patch import apply_dbt_scan_patches, write_dbt_scan_patch_results
from qseal.report.text import (
    render_dbt_intake_report,
    render_dbt_scan_diff_report,
    render_dbt_scan_report,
)
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.registry import (
    select_rules,
)
from qseal.verifier.backends.verieql import VeriEqlBackend

console = Console()

@click.group(name="dbt")
def dbt_group() -> None:
    """dbt project workflows."""


@dbt_group.command(name="scan")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show unknown and unsupported scan results in addition to proven rewrites.",
)
@click.option(
    "--chain",
    "use_chain",
    is_flag=True,
    help="Repeatedly apply verified rewrites per model until a fixed point is reached.",
)
@click.option(
    "--max-steps",
    "max_chain_steps",
    type=click.IntRange(min=1),
    default=8,
    show_default=True,
    help="Maximum verified rewrite steps per model when --chain is enabled.",
)
@click.option(
    "--rule",
    "selected_rules",
    multiple=True,
    type=RuleChoice,
    help="Only run a specific rewrite rule. Can be passed more than once.",
)
@click.option(
    "--format",
    "output_format",
    type=ScanFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--diff",
    "show_diff",
    is_flag=True,
    help="Print unified diffs for proven rewrites instead of the normal scan report.",
)
@click.option(
    "--fail-on",
    type=FailOn,
    default="none",
    show_default=True,
    help="Exit nonzero only for the selected proven-result policy.",
)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write a versioned JSON scan artifact to this file.",
)
@click.option(
    "--compiled-dir",
    "compiled_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing compiled dbt SQL files to scan instead of models/ SQL.",
)
@click.option(
    "--write-patches",
    "patch_dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Write unified diff patch files for proven rewrites to this directory.",
)
@click.option(
    "--apply-patches",
    is_flag=True,
    help="Apply proven rewrites directly to model SQL files.",
)
@click.option(
    "--use-compiled",
    is_flag=True,
    help="Auto-discover and scan compiled SQL under target/compiled/.",
)
@click.option(
    "--changed-since",
    "changed_since",
    metavar="GIT_REF",
    help="Scan only model SQL files changed versus this git ref (for CI).",
)
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used to parse model SQL.",
)
def dbt_scan(
    project_path: Path,
    show_all: bool,
    use_chain: bool,
    max_chain_steps: int,
    selected_rules: tuple[str, ...],
    output_format: str,
    show_diff: bool,
    fail_on: str,
    report_file: Path | None,
    compiled_path: Path | None,
    patch_dir: Path | None,
    apply_patches: bool,
    use_compiled: bool,
    changed_since: str | None,
    dialect: str,
) -> None:
    """Scan dbt model SQL files for verified rewrite opportunities."""
    if show_diff and output_format != "text":
        raise click.ClickException("--diff is only supported with --format text.")
    if patch_dir is not None and output_format != "text":
        raise click.ClickException("--write-patches is only supported with --format text.")
    if apply_patches and output_format != "text":
        raise click.ClickException("--apply-patches is only supported with --format text.")
    if apply_patches and show_all:
        raise click.ClickException("--apply-patches cannot be used with --all.")
    if apply_patches and patch_dir is not None:
        raise click.ClickException("--apply-patches and --write-patches cannot be used together.")
    if compiled_path is not None and use_compiled:
        raise click.ClickException("--compiled-dir and --use-compiled cannot be used together.")
    if changed_since is not None and (use_compiled or compiled_path is not None):
        raise click.ClickException("--changed-since scans source models, not compiled SQL.")
    if use_chain and show_diff:
        raise click.ClickException("--chain cannot be used with --diff yet.")
    if use_chain and patch_dir is not None:
        raise click.ClickException("--chain cannot be used with --write-patches yet.")
    if use_chain and apply_patches:
        raise click.ClickException("--chain cannot be used with --apply-patches yet.")

    only_paths: set[Path] | None = None
    if changed_since is not None:
        try:
            only_paths = changed_model_paths(project_path, changed_since)
        except GitDiffError as error:
            raise click.ClickException(str(error)) from error

    try:
        if use_compiled:
            compiled_path = discover_compiled_sql_path(project_path)
        result = scan_dbt_project(
            project_path,
            rules=select_rules(selected_rules),
            include_all=show_all,
            compiled_path=compiled_path,
            dialect=dialect,
            only_paths=only_paths,
            chain=use_chain,
            max_chain_steps=max_chain_steps,
        )
    except DbtProjectDiscoveryError as error:
        raise click.ClickException(str(error)) from error

    patch_results = ()
    if patch_dir is not None:
        patch_results = write_dbt_scan_patch_results(result, patch_dir)

    json_report = render_dbt_scan_json(result, patch_results=patch_results)

    if output_format == "json":
        click.echo(json_report)
    elif output_format == "markdown":
        click.echo(render_dbt_scan_markdown(result))
    elif show_diff:
        click.echo(render_dbt_scan_diff_report(result))
    else:
        console.print(render_dbt_scan_report(result))

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(f"{json_report}\n")
        click.echo(f"Report file written: {report_file}", err=True)

    if patch_dir is not None:
        console.print(f"Patch files written: {len(patch_results)}")
        for patch in patch_results:
            console.print(f"  {patch.path}")

    if apply_patches:
        applied = apply_dbt_scan_patches(result)
        applied_count = sum(1 for item in applied if item.applied)
        skipped = tuple(item for item in applied if not item.applied)
        console.print(f"Patches applied: {applied_count}")
        for item in applied:
            if item.applied:
                console.print(f"  {item.path} ({item.rule_name})")
            else:
                console.print(f"  skipped {item.path} ({item.rule_name}): {item.reason}")
        if skipped:
            raise click.ClickException("Some proven rewrites could not be applied.")

    if fail_on == "findings" and result.has_proven_findings():
        raise click.exceptions.Exit(1)


@dbt_group.command(name="intake")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--chain",
    "use_chain",
    is_flag=True,
    help="Repeatedly apply verified rewrites per model until a fixed point is reached.",
)
@click.option(
    "--max-steps",
    "max_chain_steps",
    type=click.IntRange(min=1),
    default=8,
    show_default=True,
    help="Maximum verified rewrite steps per model when --chain is enabled.",
)
@click.option(
    "--rule",
    "selected_rules",
    multiple=True,
    type=RuleChoice,
    help="Only run a specific rewrite rule. Can be passed more than once.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the redacted JSON intake artifact to this file.",
)
@click.option(
    "--compiled-dir",
    "compiled_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing compiled dbt SQL files to scan instead of models/ SQL.",
)
@click.option(
    "--use-compiled",
    is_flag=True,
    help="Auto-discover and scan compiled SQL under target/compiled/.",
)
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used to parse model SQL.",
)
def dbt_intake(
    project_path: Path,
    use_chain: bool,
    max_chain_steps: int,
    selected_rules: tuple[str, ...],
    output_format: str,
    report_file: Path | None,
    compiled_path: Path | None,
    use_compiled: bool,
    dialect: str,
) -> None:
    """Generate a privacy-preserving aggregate dbt scan report."""
    if compiled_path is not None and use_compiled:
        raise click.ClickException("--compiled-dir and --use-compiled cannot be used together.")

    rules = select_rules(selected_rules)
    try:
        if use_compiled:
            compiled_path = discover_compiled_sql_path(project_path)
        scan = scan_dbt_project(
            project_path,
            rules=rules,
            include_all=True,
            compiled_path=compiled_path,
            dialect=dialect,
            chain=use_chain,
            max_chain_steps=max_chain_steps,
        )
    except DbtProjectDiscoveryError as error:
        raise click.ClickException(str(error)) from error

    intake = build_dbt_intake_report(
        scan,
        rules=rules,
        include_all=True,
        compiled_sql=compiled_path is not None,
        use_compiled_auto=use_compiled,
        chain=use_chain,
        max_chain_steps=max_chain_steps,
    )
    json_report = render_dbt_intake_json(intake)

    if output_format == "json":
        click.echo(json_report)
    else:
        console.print(render_dbt_intake_report(intake))

    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(f"{json_report}\n")
        click.echo(f"Intake report file written: {report_file}", err=True)


@dbt_group.command(name="crosscheck")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--verieql-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to a local VeriEQL checkout with a prepared .venv.",
)
@click.option(
    "--verieql-python",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Python interpreter for the VeriEQL checkout. Defaults to its .venv.",
)
@click.option(
    "--bound",
    type=click.IntRange(min=1),
    default=2,
    show_default=True,
    help="Maximum rows per table in the counterexample search.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    default=120,
    show_default=True,
    help="Refuter timeout in seconds per finding.",
)
@click.option(
    "--compiled-dir",
    "compiled_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Scan already-compiled dbt SQL from this directory.",
)
@click.option(
    "--use-compiled",
    is_flag=True,
    help="Auto-discover a single compiled SQL directory under target/compiled.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used to parse, verify, and report.",
)
def dbt_crosscheck(
    project_path: Path,
    verieql_dir: Path,
    verieql_python: Path | None,
    bound: int,
    timeout_seconds: int,
    compiled_path: Path | None,
    use_compiled: bool,
    output_format: str,
    dialect: str,
) -> None:
    """Cross-check proven scan findings against the VeriEQL refuter.

    Exits nonzero when any proven finding is refuted, which indicates a
    soundness bug in QuerySeal or an untrue trusted constraint.
    """
    if compiled_path is not None and use_compiled:
        raise click.ClickException("--compiled-dir and --use-compiled cannot be used together.")

    try:
        if use_compiled:
            compiled_path = discover_compiled_sql_path(project_path)
        scan = scan_dbt_project(
            project_path,
            rules=select_rules(None),
            compiled_path=compiled_path,
            dialect=dialect,
        )
        project = discover_dbt_project(project_path, compiled_path=compiled_path)
    except DbtProjectDiscoveryError as error:
        raise click.ClickException(str(error)) from error

    constraints = _load_project_constraints(project.schema_yml_files)
    backend = VeriEqlBackend(
        verieql_dir=verieql_dir,
        python_path=verieql_python,
        bound=bound,
        timeout_seconds=timeout_seconds,
    )

    rows = []
    for model in scan.results:
        for suggestion in model.suggestions:
            if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
                continue
            if suggestion.rewritten_sql is None:
                continue
            # Fragment findings are proven at the fragment level; cross-check
            # the pair that was proven rather than the spliced full query.
            original = suggestion.fragment_original_sql or suggestion.original_sql
            rewritten = suggestion.fragment_rewritten_sql or suggestion.rewritten_sql
            verdict = backend.refute(original, rewritten, constraints, dialect=dialect)
            rows.append(
                {
                    "model_path": str(model.display_path()),
                    "rule_name": suggestion.rule_name,
                    "fragment_location": suggestion.fragment_location,
                    "refuter_status": verdict.status.value,
                    "refuter_reason": verdict.reason,
                    "counterexample": verdict.counterexample,
                }
            )

    refuted = [row for row in rows if row["refuter_status"] == "NOT_EQUIVALENT"]
    payload = {
        "artifact_type": "dbt_crosscheck",
        "schema_version": 1,
        "dialect": dialect,
        "proven_finding_count": len(rows),
        "refuted_count": len(refuted),
        "results": rows,
    }

    if output_format == "json":
        click.echo(json.dumps(payload, indent=2))
    else:
        console.print(f"Proven findings cross-checked: {len(rows)}")
        for row in rows:
            console.print(
                f"  {row['refuter_status']:>14}  {row['model_path']} ({row['rule_name']})"
            )
            if row["refuter_status"] == "NOT_EQUIVALENT":
                console.print(f"    {row['refuter_reason']}")
        console.print(f"Refuted: {len(refuted)}")

    if refuted:
        raise click.exceptions.Exit(1)
