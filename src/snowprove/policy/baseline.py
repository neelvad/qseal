from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from snowprove.corpus.trajectories import (
    CorpusTrajectoryRecord,
    load_corpus_trajectory_records,
)


class PolicyDataFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    include_tasks: tuple[str, ...] = Field(default_factory=tuple)
    exclude_tasks: tuple[str, ...] = Field(default_factory=tuple)
    include_fixtures: tuple[str, ...] = Field(default_factory=tuple)
    exclude_fixtures: tuple[str, ...] = Field(default_factory=tuple)
    include_tags: tuple[str, ...] = Field(default_factory=tuple)
    exclude_tags: tuple[str, ...] = Field(default_factory=tuple)


class FeatureStat(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    appearances: int = Field(ge=0)
    oracle_count: int = Field(ge=0)
    win_rate: float


class PolicyActionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    step_index: int = Field(ge=0)
    available_action_ids: tuple[str, ...] = Field(default_factory=tuple)


class BaselinePolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["baseline_policy_model"] = "baseline_policy_model"
    model_type: Literal["feature_mean_action_ranker"] = "feature_mean_action_ranker"
    generated_at: datetime
    source_trajectories: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    state_count: int
    labeled_state_count: int
    feature_stats: tuple[FeatureStat, ...]
    default_score: float


class RuleAccuracy(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_name: str
    state_count: int
    correct_count: int
    acceptable_count: int = 0
    accuracy: float
    adjusted_accuracy: float | None = None


class BaselinePolicyEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["baseline_policy_evaluation"] = "baseline_policy_evaluation"
    model_type: str
    source_trajectories: str | None = None
    model_path: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    state_count: int
    labeled_state_count: int
    predicted_state_count: int
    correct_count: int
    acceptable_count: int = 0
    accuracy: float | None
    adjusted_accuracy: float | None = None
    reward_margin: float = Field(default=0.0, ge=0)
    known_reward_gap_count: int
    mean_known_reward_gap: float | None
    max_known_reward_gap: float | None
    per_oracle_rule: tuple[RuleAccuracy, ...]


class PolicyHoldoutEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["policy_holdout_evaluation"] = "policy_holdout_evaluation"
    generated_at: datetime
    source_trajectories: str
    train_filter: PolicyDataFilter
    holdout_filter: PolicyDataFilter
    trained_state_count: int
    heldout_state_count: int
    offline_evaluation: BaselinePolicyEvaluation
    corpus_report_path: str
    heldout_task_ids: tuple[str, ...]
    strategy_rewards: dict[str, float | None]
    strategy_wins: dict[str, int]
    strategy_benchmark_requests: dict[str, int]
    strategy_verifier_requests: dict[str, int]


@dataclass(frozen=True)
class _StateExample:
    task_id: str
    state_sql: str
    fixture_id: str
    tags: tuple[str, ...]
    step_index: int
    available_action_ids: tuple[str, ...]
    oracle_action_id: str | None
    oracle_suffix_reward: float | None
    observed_suffix_rewards: dict[str, float]


def train_baseline_policy(
    trajectory_path: Path,
    *,
    source_trajectories: str | None = None,
    data_filter: PolicyDataFilter | None = None,
) -> BaselinePolicyModel:
    data_filter = data_filter or PolicyDataFilter()
    records = load_corpus_trajectory_records(trajectory_path)
    examples = _filter_examples(_state_examples(records), data_filter)
    labeled = [example for example in examples if example.oracle_action_id is not None]
    feature_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for example in labeled:
        assert example.oracle_action_id is not None
        for action_id in example.available_action_ids:
            is_oracle = action_id == example.oracle_action_id
            for feature in _features(example, action_id):
                feature_counts[feature][0] += 1
                feature_counts[feature][1] += int(is_oracle)

    stats = tuple(
        FeatureStat(
            feature=feature,
            appearances=counts[0],
            oracle_count=counts[1],
            win_rate=counts[1] / counts[0] if counts[0] else 0.0,
        )
        for feature, counts in sorted(feature_counts.items())
    )
    total_appearances = sum(counts[0] for counts in feature_counts.values())
    total_oracle = sum(counts[1] for counts in feature_counts.values())
    return BaselinePolicyModel(
        generated_at=datetime.now(UTC),
        source_trajectories=source_trajectories,
        data_filter=data_filter,
        state_count=len(examples),
        labeled_state_count=len(labeled),
        feature_stats=stats,
        default_score=total_oracle / total_appearances if total_appearances else 0.0,
    )


def evaluate_baseline_policy(
    trajectory_path: Path,
    model: BaselinePolicyModel,
    *,
    source_trajectories: str | None = None,
    model_path: str | None = None,
    data_filter: PolicyDataFilter | None = None,
    reward_margin: float = 0.0,
) -> BaselinePolicyEvaluation:
    if reward_margin < 0:
        raise ValueError("reward_margin must be zero or greater.")
    data_filter = data_filter or PolicyDataFilter()
    examples = [
        example
        for example in _filter_examples(
            _state_examples(load_corpus_trajectory_records(trajectory_path)),
            data_filter,
        )
        if example.oracle_action_id is not None
    ]
    scores = {stat.feature: stat.win_rate for stat in model.feature_stats}
    correct = 0
    acceptable = 0
    predicted = 0
    known_gaps = []
    by_rule: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])

    for example in examples:
        prediction = _predict(example, scores, model.default_score)
        if prediction is None:
            continue
        predicted += 1
        is_correct = prediction == example.oracle_action_id
        correct += int(is_correct)
        rule_name = _rule_name(example.oracle_action_id or "")
        by_rule[rule_name][0] += 1
        by_rule[rule_name][1] += int(is_correct)

        oracle_reward = example.observed_suffix_rewards.get(example.oracle_action_id or "")
        predicted_reward = example.observed_suffix_rewards.get(prediction)
        is_acceptable = is_correct
        if oracle_reward is not None and predicted_reward is not None:
            reward_gap = oracle_reward - predicted_reward
            known_gaps.append(reward_gap)
            is_acceptable = reward_gap <= reward_margin
        acceptable += int(is_acceptable)
        by_rule[rule_name][2] += int(is_acceptable)

    return BaselinePolicyEvaluation(
        model_type=model.model_type,
        source_trajectories=source_trajectories,
        model_path=model_path,
        data_filter=data_filter,
        state_count=len(examples),
        labeled_state_count=len(examples),
        predicted_state_count=predicted,
        correct_count=correct,
        acceptable_count=acceptable,
        accuracy=correct / predicted if predicted else None,
        adjusted_accuracy=acceptable / predicted if predicted else None,
        reward_margin=reward_margin,
        known_reward_gap_count=len(known_gaps),
        mean_known_reward_gap=(
            sum(known_gaps) / len(known_gaps) if known_gaps else None
        ),
        max_known_reward_gap=max(known_gaps) if known_gaps else None,
        per_oracle_rule=tuple(
            RuleAccuracy(
                rule_name=rule_name,
                state_count=counts[0],
                correct_count=counts[1],
                acceptable_count=counts[2],
                accuracy=counts[1] / counts[0] if counts[0] else 0.0,
                adjusted_accuracy=counts[2] / counts[0] if counts[0] else None,
            )
            for rule_name, counts in sorted(by_rule.items())
        ),
    )


