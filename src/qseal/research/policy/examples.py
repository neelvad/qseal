from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from qseal.research.corpus.trajectories import CorpusTrajectoryRecord
from qseal.research.policy.model import STOP_ACTION_ID, PolicyDataFilter


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
    observed_final_sql_by_action: dict[str, str]


def _state_examples(
    records: tuple[CorpusTrajectoryRecord, ...],
    *,
    stop_margin: float = 0.0,
) -> tuple[_StateExample, ...]:
    final_sql_by_result = _final_sql_by_result(records)
    grouped: dict[tuple[str, str], list[CorpusTrajectoryRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.task_id, record.state_sql)].append(record)

    examples = []
    for (task_id, state_sql), state_records in sorted(grouped.items()):
        first = state_records[0]
        rewards: dict[str, float] = {}
        final_sql_by_action: dict[str, str] = {}
        for record in state_records:
            existing = rewards.get(record.action_id)
            if existing is None or record.suffix_reward > existing:
                rewards[record.action_id] = record.suffix_reward
                final_sql_by_action[record.action_id] = final_sql_by_result[
                    (record.task_id, record.strategy)
                ]
        rewards[STOP_ACTION_ID] = 0.0
        final_sql_by_action[STOP_ACTION_ID] = state_sql
        oracle_action_id, oracle_suffix_reward = _oracle_action(
            rewards,
            stop_margin=stop_margin,
        )
        examples.append(
            _StateExample(
                task_id=task_id,
                state_sql=state_sql,
                fixture_id=first.fixture_id,
                tags=first.tags,
                step_index=first.step_index,
                available_action_ids=_policy_action_ids(first.available_action_ids),
                oracle_action_id=oracle_action_id,
                oracle_suffix_reward=oracle_suffix_reward,
                observed_suffix_rewards=rewards,
                observed_final_sql_by_action=final_sql_by_action,
            )
        )
    return tuple(examples)


def _final_sql_by_result(
    records: tuple[CorpusTrajectoryRecord, ...],
) -> dict[tuple[str, str], str]:
    grouped: dict[tuple[str, str], list[CorpusTrajectoryRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.task_id, record.strategy)].append(record)
    return {
        key: sorted(items, key=lambda item: item.step_index)[-1].next_sql
        for key, items in grouped.items()
    }


def _policy_action_ids(action_ids: tuple[str, ...]) -> tuple[str, ...]:
    items = tuple(action_id for action_id in action_ids if action_id != STOP_ACTION_ID)
    return (*items, STOP_ACTION_ID)


def _oracle_action(
    rewards: dict[str, float],
    *,
    stop_margin: float,
) -> tuple[str | None, float | None]:
    if not rewards:
        return None, None
    action_id, reward = sorted(
        rewards.items(),
        key=lambda item: (-item[1], item[0]),
    )[0]
    if action_id != STOP_ACTION_ID and reward <= stop_margin:
        return STOP_ACTION_ID, rewards[STOP_ACTION_ID]
    return action_id, reward


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


def _known_reward_gap(example: _StateExample, action_id: str) -> float:
    oracle_reward = example.observed_suffix_rewards.get(example.oracle_action_id or "")
    action_reward = example.observed_suffix_rewards.get(action_id)
    if oracle_reward is None or action_reward is None:
        return float("inf")
    return oracle_reward - action_reward


def _action_is_acceptable(
    example: _StateExample,
    action_id: str,
    *,
    reward_margin: float,
) -> bool:
    if action_id == example.oracle_action_id:
        return True
    gap = _known_reward_gap(example, action_id)
    if gap != float("inf") and gap <= reward_margin:
        return True
    return _same_observed_endpoint(example, example.oracle_action_id, action_id)


def _same_observed_endpoint(
    example: _StateExample,
    left_action_id: str | None,
    right_action_id: str | None,
) -> bool:
    if left_action_id is None or right_action_id is None:
        return False
    left = example.observed_final_sql_by_action.get(left_action_id)
    right = example.observed_final_sql_by_action.get(right_action_id)
    if left is None or right is None:
        return False
    return _canonical_endpoint_sql(left) == _canonical_endpoint_sql(right)


def _canonical_endpoint_sql(sql: str) -> str:
    return " ".join(sql.split())
