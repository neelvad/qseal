import math

import pytest

from snowprove.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
)
from snowprove.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints
from snowprove.environment import (
    DuckDbPerformanceEvaluator,
    EnvironmentTask,
    RewriteEnvironment,
)
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.model import VerificationResult


def _task(*, max_steps: int = 8) -> EnvironmentTask:
    return EnvironmentTask(
        task_id="remove-null-filters",
        sql=(
            "SELECT user_id FROM users "
            "WHERE email IS NOT NULL AND display_name IS NOT NULL"
        ),
        constraints=ConstraintCatalog(
            tables={
                "users": TableConstraints(
                    columns={
                        "email": ColumnConstraint(nullable=False),
                        "display_name": ColumnConstraint(nullable=False),
                    }
                )
            }
        ),
        max_steps=max_steps,
        metadata={"fixture": "unit"},
    )


def test_reset_returns_deterministic_action_space() -> None:
    environment = RewriteEnvironment()

    observation = environment.reset(_task())

    assert observation.task_id == "remove-null-filters"
    assert observation.step_index == 0
    assert observation.metadata == {"fixture": "unit"}
    assert [action.action_id for action in observation.actions] == [
        "remove_redundant_not_null_filter::predicate:0",
        "remove_redundant_not_null_filter::predicate:1",
    ]


def test_step_applies_actions_until_episode_terminates() -> None:
    environment = RewriteEnvironment()
    observation = environment.reset(_task())

    first = environment.step(observation.actions[0].action_id)

    assert first.verification.status == VerificationStatus.PROVEN_EQUIVALENT
    assert first.reward == 0
    assert first.terminated is False
    assert first.truncated is False
    assert first.observation.step_index == 1
    assert first.observation.current_sql == (
        "SELECT user_id\nFROM users\nWHERE display_name IS NOT NULL;"
    )
    assert [action.action_id for action in first.observation.actions] == [
        "remove_redundant_not_null_filter::predicate:0"
    ]

    second = environment.step(first.observation.actions[0].action_id)

    assert second.terminated is True
    assert second.truncated is False
    assert second.reason == "No further rewrite actions are available."
    assert second.observation.current_sql == "SELECT user_id\nFROM users;"
    assert second.observation.actions == ()
    with pytest.raises(RuntimeError, match="episode is complete"):
        environment.step(first.observation.actions[0].action_id)


def test_step_truncates_at_maximum_episode_length() -> None:
    environment = RewriteEnvironment()
    observation = environment.reset(_task(max_steps=1))

    transition = environment.step(observation.actions[0].action_id)

    assert transition.terminated is False
    assert transition.truncated is True
    assert transition.observation.actions
    assert transition.reason == "Episode reached its maximum step count."


def test_step_rejects_unproven_transition_without_advancing_state() -> None:
    verifier = _RejectingVerifier()
    environment = RewriteEnvironment(verifier=verifier)
    observation = environment.reset(_task())

    transition = environment.step(observation.actions[0].action_id)

    assert transition.reward == -1
    assert transition.terminated is True
    assert transition.observation == observation
    assert transition.proposed_sql == (
        "SELECT user_id\nFROM users\nWHERE display_name IS NOT NULL;"
    )
    assert transition.verification.status == VerificationStatus.NOT_EQUIVALENT
    with pytest.raises(RuntimeError, match="episode is complete"):
        environment.step(observation.actions[0].action_id)


def test_step_uses_log_speedup_reward() -> None:
    evaluator = _FixedPerformanceEvaluator(speedup=2.0)
    environment = RewriteEnvironment(performance_evaluator=evaluator)
    observation = environment.reset(_task())

    transition = environment.step(observation.actions[0].action_id)

    assert transition.benchmark is not None
    assert transition.reward == pytest.approx(math.log(2))
    assert evaluator.calls == [
        (
            observation.current_sql,
            transition.observation.current_sql,
        )
    ]


def test_step_neutralizes_low_confidence_speedup() -> None:
    evaluator = _FixedPerformanceEvaluator(speedup=2.0, timing_confident=False)
    environment = RewriteEnvironment(performance_evaluator=evaluator)
    observation = environment.reset(_task())

    transition = environment.step(observation.actions[0].action_id)

    assert transition.benchmark is not None
    assert transition.benchmark.speedup == 2.0
    assert transition.benchmark.timing_confident is False
    assert transition.reward == 0.0


def test_environment_requires_reset_and_available_action() -> None:
    environment = RewriteEnvironment()

    with pytest.raises(RuntimeError, match=r"Call reset\(\)"):
        environment.step("missing")

    environment.reset(_task())
    with pytest.raises(ValueError, match="not available"):
        environment.step("missing")


def test_environment_can_use_real_duckdb_performance_evaluator() -> None:
    task = EnvironmentTask(
        task_id="distinct",
        sql="SELECT DISTINCT user_id FROM users",
        constraints=ConstraintCatalog(
            tables={"users": TableConstraints(unique=[("user_id",)])}
        ),
    )
    environment = RewriteEnvironment(
        performance_evaluator=DuckDbPerformanceEvaluator(
            setup_sql=(
                "CREATE TABLE users AS "
                "SELECT value AS user_id FROM range(1000) AS values(value)"
            ),
            warmups=0,
            repetitions=1,
            timeout_seconds=5,
        )
    )
    observation = environment.reset(task)

    transition = environment.step(observation.actions[0].action_id)

    assert transition.verification.status == VerificationStatus.PROVEN_EQUIVALENT
    assert transition.benchmark is not None
    assert transition.benchmark.status == BenchmarkStatus.COMPLETED
    assert math.isfinite(transition.reward)


class _RejectingVerifier:
    name = "rejecting"

    def verify(self, original_sql, rewritten_sql, constraints, dialect="duckdb"):
        del constraints, dialect
        return VerificationResult(
            status=VerificationStatus.NOT_EQUIVALENT,
            original_sql=original_sql,
            rewritten_sql=rewritten_sql,
            rule_name=self.name,
            reason="Rejected for testing.",
        )


class _FixedPerformanceEvaluator:
    def __init__(self, speedup: float, *, timing_confident: bool = True) -> None:
        self.speedup = speedup
        self.timing_confident = timing_confident
        self.calls: list[tuple[str, str]] = []

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        self.calls.append((original_sql, rewritten_sql))
        environment = BenchmarkEnvironment(
            duckdb_version="test",
            python_version="test",
            platform="test",
            database_path=":memory:",
            threads=1,
            warmups=0,
            repetitions=1,
            timeout_seconds=1,
        )
        return BenchmarkResult(
            status=BenchmarkStatus.COMPLETED,
            original=QueryBenchmark(
                status=BenchmarkStatus.COMPLETED,
                sql=original_sql,
                timings_ms=(self.speedup,),
                median_ms=self.speedup,
                row_count=1,
            ),
            rewritten=QueryBenchmark(
                status=BenchmarkStatus.COMPLETED,
                sql=rewritten_sql,
                timings_ms=(1.0,),
                median_ms=1.0,
                row_count=1,
            ),
            environment=environment,
            speedup=self.speedup,
            row_counts_match=True,
            timing_confident=self.timing_confident,
            confidence_reason=(
                None if self.timing_confident else "Synthetic timing below duration floor."
            ),
        )