def score_baseline_action(
    model: BaselinePolicyModel,
    context: PolicyActionContext,
    action_id: str,
) -> float:
    scores = {stat.feature: stat.win_rate for stat in model.feature_stats}
    values = [
        scores[feature]
        for feature in _feature_values(
            fixture_id=context.fixture_id,
            tags=context.tags,
            step_index=context.step_index,
            action_id=action_id,
        )
        if feature in scores
    ]
    if not values:
        return model.default_score
    return sum(values) / len(values)


def write_baseline_policy(model: BaselinePolicyModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2))


def load_baseline_policy(path: Path) -> BaselinePolicyModel:
    return BaselinePolicyModel.model_validate_json(path.read_text())


def render_baseline_policy_training(model: BaselinePolicyModel) -> str:
    return "\n".join(
        [
            f"Model: {model.model_type}",
            f"States: {model.state_count}",
            f"Labeled states: {model.labeled_state_count}",
            f"Feature stats: {len(model.feature_stats)}",
            f"Default score: {model.default_score:.6f}",
            f"Filter: {_render_filter(model.data_filter)}",
        ]
    )


def render_baseline_policy_evaluation(evaluation: BaselinePolicyEvaluation) -> str:
    accuracy = "n/a" if evaluation.accuracy is None else f"{evaluation.accuracy:.4f}"
    adjusted_accuracy = (
        "n/a"
        if evaluation.adjusted_accuracy is None
        else f"{evaluation.adjusted_accuracy:.4f}"
    )
    mean_gap = (
        "n/a"
        if evaluation.mean_known_reward_gap is None
        else f"{evaluation.mean_known_reward_gap:.6f}"
    )
    lines = [
        f"Model: {evaluation.model_type}",
        f"States: {evaluation.state_count}",
        f"Predicted states: {evaluation.predicted_state_count}",
        f"Top-1 accuracy: {accuracy}",
        f"Adjusted accuracy: {adjusted_accuracy}",
        f"Reward margin: {evaluation.reward_margin:.6f}",
        f"Known reward gaps: {evaluation.known_reward_gap_count}",
        f"Mean known reward gap: {mean_gap}",
        f"Filter: {_render_filter(evaluation.data_filter)}",
    ]
    if evaluation.per_oracle_rule:
        lines.append("")
        lines.append("Per oracle rule:")
        for rule in evaluation.per_oracle_rule:
            adjusted = (
                "n/a"
                if rule.adjusted_accuracy is None
                else f"{rule.adjusted_accuracy:.4f}"
            )
            lines.append(
                f"  {rule.rule_name}: {rule.correct_count}/{rule.state_count} "
                f"({rule.accuracy:.4f}), adjusted={rule.acceptable_count}/"
                f"{rule.state_count} ({adjusted})"
            )
    return "\n".join(lines)


