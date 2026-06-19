from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Literal

from qseal.research.corpus.trajectories import load_corpus_trajectory_records
from qseal.research.policy.examples import (
    _action_is_acceptable,
    _filter_examples,
    _known_reward_gap,
    _state_examples,
    _StateExample,
)
from qseal.research.policy.features import _action_target, _rule_name
from qseal.research.policy.model import (
    PolicyDataFilter,
    PolicyLabelInspection,
    PolicyPreferenceExample,
    PolicyPreferenceGroup,
)


def inspect_policy_labels(
    trajectory_path: Path,
    *,
    source_trajectories: str | None = None,
    train_filter: PolicyDataFilter | None = None,
    holdout_filter: PolicyDataFilter | None = None,
    group_by: tuple[str, ...] = ("action_set", "table"),
    reward_margin: float = 0.0,
    stop_margin: float = 0.0,
    examples_per_group: int = 3,
) -> PolicyLabelInspection:
    if reward_margin < 0:
        raise ValueError("reward_margin must be zero or greater.")
    if stop_margin < 0:
        raise ValueError("stop_margin must be zero or greater.")
    if examples_per_group < 0:
        raise ValueError("examples_per_group must be zero or greater.")
    train_filter = train_filter or PolicyDataFilter()
    holdout_filter = holdout_filter or PolicyDataFilter()
    examples = _state_examples(
        load_corpus_trajectory_records(trajectory_path),
        stop_margin=stop_margin,
    )
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
        stop_margin=stop_margin,
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
            if _action_is_acceptable(
                example,
                action_id,
                reward_margin=reward_margin,
            ):
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
