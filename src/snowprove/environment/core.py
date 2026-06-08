from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Protocol

from snowprove.benchmark import BenchmarkResult, BenchmarkStatus, benchmark_query_pair
from snowprove.environment.model import (
    EnvironmentAction,
    EnvironmentObservation,
    EnvironmentTask,
    EnvironmentTransition,
)
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.registry import (
    DEFAULT_RULES,
    RewriteRule,
    apply_rewrite_match,
    available_rewrite_matches,
)
from snowprove.verifier.backends import BuiltinVerifierBackend
from snowprove.verifier.backends.base import VerifierBackend


class PerformanceEvaluator(Protocol):
    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        pass


class TrajectoryRecorder(Protocol):
    def record(
        self,
        task: EnvironmentTask,
        before: EnvironmentObservation,
        transition: EnvironmentTransition,
    ) -> Any:
        pass


class DuckDbPerformanceEvaluator:
    def __init__(
        self,
        *,
        database_path: Path | str = ":memory:",
        setup_sql: str | None = None,
        warmups: int = 2,
        repetitions: int = 5,
        timeout_seconds: float = 30.0,
        threads: int = 1,
        fixture_fingerprint: str | None = None,
        minimum_duration_ms: float = 0.0,
    ) -> None:
        self.database_path = database_path
        self.setup_sql = setup_sql
        self.warmups = warmups
        self.repetitions = repetitions
        self.timeout_seconds = timeout_seconds
        self.threads = threads
        self.fixture_fingerprint = fixture_fingerprint
        self.minimum_duration_ms = minimum_duration_ms

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        return benchmark_query_pair(
            original_sql,
            rewritten_sql,
            database_path=self.database_path,
            setup_sql=self.setup_sql,
            warmups=self.warmups,
            repetitions=self.repetitions,
            timeout_seconds=self.timeout_seconds,
            threads=self.threads,
            minimum_duration_ms=self.minimum_duration_ms,
        )

    def cache_context(self) -> dict[str, Any]:
        return {
            "evaluator": "duckdb",
            "database_path": str(self.database_path),
            "fixture_fingerprint": self.fixture_fingerprint,
            "setup_sha256": (
                hashlib.sha256(self.setup_sql.encode()).hexdigest()
                if self.setup_sql is not None
                else None
            ),
            "warmups": self.warmups,
            "repetitions": self.repetitions,
            "timeout_seconds": self.timeout_seconds,
            "threads": self.threads,
            "minimum_duration_ms": self.minimum_duration_ms,
        }


