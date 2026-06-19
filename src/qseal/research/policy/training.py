from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from qseal.research.corpus.trajectories import load_corpus_trajectory_records
from qseal.research.policy.examples import (
    _action_is_acceptable,
    _filter_examples,
    _known_reward_gap,
    _preference_scale,
    _reward_span,
    _same_observed_endpoint,
    _state_examples,
    _StateExample,
)
from qseal.research.policy.features import _features
from qseal.research.policy.labels import _preference_group_key
from qseal.research.policy.model import (
    BaselinePolicyModel,
    FeatureStat,
    FeatureWeight,
    LinearPolicyModel,
    PolicyDataFilter,
    PolicyPreferenceExample,
)


def train_baseline_policy(
    trajectory_path: Path,
    *,
    source_trajectories: str | None = None,
    data_filter: PolicyDataFilter | None = None,
    stop_margin: float = 0.0,
) -> BaselinePolicyModel:
    if stop_margin < 0:
        raise ValueError("stop_margin must be zero or greater.")
    data_filter = data_filter or PolicyDataFilter()
    records = load_corpus_trajectory_records(trajectory_path)
    examples = _filter_examples(
        _state_examples(records, stop_margin=stop_margin),
        data_filter,
    )
    labeled = [example for example in examples if example.oracle_action_id is not None]
    feature_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for example in labeled:
        if len(example.available_action_ids) < 2:
            continue
        assert example.oracle_action_id is not None
        for action_id in example.available_action_ids:
            is_oracle = _action_is_acceptable(
                example,
                action_id,
                reward_margin=stop_margin,
            )
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
        stop_margin=stop_margin,
        feature_stats=stats,
        default_score=total_oracle / total_appearances if total_appearances else 0.0,
    )


def train_linear_policy(
    trajectory_path: Path,
    *,
    source_trajectories: str | None = None,
    data_filter: PolicyDataFilter | None = None,
    stop_margin: float = 0.0,
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
    if stop_margin < 0:
        raise ValueError("stop_margin must be zero or greater.")
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
    examples = _filter_examples(
        _state_examples(records, stop_margin=stop_margin),
        data_filter,
    )
    labeled = [example for example in examples if example.oracle_action_id is not None]
    choice_examples = [
        example for example in labeled if len(example.available_action_ids) >= 2
    ]
    weights: dict[str, float] = {}
    update_count = 0
    skipped_preference_count = 0
    skipped_unknown_preference_count = 0
    skipped_equivalent_preference_count = 0

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
                if _same_observed_endpoint(
                    example,
                    example.oracle_action_id,
                    action_id,
                ):
                    skipped_equivalent_preference_count += 1
                    continue
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
        stop_margin=stop_margin,
        epochs=epochs,
        learning_rate=learning_rate,
        training_margin=training_margin,
        unknown_preference_scale=unknown_preference_scale,
        unknown_preference_group_by=unknown_preference_group_by,
        unknown_preference_group_scales=dict(sorted(unknown_preference_group_scales.items())),
        update_count=update_count,
        skipped_preference_count=skipped_preference_count,
        skipped_unknown_preference_count=skipped_unknown_preference_count,
        skipped_equivalent_preference_count=skipped_equivalent_preference_count,
        feature_weights=tuple(
            FeatureWeight(feature=feature, weight=weight)
            for feature, weight in sorted(weights.items())
            if weight != 0
        ),
    )


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
