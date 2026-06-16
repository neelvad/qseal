from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from qseal.corpus.trajectories import (
    CorpusTrajectoryRecord,
    load_corpus_trajectory_records,
)
from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.ir.model import Predicate, SelectQuery
from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select


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


class FeatureWeight(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    weight: float


class PolicyActionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    step_index: int = Field(ge=0)
    available_action_ids: tuple[str, ...] = Field(default_factory=tuple)
    state_sql: str | None = None
    dialect: SqlDialect = DEFAULT_DIALECT


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


class LinearPolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["linear_policy_model"] = "linear_policy_model"
    model_type: Literal["linear_action_ranker"] = "linear_action_ranker"
    generated_at: datetime
    source_trajectories: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    state_count: int
    labeled_state_count: int
    choice_state_count: int
    epochs: int = Field(ge=1)
    learning_rate: float = Field(gt=0)
    training_margin: float = Field(default=0.0, ge=0)
    unknown_preference_scale: float = Field(default=1.0, ge=0)
    unknown_preference_group_by: tuple[str, ...] = Field(default_factory=tuple)
    unknown_preference_group_scales: dict[str, float] = Field(default_factory=dict)
    update_count: int = Field(ge=0)
    skipped_preference_count: int = Field(default=0, ge=0)
    skipped_unknown_preference_count: int = Field(default=0, ge=0)
    feature_weights: tuple[FeatureWeight, ...]
    default_score: float = 0.0


type PolicyModel = BaselinePolicyModel | LinearPolicyModel


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


class BaselinePolicyInspectionRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    fixture_id: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    step_index: int = Field(ge=0)
    state_sql: str
    available_action_ids: tuple[str, ...]
    oracle_action_id: str
    predicted_action_id: str
    correct: bool
    acceptable: bool
    reward_gap: float | None
    oracle_suffix_reward: float | None
    predicted_suffix_reward: float | None
    action_scores: dict[str, float]


class BaselinePolicyInspection(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["baseline_policy_inspection"] = "baseline_policy_inspection"
    model_type: str
    source_trajectories: str | None = None
    model_path: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    reward_margin: float = Field(default=0.0, ge=0)
    state_count: int
    predicted_state_count: int
    row_count: int
    miss_count: int
    unacceptable_count: int
    rows: tuple[BaselinePolicyInspectionRow, ...]


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


class PolicyHoldoutComparisonRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    path: str
    model_type: str
    trained_state_count: int
    heldout_state_count: int
    exact_accuracy: float | None
    adjusted_accuracy: float | None
    greedy_reward: float | None
    policy_reward: float | None
    reward_delta_vs_greedy: float | None
    greedy_wins: int | None
    policy_wins: int | None
    win_delta_vs_greedy: int | None
    greedy_oracle_requests: int | None
    policy_oracle_requests: int | None
    oracle_request_delta_vs_greedy: int | None


class PolicyHoldoutComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["policy_holdout_comparison"] = "policy_holdout_comparison"
    baseline_label: str
    rows: tuple[PolicyHoldoutComparisonRow, ...]


class PolicyPreferenceExample(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    fixture_id: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    state_sql: str
    available_action_ids: tuple[str, ...]
    preferred_action_id: str
    alternative_action_id: str
    reward_gap: float | None


class PolicyPreferenceGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_key: str
    coverage_status: Literal["matched", "train_only", "holdout_only"]
    train_count: int
    holdout_count: int
    train_preferences: dict[str, int]
    holdout_preferences: dict[str, int]
    train_majority_preference: str | None
    holdout_majority_preference: str | None
    train_majority_ratio: float | None
    holdout_majority_ratio: float | None
    disagreement_count: int
    mean_train_reward_gap: float | None
    mean_holdout_reward_gap: float | None
    examples: tuple[PolicyPreferenceExample, ...] = Field(default_factory=tuple)


class PolicyLabelInspection(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["policy_label_inspection"] = "policy_label_inspection"
    source_trajectories: str | None = None
    train_filter: PolicyDataFilter
    holdout_filter: PolicyDataFilter
    group_by: tuple[str, ...]
    reward_margin: float = Field(ge=0)
    train_preference_count: int
    holdout_preference_count: int
    train_preferences: dict[str, int]
    holdout_preferences: dict[str, int]
    group_count: int
    disagreement_group_count: int
    train_only_group_count: int
    holdout_only_group_count: int
    groups: tuple[PolicyPreferenceGroup, ...]


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
        if len(example.available_action_ids) < 2:
            continue
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


def train_linear_policy(
    trajectory_path: Path,
    *,
    source_trajectories: str | None = None,
    data_filter: PolicyDataFilter | None = None,
    epochs: int = 20,
    learning_rate: float = 1.0,
    training_margin: float = 0.0,
    unknown_preference_scale: float = 1.0,
    unknown_preference_group_by: tuple[str, ...] = (),
    unknown_preference_group_scales: dict[str, float] | None = None,
) -> LinearPolicyModel:
    if epochs < 1:
        raise ValueError("epochs must be one or greater.")
    if learning_rate <= 0:
        raise ValueError("learning_rate must be greater than zero.")
    if training_margin < 0:
        raise ValueError("training_margin must be zero or greater.")
    if unknown_preference_scale < 0:
        raise ValueError("unknown_preference_scale must be zero or greater.")
    unknown_preference_group_scales = unknown_preference_group_scales or {}
    for group_key, group_scale in unknown_preference_group_scales.items():
        if group_scale < 0:
            raise ValueError(
                f"Unknown preference scale for group {group_key!r} "
                "must be zero or greater."
            )
    if unknown_preference_group_scales and not unknown_preference_group_by:
        unknown_preference_group_by = ("action_set", "table")

    data_filter = data_filter or PolicyDataFilter()
    records = load_corpus_trajectory_records(trajectory_path)
    examples = _filter_examples(_state_examples(records), data_filter)
    labeled = [example for example in examples if example.oracle_action_id is not None]
    choice_examples = [
        example for example in labeled if len(example.available_action_ids) >= 2
    ]
    weights: dict[str, float] = {}
    update_count = 0
    skipped_preference_count = 0
    skipped_unknown_preference_count = 0

    for _ in range(epochs):
        for example in choice_examples:
            assert example.oracle_action_id is not None
            non_oracle_actions = tuple(
                action_id for action_id in example.available_action_ids
                if action_id != example.oracle_action_id
            )
            if not non_oracle_actions:
                continue
            reward_span = _reward_span(example)
            for action_id in non_oracle_actions:
                reward_gap = _known_reward_gap(example, action_id)
                if reward_gap == float("inf"):
                    scale = _unknown_preference_scale(
                        example,
                        action_id,
                        group_by=unknown_preference_group_by,
                        group_scales=unknown_preference_group_scales,
                        default_scale=unknown_preference_scale,
                    )
                    if scale == 0:
                        skipped_unknown_preference_count += 1
                        continue
                elif reward_gap < training_margin:
                    skipped_preference_count += 1
                    continue
                else:
                    scale = _preference_scale(example, action_id, reward_span)
                for feature in _features(example, example.oracle_action_id):
                    weights[feature] = weights.get(feature, 0.0) + learning_rate * scale
                for feature in _features(example, action_id):
                    weights[feature] = weights.get(feature, 0.0) - learning_rate * scale
                update_count += 1

    return LinearPolicyModel(
        generated_at=datetime.now(UTC),
        source_trajectories=source_trajectories,
        data_filter=data_filter,
        state_count=len(examples),
        labeled_state_count=len(labeled),
        choice_state_count=len(choice_examples),
        epochs=epochs,
        learning_rate=learning_rate,
        training_margin=training_margin,
        unknown_preference_scale=unknown_preference_scale,
        unknown_preference_group_by=unknown_preference_group_by,
        unknown_preference_group_scales=dict(sorted(unknown_preference_group_scales.items())),
        update_count=update_count,
        skipped_preference_count=skipped_preference_count,
        skipped_unknown_preference_count=skipped_unknown_preference_count,
        feature_weights=tuple(
            FeatureWeight(feature=feature, weight=weight)
            for feature, weight in sorted(weights.items())
            if weight != 0
        ),
    )


def evaluate_baseline_policy(
    trajectory_path: Path,
    model: PolicyModel,
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
    correct = 0
    acceptable = 0
    predicted = 0
    known_gaps = []
    by_rule: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])

    for example in examples:
        prediction = _predict_policy(example, model)
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


def inspect_baseline_policy(
    trajectory_path: Path,
    model: PolicyModel,
    *,
    source_trajectories: str | None = None,
    model_path: str | None = None,
    data_filter: PolicyDataFilter | None = None,
    reward_margin: float = 0.0,
    mode: Literal["misses", "unacceptable", "all"] = "misses",
) -> BaselinePolicyInspection:
    if reward_margin < 0:
        raise ValueError("reward_margin must be zero or greater.")
    if mode not in ("misses", "unacceptable", "all"):
        raise ValueError(f"Unknown inspection mode: {mode}.")

    data_filter = data_filter or PolicyDataFilter()
    examples = [
        example
        for example in _filter_examples(
            _state_examples(load_corpus_trajectory_records(trajectory_path)),
            data_filter,
        )
        if example.oracle_action_id is not None
    ]
    rows = []
    predicted = 0
    miss_count = 0
    unacceptable_count = 0

    for example in examples:
        prediction = _predict_policy(example, model)
        if prediction is None:
            continue
        predicted += 1
        assert example.oracle_action_id is not None
        correct = prediction == example.oracle_action_id
        miss_count += int(not correct)

        oracle_reward = example.observed_suffix_rewards.get(example.oracle_action_id)
        predicted_reward = example.observed_suffix_rewards.get(prediction)
        reward_gap = None
        acceptable = correct
        if oracle_reward is not None and predicted_reward is not None:
            reward_gap = oracle_reward - predicted_reward
            acceptable = reward_gap <= reward_margin
        unacceptable_count += int(not acceptable)

        if mode == "misses" and correct:
            continue
        if mode == "unacceptable" and acceptable:
            continue

        rows.append(
            BaselinePolicyInspectionRow(
                task_id=example.task_id,
                fixture_id=example.fixture_id,
                tags=example.tags,
                step_index=example.step_index,
                state_sql=example.state_sql,
                available_action_ids=example.available_action_ids,
                oracle_action_id=example.oracle_action_id,
                predicted_action_id=prediction,
                correct=correct,
                acceptable=acceptable,
                reward_gap=reward_gap,
                oracle_suffix_reward=oracle_reward,
                predicted_suffix_reward=predicted_reward,
                action_scores={
                    action_id: _score_policy(example, action_id, model)
                    for action_id in example.available_action_ids
                },
            )
        )

    return BaselinePolicyInspection(
        model_type=model.model_type,
        source_trajectories=source_trajectories,
        model_path=model_path,
        data_filter=data_filter,
        reward_margin=reward_margin,
        state_count=len(examples),
        predicted_state_count=predicted,
        row_count=len(rows),
        miss_count=miss_count,
        unacceptable_count=unacceptable_count,
        rows=tuple(sorted(rows, key=_inspection_sort_key)),
    )


def inspect_policy_labels(
    trajectory_path: Path,
    *,
    source_trajectories: str | None = None,
    train_filter: PolicyDataFilter | None = None,
    holdout_filter: PolicyDataFilter | None = None,
    group_by: tuple[str, ...] = ("action_set", "table"),
    reward_margin: float = 0.0,
    examples_per_group: int = 3,
) -> PolicyLabelInspection:
    if reward_margin < 0:
        raise ValueError("reward_margin must be zero or greater.")
    if examples_per_group < 0:
        raise ValueError("examples_per_group must be zero or greater.")
    train_filter = train_filter or PolicyDataFilter()
    holdout_filter = holdout_filter or PolicyDataFilter()
    examples = _state_examples(load_corpus_trajectory_records(trajectory_path))
    train_preferences = _preference_examples(
        _filter_examples(examples, train_filter),
        reward_margin=reward_margin,
    )
    holdout_preferences = _preference_examples(
        _filter_examples(examples, holdout_filter),
        reward_margin=reward_margin,
    )
    group_lookup: dict[str, dict[str, list[PolicyPreferenceExample]]] = defaultdict(
        lambda: {"train": [], "holdout": []}
    )
    for preference in train_preferences:
        group_lookup[_preference_group_key(preference, group_by)]["train"].append(
            preference
        )
    for preference in holdout_preferences:
        group_lookup[_preference_group_key(preference, group_by)]["holdout"].append(
            preference
        )

    groups = []
    for group_key, split_preferences in group_lookup.items():
        train_items = split_preferences["train"]
        holdout_items = split_preferences["holdout"]
        train_counts = _preference_counts(train_items)
        holdout_counts = _preference_counts(holdout_items)
        disagreement_count = _preference_disagreement_count(train_counts, holdout_counts)
        groups.append(
            PolicyPreferenceGroup(
                group_key=group_key,
                coverage_status=_preference_coverage_status(
                    train_count=len(train_items),
                    holdout_count=len(holdout_items),
                ),
                train_count=len(train_items),
                holdout_count=len(holdout_items),
                train_preferences=train_counts,
                holdout_preferences=holdout_counts,
                train_majority_preference=_majority_preference(train_counts),
                holdout_majority_preference=_majority_preference(holdout_counts),
                train_majority_ratio=_majority_ratio(train_counts),
                holdout_majority_ratio=_majority_ratio(holdout_counts),
                disagreement_count=disagreement_count,
                mean_train_reward_gap=_mean_known_gap(train_items),
                mean_holdout_reward_gap=_mean_known_gap(holdout_items),
                examples=tuple(
                    sorted(
                        (*holdout_items, *train_items),
                        key=_preference_example_sort_key,
                    )[:examples_per_group]
                ),
            )
        )

    sorted_groups = tuple(
        sorted(
            groups,
            key=lambda group: (
                -group.disagreement_count,
                int(group.coverage_status != "holdout_only"),
                -group.holdout_count,
                -group.train_count,
                group.group_key,
            ),
        )
    )
    return PolicyLabelInspection(
        source_trajectories=source_trajectories,
        train_filter=train_filter,
        holdout_filter=holdout_filter,
        group_by=group_by,
        reward_margin=reward_margin,
        train_preference_count=len(train_preferences),
        holdout_preference_count=len(holdout_preferences),
        train_preferences=_preference_counts(list(train_preferences)),
        holdout_preferences=_preference_counts(list(holdout_preferences)),
        group_count=len(sorted_groups),
        disagreement_group_count=sum(
            int(group.disagreement_count > 0) for group in sorted_groups
        ),
        train_only_group_count=sum(
            int(group.coverage_status == "train_only") for group in sorted_groups
        ),
        holdout_only_group_count=sum(
            int(group.coverage_status == "holdout_only") for group in sorted_groups
        ),
        groups=sorted_groups,
    )


def score_baseline_action(
    model: PolicyModel,
    context: PolicyActionContext,
    action_id: str,
) -> float:
    return score_policy_action(model, context, action_id)


def score_policy_action(
    model: PolicyModel,
    context: PolicyActionContext,
    action_id: str,
) -> float:
    features = _feature_values(
        fixture_id=context.fixture_id,
        tags=context.tags,
        step_index=context.step_index,
        action_id=action_id,
        available_action_ids=context.available_action_ids,
        state_sql=context.state_sql,
        dialect=context.dialect,
    )
    return _score_features(model, features)


def _score_features(model: PolicyModel, features: tuple[str, ...]) -> float:
    if isinstance(model, BaselinePolicyModel):
        scores = {stat.feature: stat.win_rate for stat in model.feature_stats}
        values = [scores[feature] for feature in features if feature in scores]
        if not values:
            return model.default_score
        return sum(values) / len(values)

    weights = {item.feature: item.weight for item in model.feature_weights}
    return sum(weights.get(feature, 0.0) for feature in features) + model.default_score


def write_baseline_policy(model: PolicyModel, path: Path) -> None:
    write_policy_model(model, path)


def write_policy_model(model: PolicyModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2))


def load_baseline_policy(path: Path) -> PolicyModel:
    return load_policy_model(path)


def load_policy_model(path: Path) -> PolicyModel:
    payload = json.loads(path.read_text())
    artifact_type = payload.get("artifact_type")
    if artifact_type == "baseline_policy_model":
        return BaselinePolicyModel.model_validate(payload)
    if artifact_type == "linear_policy_model":
        return LinearPolicyModel.model_validate(payload)
    raise ValueError(f"Unknown policy model artifact_type: {artifact_type}.")


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


def render_linear_policy_training(model: LinearPolicyModel) -> str:
    return "\n".join(
        [
            f"Model: {model.model_type}",
            f"States: {model.state_count}",
            f"Labeled states: {model.labeled_state_count}",
            f"Choice states: {model.choice_state_count}",
            f"Epochs: {model.epochs}",
            f"Learning rate: {model.learning_rate:.6f}",
            f"Training margin: {model.training_margin:.6f}",
            f"Unknown preference scale: {model.unknown_preference_scale:.6f}",
            f"Unknown preference group by: {_render_tuple(model.unknown_preference_group_by)}",
            (
                "Unknown preference group scales: "
                f"{_render_group_scales(model.unknown_preference_group_scales)}"
            ),
            f"Updates: {model.update_count}",
            f"Skipped preferences: {model.skipped_preference_count}",
            f"Skipped unknown preferences: {model.skipped_unknown_preference_count}",
            f"Feature weights: {len(model.feature_weights)}",
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


def render_baseline_policy_inspection(
    inspection: BaselinePolicyInspection,
    *,
    limit: int | None = None,
) -> str:
    rows = inspection.rows[:limit] if limit is not None else inspection.rows
    lines = [
        "Baseline policy inspection",
        f"Model: {inspection.model_type}",
        f"States: {inspection.state_count}",
        f"Predicted states: {inspection.predicted_state_count}",
        f"Misses: {inspection.miss_count}",
        f"Unacceptable: {inspection.unacceptable_count}",
        f"Rows shown: {len(rows)}/{inspection.row_count}",
        f"Reward margin: {inspection.reward_margin:.6f}",
        f"Filter: {_render_filter(inspection.data_filter)}",
    ]
    if not rows:
        lines.append("")
        lines.append("No matching policy states.")
        return "\n".join(lines)

    for row in rows:
        gap = "n/a" if row.reward_gap is None else f"{row.reward_gap:.6f}"
        lines.extend(
            [
                "",
                f"Task: {row.task_id}",
                f"  Fixture: {row.fixture_id}",
                f"  Step: {row.step_index}",
                f"  Tags: {', '.join(row.tags) if row.tags else 'none'}",
                f"  Oracle: {row.oracle_action_id}",
                f"  Predicted: {row.predicted_action_id}",
                f"  Correct: {row.correct}",
                f"  Acceptable: {row.acceptable}",
                f"  Reward gap: {gap}",
                "  Scores:",
            ]
        )
        for action_id, score in sorted(
            row.action_scores.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"    {action_id}: {score:.6f}")
        lines.append("  SQL:")
        lines.extend(f"    {line}" for line in row.state_sql.splitlines())

    return "\n".join(lines)


def render_policy_label_inspection(
    inspection: PolicyLabelInspection,
    *,
    limit: int | None = None,
) -> str:
    groups = inspection.groups[:limit] if limit is not None else inspection.groups
    lines = [
        "Policy label inspection",
        f"Train preferences: {inspection.train_preference_count}",
        f"Holdout preferences: {inspection.holdout_preference_count}",
        f"Groups: {inspection.group_count}",
        f"Disagreement groups: {inspection.disagreement_group_count}",
        f"Train-only groups: {inspection.train_only_group_count}",
        f"Holdout-only groups: {inspection.holdout_only_group_count}",
        f"Rows shown: {len(groups)}/{inspection.group_count}",
        f"Group by: {', '.join(inspection.group_by)}",
        f"Reward margin: {inspection.reward_margin:.6f}",
        f"Train filter: {_render_filter(inspection.train_filter)}",
        f"Holdout filter: {_render_filter(inspection.holdout_filter)}",
        f"Global train prefs: {_render_preference_counts(inspection.train_preferences)}",
        f"Global holdout prefs: {_render_preference_counts(inspection.holdout_preferences)}",
    ]
    if not groups:
        lines.append("")
        lines.append("No matching preference groups.")
        return "\n".join(lines)

    for group in groups:
        lines.extend(
            [
                "",
                f"Group: {group.group_key}",
                f"  Coverage: {group.coverage_status}",
                f"  Train count: {group.train_count}",
                f"  Holdout count: {group.holdout_count}",
                f"  Disagreements: {group.disagreement_count}",
                f"  Train prefs: {_render_preference_counts(group.train_preferences)}",
                f"  Holdout prefs: {_render_preference_counts(group.holdout_preferences)}",
                "  Train majority: "
                f"{_render_majority(group.train_majority_preference, group.train_majority_ratio)}",
                "  Holdout majority: "
                f"{_render_majority(
                    group.holdout_majority_preference,
                    group.holdout_majority_ratio,
                )}",
                f"  Mean train gap: {_render_optional_float(group.mean_train_reward_gap)}",
                f"  Mean holdout gap: {_render_optional_float(group.mean_holdout_reward_gap)}",
            ]
        )
        for example in group.examples:
            gap = _render_optional_float(example.reward_gap)
            lines.extend(
                [
                    f"  Example: {example.task_id} ({example.fixture_id})",
                    f"    preferred={example.preferred_action_id}",
                    f"    alternative={example.alternative_action_id}",
                    f"    gap={gap}",
                ]
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


def compare_policy_holdouts(
    paths: tuple[Path, ...],
    *,
    labels: tuple[str, ...] = (),
) -> PolicyHoldoutComparison:
    if not paths:
        raise ValueError("At least one holdout evaluation path is required.")
    if labels and len(labels) != len(paths):
        raise ValueError("If labels are provided, their count must match paths.")
    resolved_labels = labels or tuple(path.stem for path in paths)
    rows = tuple(
        _holdout_comparison_row(
            load_policy_holdout_evaluation(path),
            label=label,
            path=path,
        )
        for label, path in zip(resolved_labels, paths, strict=True)
    )
    return PolicyHoldoutComparison(
        baseline_label=resolved_labels[0],
        rows=rows,
    )


def render_policy_holdout_comparison(comparison: PolicyHoldoutComparison) -> str:
    lines = [
        "Policy holdout comparison",
        f"Baseline: {comparison.baseline_label}",
        "",
        (
            "LABEL EXACT ADJUSTED GREEDY_REWARD POLICY_REWARD DELTA "
            "GREEDY_WINS POLICY_WINS WIN_DELTA GREEDY_REQ POLICY_REQ REQ_DELTA"
        ),
    ]
    for row in comparison.rows:
        lines.append(
            " ".join(
                [
                    row.label,
                    _render_optional_ratio(row.exact_accuracy),
                    _render_optional_ratio(row.adjusted_accuracy),
                    _render_optional_float(row.greedy_reward),
                    _render_optional_float(row.policy_reward),
                    _render_optional_float(row.reward_delta_vs_greedy),
                    _render_optional_int(row.greedy_wins),
                    _render_optional_int(row.policy_wins),
                    _render_optional_int(row.win_delta_vs_greedy),
                    _render_optional_int(row.greedy_oracle_requests),
                    _render_optional_int(row.policy_oracle_requests),
                    _render_optional_int(row.oracle_request_delta_vs_greedy),
                ]
            )
        )
    return "\n".join(lines)


def _holdout_comparison_row(
    evaluation: PolicyHoldoutEvaluation,
    *,
    label: str,
    path: Path,
) -> PolicyHoldoutComparisonRow:
    greedy_reward = evaluation.strategy_rewards.get("greedy")
    policy_reward = evaluation.strategy_rewards.get("policy_baseline_abstain")
    greedy_wins = evaluation.strategy_wins.get("greedy")
    policy_wins = evaluation.strategy_wins.get("policy_baseline_abstain")
    greedy_requests = _strategy_oracle_requests(evaluation, "greedy")
    policy_requests = _strategy_oracle_requests(evaluation, "policy_baseline_abstain")
    return PolicyHoldoutComparisonRow(
        label=label,
        path=str(path),
        model_type=evaluation.offline_evaluation.model_type,
        trained_state_count=evaluation.trained_state_count,
        heldout_state_count=evaluation.heldout_state_count,
        exact_accuracy=evaluation.offline_evaluation.accuracy,
        adjusted_accuracy=evaluation.offline_evaluation.adjusted_accuracy,
        greedy_reward=greedy_reward,
        policy_reward=policy_reward,
        reward_delta_vs_greedy=(
            None
            if greedy_reward is None or policy_reward is None
            else policy_reward - greedy_reward
        ),
        greedy_wins=greedy_wins,
        policy_wins=policy_wins,
        win_delta_vs_greedy=(
            None
            if greedy_wins is None or policy_wins is None
            else policy_wins - greedy_wins
        ),
        greedy_oracle_requests=greedy_requests,
        policy_oracle_requests=policy_requests,
        oracle_request_delta_vs_greedy=(
            None
            if greedy_requests is None or policy_requests is None
            else policy_requests - greedy_requests
        ),
    )


def _strategy_oracle_requests(
    evaluation: PolicyHoldoutEvaluation,
    strategy: str,
) -> int | None:
    verifier = evaluation.strategy_verifier_requests.get(strategy)
    benchmark = evaluation.strategy_benchmark_requests.get(strategy)
    if verifier is None and benchmark is None:
        return None
    return (verifier or 0) + (benchmark or 0)


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


def _preference_examples(
    examples: tuple[_StateExample, ...],
    *,
    reward_margin: float,
) -> tuple[PolicyPreferenceExample, ...]:
    preferences = []
    for example in examples:
        if example.oracle_action_id is None or len(example.available_action_ids) < 2:
            continue
        for action_id in example.available_action_ids:
            if action_id == example.oracle_action_id:
                continue
            gap = _known_reward_gap(example, action_id)
            if gap != float("inf") and gap < reward_margin:
                continue
            preferences.append(
                PolicyPreferenceExample(
                    task_id=example.task_id,
                    fixture_id=example.fixture_id,
                    tags=example.tags,
                    state_sql=example.state_sql,
                    available_action_ids=example.available_action_ids,
                    preferred_action_id=example.oracle_action_id,
                    alternative_action_id=action_id,
                    reward_gap=None if gap == float("inf") else gap,
                )
            )
    return tuple(preferences)


def _preference_group_key(
    preference: PolicyPreferenceExample,
    group_by: tuple[str, ...],
) -> str:
    parts = []
    for group_name in group_by:
        if group_name == "action_set":
            action_set = "+".join(sorted(preference.available_action_ids))
            parts.append(f"action_set={action_set}")
        elif group_name == "rule_pair":
            rules = sorted(
                {
                    _rule_name(preference.preferred_action_id),
                    _rule_name(preference.alternative_action_id),
                }
            )
            parts.append(f"rule_pair={' vs '.join(rules)}")
        elif group_name == "preferred_rule":
            parts.append(f"preferred_rule={_rule_name(preference.preferred_action_id)}")
        elif group_name == "alternative_rule":
            parts.append(
                f"alternative_rule={_rule_name(preference.alternative_action_id)}"
            )
        elif group_name == "table":
            parts.append(f"table={_table_tag(preference.tags)}")
        elif group_name == "fixture":
            parts.append(f"fixture={preference.fixture_id}")
        elif group_name == "target":
            parts.append(f"target={_target_key(preference.preferred_action_id)}")
        elif group_name == "target_pair":
            parts.append(
                "target_pair="
                f"{_target_key(preference.preferred_action_id)}"
                " vs "
                f"{_target_key(preference.alternative_action_id)}"
            )
        else:
            raise ValueError(f"Unsupported policy label group: {group_name}")
    return " | ".join(parts) if parts else "all"


def _table_tag(tags: tuple[str, ...]) -> str:
    for tag in tags:
        if tag.startswith("table:"):
            return tag
    return "table:none"


def _target_key(action_id: str) -> str:
    target_kind, target_index = _action_target(action_id)
    if target_index is None:
        return target_kind
    return f"{target_kind}:{target_index}"


def _preference_counts(
    preferences: list[PolicyPreferenceExample],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for preference in preferences:
        counts[preference.preferred_action_id] += 1
    return dict(sorted(counts.items()))


def _preference_disagreement_count(
    train_counts: dict[str, int],
    holdout_counts: dict[str, int],
) -> int:
    train_majority = _majority_preference(train_counts)
    if train_majority is None:
        return 0
    return sum(
        count
        for action_id, count in holdout_counts.items()
        if action_id != train_majority
    )


def _preference_coverage_status(
    *,
    train_count: int,
    holdout_count: int,
) -> Literal["matched", "train_only", "holdout_only"]:
    if train_count > 0 and holdout_count > 0:
        return "matched"
    if holdout_count > 0:
        return "holdout_only"
    return "train_only"


def _majority_preference(counts: dict[str, int]) -> str | None:
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _majority_ratio(counts: dict[str, int]) -> float | None:
    if not counts:
        return None
    total = sum(counts.values())
    if total == 0:
        return None
    majority = max(counts.values())
    return majority / total


def _mean_known_gap(preferences: list[PolicyPreferenceExample]) -> float | None:
    gaps = [
        preference.reward_gap
        for preference in preferences
        if preference.reward_gap is not None
    ]
    if not gaps:
        return None
    return sum(gaps) / len(gaps)


def _preference_example_sort_key(
    preference: PolicyPreferenceExample,
) -> tuple[int, float, str, str, str]:
    gap = preference.reward_gap if preference.reward_gap is not None else 0.0
    return (
        -int(preference.reward_gap is not None),
        -gap,
        preference.task_id,
        preference.preferred_action_id,
        preference.alternative_action_id,
    )


def _predict_policy(example: _StateExample, model: PolicyModel) -> str | None:
    if not example.available_action_ids:
        return None
    return sorted(
        example.available_action_ids,
        key=lambda action_id: (
            -_score_policy(example, action_id, model),
            action_id,
        ),
    )[0]


def _score_policy(
    example: _StateExample,
    action_id: str,
    model: PolicyModel,
) -> float:
    return _score_features(model, _features(example, action_id))


def _score_linear_features(
    features: tuple[str, ...],
    weights: dict[str, float],
    default_score: float,
) -> float:
    return sum(weights.get(feature, 0.0) for feature in features) + default_score


def _reward_span(example: _StateExample) -> float:
    rewards = [
        reward
        for action_id, reward in example.observed_suffix_rewards.items()
        if action_id in example.available_action_ids
    ]
    if not rewards:
        return 0.0
    return max(rewards) - min(rewards)


def _preference_scale(
    example: _StateExample,
    action_id: str,
    reward_span: float,
) -> float:
    if reward_span <= 0:
        return 1.0
    oracle_reward = example.observed_suffix_rewards.get(example.oracle_action_id or "")
    action_reward = example.observed_suffix_rewards.get(action_id)
    if oracle_reward is None or action_reward is None:
        return 1.0
    return max(0.0, (oracle_reward - action_reward) / reward_span)


def _unknown_preference_scale(
    example: _StateExample,
    action_id: str,
    *,
    group_by: tuple[str, ...],
    group_scales: dict[str, float],
    default_scale: float,
) -> float:
    if not group_scales:
        return default_scale
    assert example.oracle_action_id is not None
    preference = PolicyPreferenceExample(
        task_id=example.task_id,
        fixture_id=example.fixture_id,
        tags=example.tags,
        state_sql=example.state_sql,
        available_action_ids=example.available_action_ids,
        preferred_action_id=example.oracle_action_id,
        alternative_action_id=action_id,
        reward_gap=None,
    )
    return group_scales.get(
        _preference_group_key(preference, group_by),
        default_scale,
    )


def _known_reward_gap(example: _StateExample, action_id: str) -> float:
    oracle_reward = example.observed_suffix_rewards.get(example.oracle_action_id or "")
    action_reward = example.observed_suffix_rewards.get(action_id)
    if oracle_reward is None or action_reward is None:
        return float("inf")
    return oracle_reward - action_reward


def _inspection_sort_key(row: BaselinePolicyInspectionRow) -> tuple[int, float, str, int]:
    reward_gap = row.reward_gap if row.reward_gap is not None else 0.0
    return (
        int(row.acceptable),
        -reward_gap,
        row.task_id,
        row.step_index,
    )


def _features(example: _StateExample, action_id: str) -> tuple[str, ...]:
    return _feature_values(
        fixture_id=example.fixture_id,
        tags=example.tags,
        step_index=example.step_index,
        action_id=action_id,
        available_action_ids=example.available_action_ids,
        state_sql=example.state_sql,
    )


def _feature_values(
    *,
    fixture_id: str,
    tags: tuple[str, ...],
    step_index: int,
    action_id: str,
    available_action_ids: tuple[str, ...] = (),
    state_sql: str | None = None,
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> tuple[str, ...]:
    rule_name = _rule_name(action_id)
    target_kind, target_index = _action_target(action_id)
    available_rules = tuple(sorted({_rule_name(item) for item in available_action_ids}))
    same_rule_actions = tuple(
        sorted(item for item in available_action_ids if _rule_name(item) == rule_name)
    )
    same_rule_position = (
        same_rule_actions.index(action_id) if action_id in same_rule_actions else None
    )
    available_rule_key = "+".join(available_rules) if available_rules else "none"
    return (
        f"action:{action_id}",
        f"rule:{rule_name}",
        f"fixture_action:{fixture_id}:{action_id}",
        f"step_action:{step_index}:{action_id}",
        f"target_kind:{target_kind}",
        f"rule_target_kind:{rule_name}:{target_kind}",
        f"available_rules:{available_rule_key}",
        f"action_available_rules:{action_id}:{available_rule_key}",
        f"rule_available_rules:{rule_name}:{available_rule_key}",
        *(f"competes_with:{rule_name}:{other}" for other in available_rules if other != rule_name),
        *(
            (f"target_index:{target_index}", f"rule_target_index:{rule_name}:{target_index}")
            if target_index is not None
            else ()
        ),
        *(
            (
                f"same_rule_count:{rule_name}:{len(same_rule_actions)}",
                f"same_rule_position:{rule_name}:{same_rule_position}",
            )
            if same_rule_position is not None and len(same_rule_actions) > 1
            else ()
        ),
        *(f"tag_action:{tag}:{action_id}" for tag in tags),
        *_sql_context_features(
            state_sql=state_sql,
            dialect=dialect,
            action_id=action_id,
            rule_name=rule_name,
            target_index=target_index,
        ),
    )


def _rule_name(action_id: str) -> str:
    return action_id.split("::", 1)[0]


def _action_target(action_id: str) -> tuple[str, int | None]:
    if "::" not in action_id:
        return "unknown", None
    match_id = action_id.split("::", 1)[1]
    if ":" not in match_id:
        return match_id, None
    target_kind, raw_index = match_id.split(":", 1)
    try:
        return target_kind, int(raw_index)
    except ValueError:
        return target_kind, None


def _sql_context_features(
    *,
    state_sql: str | None,
    dialect: SqlDialect,
    action_id: str,
    rule_name: str,
    target_index: int | None,
) -> tuple[str, ...]:
    if state_sql is None:
        return ()
    try:
        query = parse_select(state_sql, dialect=dialect)
    except UnsupportedSqlError:
        return ()

    projection_columns = _direct_projection_columns(query)
    not_null_columns = _not_null_predicate_columns(query)
    action_column = _action_column(
        query,
        rule_name=rule_name,
        target_index=target_index,
    )
    projection_key = "+".join(projection_columns) if projection_columns else "none"
    not_null_key = "+".join(not_null_columns) if not_null_columns else "none"
    features = [
        f"state_projection_columns:{projection_key}",
        f"state_not_null_columns:{not_null_key}",
        f"state_distinct:{str(query.distinct).lower()}",
        f"state_projection_count:{len(projection_columns)}",
        f"action_projection_columns:{action_id}:{projection_key}",
        f"action_not_null_columns:{action_id}:{not_null_key}",
        f"rule_projection_columns:{rule_name}:{projection_key}",
        f"rule_not_null_columns:{rule_name}:{not_null_key}",
    ]

    if query.distinct:
        has_not_null_on_projection = bool(set(projection_columns) & set(not_null_columns))
        features.extend(
            [
                (
                    "state_distinct_has_not_null_projection:"
                    f"{str(has_not_null_on_projection).lower()}"
                ),
                (
                    "rule_distinct_has_not_null_projection:"
                    f"{rule_name}:{str(has_not_null_on_projection).lower()}"
                ),
            ]
        )

    if action_column is not None:
        action_column_projected = action_column in projection_columns
        action_column_is_only_projection = projection_columns == (action_column,)
        features.extend(
            [
                f"action_column:{action_id}:{action_column}",
                f"rule_action_column:{rule_name}:{action_column}",
                f"target_column:{action_column}",
                f"action_column_projected:{action_id}:{str(action_column_projected).lower()}",
                f"rule_action_column_projected:{rule_name}:{str(action_column_projected).lower()}",
                (
                    "rule_action_column_is_only_projection:"
                    f"{rule_name}:{str(action_column_is_only_projection).lower()}"
                ),
            ]
        )

    return tuple(features)


def _direct_projection_columns(query: SelectQuery) -> tuple[str, ...]:
    return tuple(
        projection.name
        for projection in query.projections
        if projection.is_direct_column()
    )


def _not_null_predicate_columns(query: SelectQuery) -> tuple[str, ...]:
    return tuple(
        predicate.left.name
        for predicate in query.predicates
        if isinstance(predicate, Predicate) and predicate.operator == "IS NOT NULL"
    )


def _action_column(
    query: SelectQuery,
    *,
    rule_name: str,
    target_index: int | None,
) -> str | None:
    if rule_name == "remove_redundant_distinct":
        projection_columns = _direct_projection_columns(query)
        if len(projection_columns) == 1:
            return projection_columns[0]
        return None
    if rule_name != "remove_redundant_not_null_filter" or target_index is None:
        return None
    if target_index < 0 or target_index >= len(query.predicates):
        return None
    predicate = query.predicates[target_index]
    if not isinstance(predicate, Predicate) or predicate.operator != "IS NOT NULL":
        return None
    return predicate.left.name


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


def _render_tuple(values: tuple[str, ...]) -> str:
    return ",".join(values) if values else "none"


def _render_group_scales(scales: dict[str, float]) -> str:
    if not scales:
        return "none"
    return ", ".join(
        f"{group_key}={scale:.6f}" for group_key, scale in sorted(scales.items())
    )


def _render_preference_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(
        f"{action_id}={count}"
        for action_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _render_majority(action_id: str | None, ratio: float | None) -> str:
    if action_id is None or ratio is None:
        return "none"
    return f"{action_id} ({ratio:.4f})"


def _render_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def _render_optional_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def _render_optional_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


def load_policy_holdout_evaluation(path: Path) -> PolicyHoldoutEvaluation:
    return PolicyHoldoutEvaluation.model_validate(json.loads(path.read_text()))


def load_baseline_policy_evaluation(path: Path) -> BaselinePolicyEvaluation:
    return BaselinePolicyEvaluation.model_validate(json.loads(path.read_text()))