class RewriteEnvironment:
    def __init__(
        self,
        *,
        verifier: VerifierBackend | None = None,
        performance_evaluator: PerformanceEvaluator | None = None,
        trajectory_recorder: TrajectoryRecorder | None = None,
        rules: tuple[RewriteRule, ...] = DEFAULT_RULES,
    ) -> None:
        self.verifier = verifier or BuiltinVerifierBackend()
        self.performance_evaluator = performance_evaluator
        self.trajectory_recorder = trajectory_recorder
        self.rules = rules
        self._task: EnvironmentTask | None = None
        self._observation: EnvironmentObservation | None = None
        self._done = False

    def reset(self, task: EnvironmentTask) -> EnvironmentObservation:
        query = parse_select(task.sql, dialect=task.dialect)
        observation = self._observation_for(
            task=task,
            current_sql=task.sql.strip(),
            step_index=0,
            query=query,
        )
        self._task = task
        self._observation = observation
        self._done = False
        return observation

    def step(self, action_id: str) -> EnvironmentTransition:
        task, observation = self._active_episode()
        action = next(
            (candidate for candidate in observation.actions if candidate.action_id == action_id),
            None,
        )
        if action is None:
            raise ValueError(f"Action is not available in the current state: {action_id}.")

        current_query = parse_select(observation.current_sql, dialect=task.dialect)
        suggestion = apply_rewrite_match(
            current_query,
            task.constraints,
            action.match,
            rules=self.rules,
        )
        if suggestion.rewritten_sql is None:
            raise RuntimeError(f"Rewrite action produced no SQL: {action_id}.")

        verification = self.verifier.verify(
            observation.current_sql,
            suggestion.rewritten_sql,
            task.constraints,
            dialect=task.dialect,
        )
        if verification.status != VerificationStatus.PROVEN_EQUIVALENT:
            self._done = True
            transition = EnvironmentTransition(
                action=action,
                observation=observation,
                proposed_sql=suggestion.rewritten_sql,
                reward=_verification_failure_reward(verification.status),
                terminated=True,
                truncated=False,
                verification=verification,
                reason="Verifier did not prove the selected transition equivalent.",
            )
            self._record(task, observation, transition)
            return transition

        benchmark = (
            self.performance_evaluator.evaluate(
                observation.current_sql,
                suggestion.rewritten_sql,
            )
            if self.performance_evaluator is not None
            else None
        )
        next_step = observation.step_index + 1
        next_query = parse_select(suggestion.rewritten_sql, dialect=task.dialect)
        next_observation = self._observation_for(
            task=task,
            current_sql=suggestion.rewritten_sql,
            step_index=next_step,
            query=next_query,
        )
        truncated = next_step >= task.max_steps and bool(next_observation.actions)
        terminated = not next_observation.actions
        reward = _performance_reward(benchmark)
        reason = _transition_reason(benchmark, terminated, truncated)

        self._observation = next_observation
        self._done = terminated or truncated
        transition = EnvironmentTransition(
            action=action,
            observation=next_observation,
            proposed_sql=suggestion.rewritten_sql,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            verification=verification,
            benchmark=benchmark,
            reason=reason,
        )
        self._record(task, observation, transition)
        return transition

    @property
    def observation(self) -> EnvironmentObservation | None:
        return self._observation

    def _active_episode(self) -> tuple[EnvironmentTask, EnvironmentObservation]:
        if self._task is None or self._observation is None:
            raise RuntimeError("Call reset() before step().")
        if self._done:
            raise RuntimeError("The current episode is complete; call reset() before step().")
        if not self._observation.actions:
            raise RuntimeError("The current episode has terminated.")
        if self._observation.step_index >= self._task.max_steps:
            raise RuntimeError("The current episode has been truncated.")
        return self._task, self._observation

    def _observation_for(
        self,
        *,
        task: EnvironmentTask,
        current_sql: str,
        step_index: int,
        query,
    ) -> EnvironmentObservation:
        matches = available_rewrite_matches(query, task.constraints, rules=self.rules)
        actions = tuple(
            EnvironmentAction(
                action_id=f"{match.rule_name}::{match.match_id}",
                match=match,
            )
            for match in matches
        )
        return EnvironmentObservation(
            task_id=task.task_id,
            initial_sql=task.sql.strip(),
            current_sql=current_sql.strip(),
            dialect=task.dialect,
            step_index=step_index,
            actions=actions,
            metadata=task.metadata,
        )

    def _record(
        self,
        task: EnvironmentTask,
        before: EnvironmentObservation,
        transition: EnvironmentTransition,
    ) -> None:
        if self.trajectory_recorder is not None:
            self.trajectory_recorder.record(task, before, transition)


def _verification_failure_reward(status: VerificationStatus) -> float:
    if status == VerificationStatus.NOT_EQUIVALENT:
        return -1.0
    return -0.25


def _performance_reward(benchmark: BenchmarkResult | None) -> float:
    if (
        benchmark is None
        or benchmark.status != BenchmarkStatus.COMPLETED
        or benchmark.speedup is None
        or benchmark.speedup <= 0
        or not benchmark.timing_confident
    ):
        return 0.0
    return math.log(benchmark.speedup)


def _transition_reason(
    benchmark: BenchmarkResult | None,
    terminated: bool,
    truncated: bool,
) -> str | None:
    if truncated:
        return "Episode reached its maximum step count."
    if terminated:
        return "No further rewrite actions are available."
    if benchmark is not None and benchmark.status != BenchmarkStatus.COMPLETED:
        return "Rewrite was proven equivalent, but performance evaluation did not complete."
    return None
