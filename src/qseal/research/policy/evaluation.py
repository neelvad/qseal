from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Literal

from qseal.research.corpus.trajectories import load_corpus_trajectory_records
from qseal.research.policy.examples import (
    _filter_examples,
    _same_observed_endpoint,
    _state_examples,
)
from qseal.research.policy.features import _rule_name
from qseal.research.policy.model import (
    BaselinePolicyEvaluation,
    BaselinePolicyInspection,
    BaselinePolicyInspectionRow,
    PolicyDataFilter,
    PolicyModel,
    RuleAccuracy,
)
from qseal.research.policy.scoring import _predict_policy, _score_policy


def evaluate_baseline_policy(
    trajectory_path: Path,
    model: PolicyModel,
    *,
    source_trajectories: str | None = None,
    model_path: str | None = None,
    data_filter: PolicyDataFilter | None = None,
    reward_margin: float = 0.0,
    stop_margin: float = 0.0,
) -> BaselinePolicyEvaluation:
    if reward_margin < 0:
        raise ValueError("reward_margin must be zero or greater.")
    if stop_margin < 0:
        raise ValueError("stop_margin must be zero or greater.")
    data_filter = data_filter or PolicyDataFilter()
    examples = [
        example
        for example in _filter_examples(
            _state_examples(
                load_corpus_trajectory_records(trajectory_path),
                stop_margin=stop_margin,
            ),
            data_filter,
        )
        if example.oracle_action_id is not None
    ]
    correct = 0
    acceptable = 0
    predicted = 0
    known_gaps = []
    endpoint_equivalent_count = 0
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
        endpoint_equivalent = _same_observed_endpoint(
            example,
            example.oracle_action_id,
            prediction,
        )
        endpoint_equivalent_count += int(endpoint_equivalent and not is_correct)
        if oracle_reward is not None and predicted_reward is not None:
            reward_gap = oracle_reward - predicted_reward
            known_gaps.append(reward_gap)
            is_acceptable = reward_gap <= reward_margin or endpoint_equivalent
        elif endpoint_equivalent:
            is_acceptable = True
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
        stop_margin=stop_margin,
        endpoint_equivalent_count=endpoint_equivalent_count,
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
    stop_margin: float = 0.0,
    mode: Literal["misses", "unacceptable", "all"] = "misses",
) -> BaselinePolicyInspection:
    if reward_margin < 0:
        raise ValueError("reward_margin must be zero or greater.")
    if stop_margin < 0:
        raise ValueError("stop_margin must be zero or greater.")
    if mode not in ("misses", "unacceptable", "all"):
        raise ValueError(f"Unknown inspection mode: {mode}.")

    data_filter = data_filter or PolicyDataFilter()
    examples = [
        example
        for example in _filter_examples(
            _state_examples(
                load_corpus_trajectory_records(trajectory_path),
                stop_margin=stop_margin,
            ),
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
        endpoint_equivalent = _same_observed_endpoint(
            example,
            example.oracle_action_id,
            prediction,
        )
        if oracle_reward is not None and predicted_reward is not None:
            reward_gap = oracle_reward - predicted_reward
            acceptable = reward_gap <= reward_margin or endpoint_equivalent
        elif endpoint_equivalent:
            acceptable = True
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
                endpoint_equivalent=endpoint_equivalent,
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
        stop_margin=stop_margin,
    )


def _inspection_sort_key(row: BaselinePolicyInspectionRow) -> tuple[int, float, str, int]:
    reward_gap = row.reward_gap if row.reward_gap is not None else 0.0
    return (
        int(row.acceptable),
        -reward_gap,
        row.task_id,
        row.step_index,
    )