def render_policy_holdout_evaluation(evaluation: PolicyHoldoutEvaluation) -> str:
    lines = [
        "Policy holdout evaluation",
        f"Train states: {evaluation.trained_state_count}",
        f"Held-out states: {evaluation.heldout_state_count}",
        f"Held-out tasks: {len(evaluation.heldout_task_ids)}",
        f"Corpus report: {evaluation.corpus_report_path}",
        "",
        "Strategy comparison:",
    ]
    for strategy, reward in evaluation.strategy_rewards.items():
        rendered_reward = "n/a" if reward is None else f"{reward:.6f}"
        lines.append(
            f"  {strategy}: reward={rendered_reward}, "
            f"wins={evaluation.strategy_wins.get(strategy, 0)}, "
            f"vreq={evaluation.strategy_verifier_requests.get(strategy, 0)}, "
            f"breq={evaluation.strategy_benchmark_requests.get(strategy, 0)}"
        )
    lines.append("")
    lines.append("Offline label evaluation:")
    lines.append(render_baseline_policy_evaluation(evaluation.offline_evaluation))
    return "\n".join(lines)


def _state_examples(
    records: tuple[CorpusTrajectoryRecord, ...],
) -> tuple[_StateExample, ...]:
    grouped: dict[tuple[str, str], list[CorpusTrajectoryRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.task_id, record.state_sql)].append(record)

    examples = []
    for (task_id, state_sql), state_records in sorted(grouped.items()):
        first = state_records[0]
        rewards: dict[str, float] = {}
        for record in state_records:
            existing = rewards.get(record.action_id)
            if existing is None or record.suffix_reward > existing:
                rewards[record.action_id] = record.suffix_reward
        examples.append(
            _StateExample(
                task_id=task_id,
                state_sql=state_sql,
                fixture_id=first.fixture_id,
                tags=first.tags,
                step_index=first.step_index,
                available_action_ids=first.available_action_ids,
                oracle_action_id=first.state_oracle_best_action_id,
                oracle_suffix_reward=first.state_oracle_best_suffix_reward,
                observed_suffix_rewards=rewards,
            )
        )
    return tuple(examples)


def _filter_examples(
    examples: tuple[_StateExample, ...],
    data_filter: PolicyDataFilter,
) -> tuple[_StateExample, ...]:
    return tuple(
        example
        for example in examples
        if _matches_filter(example, data_filter)
    )


def _matches_filter(example: _StateExample, data_filter: PolicyDataFilter) -> bool:
    tags = set(example.tags)
    if data_filter.include_tasks and example.task_id not in data_filter.include_tasks:
        return False
    if example.task_id in data_filter.exclude_tasks:
        return False
    if (
        data_filter.include_fixtures
        and example.fixture_id not in data_filter.include_fixtures
    ):
        return False
    if example.fixture_id in data_filter.exclude_fixtures:
        return False
    if data_filter.include_tags and not tags.intersection(data_filter.include_tags):
        return False
    return not tags.intersection(data_filter.exclude_tags)


def _predict(
    example: _StateExample,
    scores: dict[str, float],
    default_score: float,
) -> str | None:
    if not example.available_action_ids:
        return None
    return sorted(
        example.available_action_ids,
        key=lambda action_id: (
            -_score(example, action_id, scores, default_score),
            action_id,
        ),
    )[0]


def _score(
    example: _StateExample,
    action_id: str,
    scores: dict[str, float],
    default_score: float,
) -> float:
    values = [
        scores[feature]
        for feature in _features(example, action_id)
        if feature in scores
    ]
    if not values:
        return default_score
    return sum(values) / len(values)


def _features(example: _StateExample, action_id: str) -> tuple[str, ...]:
    return _feature_values(
        fixture_id=example.fixture_id,
        tags=example.tags,
        step_index=example.step_index,
        action_id=action_id,
    )


def _feature_values(
    *,
    fixture_id: str,
    tags: tuple[str, ...],
    step_index: int,
    action_id: str,
) -> tuple[str, ...]:
    rule_name = _rule_name(action_id)
    return (
        f"action:{action_id}",
        f"rule:{rule_name}",
        f"fixture_action:{fixture_id}:{action_id}",
        f"step_action:{step_index}:{action_id}",
        *(f"tag_action:{tag}:{action_id}" for tag in tags),
    )


def _rule_name(action_id: str) -> str:
    return action_id.split("::", 1)[0]


def _render_filter(data_filter: PolicyDataFilter) -> str:
    parts = []
    for field_name in (
        "include_tasks",
        "exclude_tasks",
        "include_fixtures",
        "exclude_fixtures",
        "include_tags",
        "exclude_tags",
    ):
        values = getattr(data_filter, field_name)
        if values:
            parts.append(f"{field_name}={','.join(values)}")
    return "; ".join(parts) if parts else "none"


def load_baseline_policy_evaluation(path: Path) -> BaselinePolicyEvaluation:
    return BaselinePolicyEvaluation.model_validate(json.loads(path.read_text()))
