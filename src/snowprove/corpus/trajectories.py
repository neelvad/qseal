from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from snowprove.corpus.model import LoadedTaskCorpus
from snowprove.corpus.runner import CorpusRunReport, StrategyRunResult
from snowprove.environment import EnvironmentTask, RewriteEnvironment
from snowprove.rewrites.registry import select_rules
from snowprove.search import SearchResult, SearchStep


class CorpusTrajectoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["corpus_trajectory_step"] = "corpus_trajectory_step"
    corpus_id: str
    corpus_version: str
    corpus_fingerprint: str
    task_id: str
    task_fingerprint: str
    fixture_id: str
    tags: tuple[str, ...]
    strategy: str
    step_index: int
    state_sql: str
    available_action_ids: tuple[str, ...]
    action_id: str
    proposed_sql: str
    next_sql: str
    reward: float
    cumulative_reward: float
    suffix_reward: float
    verification_status: str
    timing_confident: bool | None
    speedup: float | None
    terminated: bool
    truncated: bool
    state_oracle_best_action_id: str | None
    state_oracle_best_suffix_reward: float | None
    is_state_oracle_best_action: bool | None
    task_oracle_strategy: str | None
    task_oracle_cumulative_reward: float | None
    task_oracle_action_ids: tuple[str, ...]
    task_oracle_action_id_at_step: str | None
    is_task_oracle_step: bool | None


class CorpusTrajectoryExport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["corpus_trajectory_export"] = "corpus_trajectory_export"
    corpus_id: str
    corpus_version: str
    corpus_fingerprint: str
    source_report: str | None = None
    output_path: str
    record_count: int
    task_count: int
    state_count: int
    labeled_state_count: int
    task_oracle_count: int
    strategy_count: int


def export_corpus_trajectories(
    report: CorpusRunReport,
    corpus: LoadedTaskCorpus,
    output_path: Path,
    *,
    source_report: str | None = None,
) -> CorpusTrajectoryExport:
    _validate_report_matches_corpus(report, corpus)
    task_lookup = {task.definition.task_id: task for task in corpus.tasks}
    task_oracles = {
        task.task_id: _best_completed_result(task.results)
        for task in report.tasks
    }
    state_labels = _state_oracle_labels(report)
    available_actions = _available_actions_by_state(report, corpus)

    record_count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as handle:
        for task_run in report.tasks:
            task = task_lookup[task_run.task_id]
            task_oracle = task_oracles[task_run.task_id]
            for result in task_run.results:
                if result.status != "COMPLETED" or result.search_result is None:
                    continue
                for step in result.search_result.steps:
                    label = state_labels.get((task_run.task_id, step.state_sql))
                    record = _record(
                        report,
                        task_run.task_id,
                        task.fingerprint,
                        task.fixture.fixture_id,
                        task.definition.tags,
                        result.search_result,
                        step,
                        available_actions.get((task_run.task_id, step.state_sql), ()),
                        label,
                        task_oracle,
                    )
                    handle.write(record.model_dump_json())
                    handle.write("\n")
                    record_count += 1

    return CorpusTrajectoryExport(
        corpus_id=report.corpus_id,
        corpus_version=report.corpus_version,
        corpus_fingerprint=report.corpus_fingerprint,
        source_report=source_report,
        output_path=str(output_path),
        record_count=record_count,
        task_count=len(report.tasks),
        state_count=len(available_actions),
        labeled_state_count=len(state_labels),
        task_oracle_count=sum(oracle is not None for oracle in task_oracles.values()),
        strategy_count=len(report.config.strategies),
    )


def render_corpus_trajectory_export(export: CorpusTrajectoryExport) -> str:
    return "\n".join(
        [
            f"Corpus: {export.corpus_id} v{export.corpus_version}",
            f"Trajectory records: {export.record_count}",
            f"Tasks: {export.task_count}",
            f"States with available actions: {export.state_count}",
            f"States with oracle labels: {export.labeled_state_count}",
            f"Tasks with oracle paths: {export.task_oracle_count}",
            f"Output: {export.output_path}",
        ]
    )


def _validate_report_matches_corpus(
    report: CorpusRunReport,
    corpus: LoadedTaskCorpus,
) -> None:
    if report.corpus_id != corpus.manifest.corpus_id:
        raise ValueError(
            f"Report corpus_id {report.corpus_id!r} does not match manifest "
            f"{corpus.manifest.corpus_id!r}."
        )
    if report.corpus_version != corpus.manifest.corpus_version:
        raise ValueError(
            f"Report corpus_version {report.corpus_version!r} does not match "
            f"manifest {corpus.manifest.corpus_version!r}."
        )
    if report.corpus_fingerprint != corpus.fingerprint:
        raise ValueError("Report corpus_fingerprint does not match manifest.")

    known_task_ids = {task.definition.task_id for task in corpus.tasks}
    missing = sorted(
        task.task_id for task in report.tasks if task.task_id not in known_task_ids
    )
    if missing:
        raise ValueError(f"Report references unknown corpus tasks: {', '.join(missing)}.")


