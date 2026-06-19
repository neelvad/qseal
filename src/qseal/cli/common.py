from pathlib import Path

import click
from rich.console import Console

from qseal.constraints.loader import load_constraint_catalog
from qseal.policy import (
    PolicyDataFilter,
)
from qseal.report.json import (
    render_verification_json,
)
from qseal.report.text import (
    render_verification_report,
)
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus
from qseal.verifier.backends import get_verifier_backend
from qseal.verifier.model import VerificationResult

console = Console()

def _print_verification(result: VerificationResult, output_format: str, fail_on: str) -> None:
    if output_format == "json":
        click.echo(render_verification_json(result))
    else:
        console.print(render_verification_report(result))

    if fail_on == "unproven" and result.status != VerificationStatus.PROVEN_EQUIVALENT:
        raise click.exceptions.Exit(1)


def _verification_inputs(
    original_path: Path,
    rewritten_path: Path,
    schema_path: Path,
    schema_format: str,
    dialect: str,
) -> dict[str, str]:
    return {
        "original_path": str(original_path),
        "rewritten_path": str(rewritten_path),
        "schema_path": str(schema_path),
        "schema_format": schema_format,
        "dialect": dialect,
    }


def _load_constraints(path: Path, schema_format: str):
    return load_constraint_catalog(path, schema_format)


def _verify_candidates(
    original_path: Path,
    original_sql: str,
    candidate_paths: list[Path],
    schema_path: Path,
    schema_format: str,
    constraints,
    *,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
    dialect: str,
) -> list[VerificationResult]:
    backend = get_verifier_backend(
        verifier,
        solver_command=solver_command,
        timeout_seconds=timeout_seconds,
    )
    return [
        backend.verify(
            original_sql,
            candidate_path.read_text(),
            constraints,
            dialect=dialect,
        ).model_copy(
            update={
                "inputs": _verification_inputs(
                    original_path,
                    candidate_path,
                    schema_path,
                    schema_format,
                    dialect,
                )
            }
        )
        for candidate_path in candidate_paths
    ]


def _resolve_candidate_paths(
    candidate_paths: tuple[Path, ...],
    candidates_dir: Path | None,
) -> list[Path]:
    if candidate_paths and candidates_dir is not None:
        raise click.ClickException("Pass candidate paths or --candidates-dir, not both.")
    if candidates_dir is not None:
        paths = sorted(candidates_dir.glob("*.sql"))
        if not paths:
            raise click.ClickException(f"No .sql candidate files found in {candidates_dir}.")
        return paths
    if not candidate_paths:
        raise click.ClickException("Pass at least one candidate path or --candidates-dir.")
    return list(candidate_paths)


def _write_candidate_suggestions(
    suggestions: list[RewriteSuggestion],
    output_dir: Path,
    *,
    include_all: bool,
    force: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for index, suggestion in enumerate(_candidate_suggestions(suggestions, include_all), start=1):
        if suggestion.rewritten_sql is None:
            skipped.append(
                {
                    "rule_name": suggestion.rule_name,
                    "status": suggestion.status.value,
                    "reason": suggestion.reason or "No rewritten SQL was produced.",
                }
            )
            continue

        candidate_path = output_dir / f"{index:03d}_{_safe_filename(suggestion.rule_name)}.sql"
        if candidate_path.exists() and not force:
            raise click.ClickException(
                f"Candidate file already exists: {candidate_path}. Use --force to overwrite."
            )

        candidate_path.write_text(f"{suggestion.rewritten_sql.strip()}\n")
        generated.append(
            {
                "path": str(candidate_path),
                "rule_name": suggestion.rule_name,
                "status": suggestion.status.value,
            }
        )

    return generated, skipped


def _candidate_generation_payload(
    query_path: Path,
    output_dir: Path,
    generated: list[dict[str, str]],
    skipped: list[dict[str, str]],
    dialect: str,
) -> dict[str, object]:
    return {
        "original_path": str(query_path),
        "output_dir": str(output_dir),
        "dialect": dialect,
        "generated_count": len(generated),
        "skipped_count": len(skipped),
        "generated": generated,
        "skipped": skipped,
    }


def _select_policy_holdout_tasks(corpus, data_filter: PolicyDataFilter) -> tuple[str, ...]:
    selected = []
    for task in corpus.tasks:
        tags = set(task.definition.tags)
        if data_filter.include_tasks and task.definition.task_id not in data_filter.include_tasks:
            continue
        if (
            data_filter.include_fixtures
            and task.fixture.fixture_id not in data_filter.include_fixtures
        ):
            continue
        if data_filter.include_tags and not tags.intersection(data_filter.include_tags):
            continue
        selected.append(task.definition.task_id)
    return tuple(selected)


def _unknown_preference_group_options(
    group_by: tuple[str, ...],
    raw_group_scales: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, ...], dict[str, float]]:
    if not raw_group_scales:
        return group_by, {}
    resolved_group_by = group_by or ("action_set", "table")
    group_scales = {}
    for group_key, raw_scale in raw_group_scales:
        try:
            scale = float(raw_scale)
        except ValueError as error:
            raise click.ClickException(
                f"Invalid unknown preference group scale {raw_scale!r}."
            ) from error
        if scale < 0:
            raise click.ClickException(
                f"Unknown preference group scale must be zero or greater: {raw_scale}."
            )
        group_scales[group_key] = scale
    return resolved_group_by, group_scales


def _strategy_wins(report) -> dict[str, int]:
    wins = {summary.strategy: 0 for summary in report.strategy_summaries}
    for task in report.tasks:
        completed = [
            result
            for result in task.results
            if result.status == "COMPLETED" and result.search_result is not None
        ]
        if not completed:
            continue
        best_reward = max(
            result.search_result.cumulative_reward for result in completed
        )
        for result in completed:
            if result.search_result.cumulative_reward == best_reward:
                wins[result.strategy] = wins.get(result.strategy, 0) + 1
    return wins


def _candidate_suggestions(
    suggestions: list[RewriteSuggestion],
    include_all: bool,
) -> list[RewriteSuggestion]:
    if include_all:
        return [
            suggestion
            for suggestion in suggestions
            if suggestion.status != VerificationStatus.NOT_APPLICABLE
        ]
    return [
        suggestion
        for suggestion in suggestions
        if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    ]


def _safe_filename(value: str) -> str:
    return "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in value
    )
