from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from snowprove.environment import (
    EnvironmentObservation,
    EnvironmentTask,
    EnvironmentTransition,
    RewriteEnvironment,
)
from snowprove.search.model import SearchResult, SearchStep

EnvironmentFactory = Callable[[], RewriteEnvironment]


@dataclass(frozen=True)
class _SearchNode:
    action_ids: tuple[str, ...]
    transitions: tuple[EnvironmentTransition, ...]
    observation: EnvironmentObservation
    cumulative_reward: float
    terminated: bool
    truncated: bool

    def active(self) -> bool:
        return not self.terminated and not self.truncated and bool(self.observation.actions)


def fixed_order_search(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
) -> SearchResult:
    node = _root_node(task, environment_factory)
    explored = 0
    while node.active():
        node = _run_sequence(
            task,
            environment_factory,
            (*node.action_ids, node.observation.actions[0].action_id),
        )
        explored += 1
    return _result("fixed_order", task, node, explored_nodes=explored)


def random_search(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
    *,
    seed: int,
) -> SearchResult:
    generator = random.Random(seed)
    node = _root_node(task, environment_factory)
    explored = 0
    while node.active():
        action = generator.choice(node.observation.actions)
        node = _run_sequence(
            task,
            environment_factory,
            (*node.action_ids, action.action_id),
        )
        explored += 1
    return _result(
        "random",
        task,
        node,
        explored_nodes=explored,
        seed=seed,
    )


def greedy_search(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
) -> SearchResult:
    node = _root_node(task, environment_factory)
    explored = 0
    stopped_early = False
    while node.active():
        candidates = _expand_node(task, environment_factory, node)
        explored += len(candidates)
        candidate = _best_node(candidates)
        if candidate.cumulative_reward <= node.cumulative_reward:
            stopped_early = True
            break
        node = candidate
    return _result(
        "greedy",
        task,
        node,
        explored_nodes=explored,
        stopped_early=stopped_early,
    )


def beam_search(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
    *,
    beam_width: int = 4,
) -> SearchResult:
    if beam_width < 1:
        raise ValueError("beam_width must be one or greater.")

    root = _root_node(task, environment_factory)
    frontier = [root]
    candidates_seen = [root]
    explored = 0
    while any(node.active() for node in frontier):
        expanded = []
        for node in frontier:
            if node.active():
                children = _expand_node(task, environment_factory, node)
                explored += len(children)
                expanded.extend(children)
            else:
                expanded.append(node)
        frontier = _rank_nodes(_deduplicate_nodes(expanded))[:beam_width]
        candidates_seen.extend(frontier)

    best = _best_node(candidates_seen)
    return _result(
        "beam",
        task,
        best,
        explored_nodes=explored,
        beam_width=beam_width,
    )


def exhaustive_search(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
    *,
    max_nodes: int = 1_000,
) -> SearchResult:
    if max_nodes < 1:
        raise ValueError("max_nodes must be one or greater.")

    root = _root_node(task, environment_factory)
    frontier = [root]
    candidates_seen = [root]
    best_by_sql = {root.observation.current_sql: root}
    explored = 0
    search_truncated = False

    while frontier:
        node = frontier.pop(0)
        if not node.active():
            continue
        for action in node.observation.actions:
            if explored >= max_nodes:
                search_truncated = True
                frontier.clear()
                break
            child = _run_sequence(
                task,
                environment_factory,
                (*node.action_ids, action.action_id),
            )
            explored += 1
            existing = best_by_sql.get(child.observation.current_sql)
            if existing is not None and _node_sort_key(existing) <= _node_sort_key(child):
                continue
            best_by_sql[child.observation.current_sql] = child
            candidates_seen.append(child)
            if child.active():
                frontier.append(child)

    best = _best_node(candidates_seen)
    return _result(
        "exhaustive",
        task,
        best,
        explored_nodes=explored,
        search_truncated=search_truncated,
        max_nodes=max_nodes,
    )


def _root_node(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
) -> _SearchNode:
    observation = environment_factory().reset(task)
    return _SearchNode(
        action_ids=(),
        transitions=(),
        observation=observation,
        cumulative_reward=0.0,
        terminated=not observation.actions,
        truncated=False,
    )


def _run_sequence(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
    action_ids: tuple[str, ...],
) -> _SearchNode:
    environment = environment_factory()
    observation = environment.reset(task)
    transitions = []
    cumulative_reward = 0.0
    terminated = not observation.actions
    truncated = False

    for action_id in action_ids:
        transition = environment.step(action_id)
        transitions.append(transition)
        cumulative_reward += transition.reward
        observation = transition.observation
        terminated = transition.terminated
        truncated = transition.truncated
        if terminated or truncated:
            break

    return _SearchNode(
        action_ids=tuple(transition.action.action_id for transition in transitions),
        transitions=tuple(transitions),
        observation=observation,
        cumulative_reward=cumulative_reward,
        terminated=terminated,
        truncated=truncated,
    )


def _expand_node(
    task: EnvironmentTask,
    environment_factory: EnvironmentFactory,
    node: _SearchNode,
) -> list[_SearchNode]:
    return [
        _run_sequence(
            task,
            environment_factory,
            (*node.action_ids, action.action_id),
        )
        for action in node.observation.actions
    ]


def _deduplicate_nodes(nodes: list[_SearchNode]) -> list[_SearchNode]:
    best_by_sql: dict[str, _SearchNode] = {}
    for node in nodes:
        existing = best_by_sql.get(node.observation.current_sql)
        if existing is None or _node_sort_key(node) < _node_sort_key(existing):
            best_by_sql[node.observation.current_sql] = node
    return list(best_by_sql.values())


def _best_node(nodes: list[_SearchNode]) -> _SearchNode:
    if not nodes:
        raise ValueError("Search produced no nodes.")
    return min(nodes, key=_node_sort_key)


def _rank_nodes(nodes: list[_SearchNode]) -> list[_SearchNode]:
    return sorted(nodes, key=_node_sort_key)


def _node_sort_key(node: _SearchNode) -> tuple[float, int, tuple[str, ...]]:
    return (-node.cumulative_reward, len(node.action_ids), node.action_ids)


def _result(
    strategy: str,
    task: EnvironmentTask,
    node: _SearchNode,
    *,
    explored_nodes: int,
    stopped_early: bool = False,
    search_truncated: bool = False,
    seed: int | None = None,
    beam_width: int | None = None,
    max_nodes: int | None = None,
) -> SearchResult:
    cumulative = 0.0
    steps = []
    state_sql = task.sql.strip()
    for index, transition in enumerate(node.transitions):
        cumulative += transition.reward
        steps.append(
            SearchStep(
                step_index=index,
                action_id=transition.action.action_id,
                state_sql=state_sql,
                proposed_sql=transition.proposed_sql,
                next_sql=transition.observation.current_sql,
                reward=transition.reward,
                cumulative_reward=cumulative,
                verification_status=transition.verification.status,
                terminated=transition.terminated,
                truncated=transition.truncated,
            )
        )
        state_sql = transition.observation.current_sql

    return SearchResult(
        strategy=strategy,
        task_id=task.task_id,
        initial_sql=task.sql.strip(),
        final_sql=node.observation.current_sql,
        action_ids=node.action_ids,
        steps=tuple(steps),
        cumulative_reward=node.cumulative_reward,
        terminated=node.terminated,
        truncated=node.truncated,
        stopped_early=stopped_early,
        search_truncated=search_truncated,
        explored_nodes=explored_nodes,
        seed=seed,
        beam_width=beam_width,
        max_nodes=max_nodes,
    )