def _best_completed_result(
    results: tuple[StrategyRunResult, ...],
) -> SearchResult | None:
    completed = [
        result.search_result
        for result in results
        if result.status == "COMPLETED" and result.search_result is not None
    ]
    if not completed:
        return None
    return sorted(
        completed,
        key=lambda result: (
            -result.cumulative_reward,
            len(result.steps),
            result.strategy,
        ),
    )[0]


def _state_oracle_labels(
    report: CorpusRunReport,
) -> dict[tuple[str, str], tuple[str, float]]:
    candidates: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for task_run in report.tasks:
        for result in task_run.results:
            if result.status != "COMPLETED" or result.search_result is None:
                continue
            for step in result.search_result.steps:
                key = (task_run.task_id, step.state_sql)
                suffix_reward = _suffix_reward(result.search_result, step)
                previous = candidates[key].get(step.action_id)
                if previous is None or suffix_reward > previous:
                    candidates[key][step.action_id] = suffix_reward

    labels = {}
    for key, action_rewards in candidates.items():
        action_id, suffix_reward = sorted(
            action_rewards.items(),
            key=lambda item: (-item[1], item[0]),
        )[0]
        labels[key] = (action_id, suffix_reward)
    return labels


def _available_actions_by_state(
    report: CorpusRunReport,
    corpus: LoadedTaskCorpus,
) -> dict[tuple[str, str], tuple[str, ...]]:
    task_lookup = {task.definition.task_id: task for task in corpus.tasks}
    states = {
        (task_run.task_id, step.state_sql)
        for task_run in report.tasks
        for result in task_run.results
        if result.status == "COMPLETED" and result.search_result is not None
        for step in result.search_result.steps
    }

    available = {}
    for task_id, state_sql in states:
        task = task_lookup[task_id]
        environment = RewriteEnvironment(
            rules=select_rules(task.definition.enabled_rules),
        )
        state_task = EnvironmentTask(
            task_id=task.environment_task.task_id,
            sql=state_sql,
            constraints=task.environment_task.constraints,
            dialect=task.environment_task.dialect,
            max_steps=task.environment_task.max_steps,
            metadata=task.environment_task.metadata,
        )
        observation = environment.reset(state_task)
        available[(task_id, state_sql)] = tuple(
            action.action_id for action in observation.actions
        )
    return available


def _record(
    report: CorpusRunReport,
    task_id: str,
    task_fingerprint: str,
    fixture_id: str,
    tags: tuple[str, ...],
    result: SearchResult,
    step: SearchStep,
    available_action_ids: tuple[str, ...],
    state_label: tuple[str, float] | None,
    task_oracle: SearchResult | None,
) -> CorpusTrajectoryRecord:
    state_best_action_id = state_label[0] if state_label is not None else None
    state_best_suffix_reward = state_label[1] if state_label is not None else None
    task_action_ids = task_oracle.action_ids if task_oracle is not None else ()
    task_action_at_step = (
        task_action_ids[step.step_index]
        if step.step_index < len(task_action_ids)
        else None
    )
    return CorpusTrajectoryRecord(
        corpus_id=report.corpus_id,
        corpus_version=report.corpus_version,
        corpus_fingerprint=report.corpus_fingerprint,
        task_id=task_id,
        task_fingerprint=task_fingerprint,
        fixture_id=fixture_id,
        tags=tags,
        strategy=result.strategy,
        step_index=step.step_index,
        state_sql=step.state_sql,
        available_action_ids=available_action_ids,
        action_id=step.action_id,
        proposed_sql=step.proposed_sql,
        next_sql=step.next_sql,
        reward=step.reward,
        cumulative_reward=step.cumulative_reward,
        suffix_reward=_suffix_reward(result, step),
        verification_status=step.verification_status,
        timing_confident=step.timing_confident,
        speedup=step.speedup,
        terminated=step.terminated,
        truncated=step.truncated,
        state_oracle_best_action_id=state_best_action_id,
        state_oracle_best_suffix_reward=state_best_suffix_reward,
        is_state_oracle_best_action=(
            None if state_best_action_id is None else step.action_id == state_best_action_id
        ),
        task_oracle_strategy=task_oracle.strategy if task_oracle is not None else None,
        task_oracle_cumulative_reward=(
            task_oracle.cumulative_reward if task_oracle is not None else None
        ),
        task_oracle_action_ids=task_action_ids,
        task_oracle_action_id_at_step=task_action_at_step,
        is_task_oracle_step=(
            None
            if task_oracle is None or task_action_at_step is None
            else step.state_sql == _state_sql_at_step(task_oracle, step.step_index)
            and step.action_id == task_action_at_step
        ),
    )


def _suffix_reward(result: SearchResult, step: SearchStep) -> float:
    previous_cumulative = step.cumulative_reward - step.reward
    return result.cumulative_reward - previous_cumulative


def _state_sql_at_step(result: SearchResult, step_index: int) -> str | None:
    if step_index >= len(result.steps):
        return None
    return result.steps[step_index].state_sql


def load_corpus_trajectory_records(path: Path) -> tuple[CorpusTrajectoryRecord, ...]:
    records = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(CorpusTrajectoryRecord.model_validate(json.loads(line)))
    return tuple(records)
