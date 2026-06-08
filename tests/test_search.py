import math

import pytest

from snowprove.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
)
from snowprove.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints
from snowprove.environment import EnvironmentTask, RewriteEnvironment
from snowprove.search import (
    beam_search,
    exhaustive_search,
    fixed_order_search,
    greedy_search,
    policy_baseline_abstain_search,
    policy_baseline_search,
    random_search,
)

INITIAL_SQL = (
    "SELECT user_id FROM users "
    "WHERE email IS NOT NULL AND display_name IS NOT NULL"
)
EMAIL_REMOVED_SQL = "SELECT user_id\nFROM users\nWHERE display_name IS NOT NULL;"
DISPLAY_NAME_REMOVED_SQL = "SELECT user_id\nFROM users\nWHERE email IS NOT NULL;"
FINAL_SQL = "SELECT user_id\nFROM users;"


def _task(*, max_steps: int = 8) -> EnvironmentTask:
    return EnvironmentTask(
        task_id="search-null-filters",
        sql=INITIAL_SQL,
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
    )


def _factory(rewards=None):
    evaluator = _MappedPerformanceEvaluator(
        rewards
        or {
            (INITIAL_SQL, EMAIL_REMOVED_SQL): 1.1,
            (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 2.0,
            (EMAIL_REMOVED_SQL, FINAL_SQL): 1.1,
            (DISPLAY_NAME_REMOVED_SQL, FINAL_SQL): 1.1,
        }
    )

    def create() -> RewriteEnvironment:
        return RewriteEnvironment(performance_evaluator=evaluator)

    return create


def test_fixed_order_follows_registry_action_order() -> None:
    result = fixed_order_search(_task(), _factory())

    assert result.strategy == "fixed_order"
    assert result.action_ids == (
        "remove_redundant_not_null_filter::predicate:0",
        "remove_redundant_not_null_filter::predicate:0",
    )
    assert result.final_sql == FINAL_SQL
    assert result.terminated is True
    assert result.explored_nodes == 2
    assert result.cumulative_reward == pytest.approx(2 * math.log(1.1))


def test_random_search_is_reproducible_for_a_seed() -> None:
    first = random_search(_task(), _factory(), seed=7)
    second = random_search(_task(), _factory(), seed=7)

    assert first.action_ids == second.action_ids
    assert first.final_sql == second.final_sql
    assert first.cumulative_reward == second.cumulative_reward
    assert first.seed == 7


def test_policy_baseline_search_follows_highest_scored_action() -> None:
    result = policy_baseline_search(
        _task(),
        _factory(),
        lambda _observation, action_id: (
            1.0 if action_id == "remove_redundant_not_null_filter::predicate:1" else 0.0
        ),
    )

    assert result.strategy == "policy_baseline"
    assert result.action_ids[0] == "remove_redundant_not_null_filter::predicate:1"
    assert result.final_sql == FINAL_SQL
    assert result.explored_nodes == 3


def test_policy_baseline_abstain_search_stops_when_top_action_does_not_improve() -> None:
    result = policy_baseline_abstain_search(
        _task(),
        _factory(
            {
                (INITIAL_SQL, EMAIL_REMOVED_SQL): 0.9,
                (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 2.0,
            }
        ),
        lambda _observation, action_id: (
            1.0 if action_id == "remove_redundant_not_null_filter::predicate:0" else 0.0
        ),
    )

    assert result.strategy == "policy_baseline_abstain"
    assert result.action_ids == ()
    assert result.stopped_early is True
    assert result.explored_nodes == 1


def test_policy_baseline_abstain_search_takes_good_top_action() -> None:
    result = policy_baseline_abstain_search(
        _task(),
        _factory(),
        lambda _observation, action_id: (
            1.0 if action_id == "remove_redundant_not_null_filter::predicate:1" else 0.0
        ),
    )

    assert result.strategy == "policy_baseline_abstain"
    assert result.action_ids[0] == "remove_redundant_not_null_filter::predicate:1"
    assert result.final_sql == FINAL_SQL
    assert result.explored_nodes == 2


def test_greedy_selects_highest_immediate_reward() -> None:
    result = greedy_search(_task(), _factory())

    assert result.action_ids[0] == (
        "remove_redundant_not_null_filter::predicate:1"
    )
    assert result.final_sql == FINAL_SQL
    assert result.cumulative_reward == pytest.approx(math.log(2) + math.log(1.1))
    assert result.explored_nodes == 3


def test_greedy_stops_when_no_action_improves_reward() -> None:
    result = greedy_search(
        _task(),
        _factory(
            {
                (INITIAL_SQL, EMAIL_REMOVED_SQL): 0.9,
                (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 0.8,
            }
        ),
    )

    assert result.action_ids == ()
    assert result.final_sql == INITIAL_SQL
    assert result.cumulative_reward == 0
    assert result.terminated is False
    assert result.stopped_early is True
    assert result.explored_nodes == 2


def test_greedy_requires_improvement_beyond_reward_margin() -> None:
    result = greedy_search(
        _task(),
        _factory(
            {
                (INITIAL_SQL, EMAIL_REMOVED_SQL): 1.02,
                (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 1.03,
            }
        ),
        reward_margin=0.05,
    )

    assert result.action_ids == ()
    assert result.stopped_early is True
    assert result.reward_margin == 0.05


def test_greedy_endpoint_policy_accepts_terminal_ties_within_margin() -> None:
    result = greedy_search(
        _task(),
        _factory(
            {
                (INITIAL_SQL, EMAIL_REMOVED_SQL): 2.0,
                (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 1.0,
                (EMAIL_REMOVED_SQL, FINAL_SQL): 1.02,
            }
        ),
        reward_margin=0.05,
        tie_policy="endpoint",
    )

    assert result.action_ids == (
        "remove_redundant_not_null_filter::predicate:0",
        "remove_redundant_not_null_filter::predicate:0",
    )
    assert result.final_sql == FINAL_SQL
    assert result.stopped_early is False
    assert result.tie_policy == "endpoint"


def test_greedy_endpoint_policy_rejects_materially_worse_endpoint() -> None:
    result = greedy_search(
        _task(),
        _factory(
            {
                (INITIAL_SQL, EMAIL_REMOVED_SQL): 2.0,
                (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 1.0,
                (EMAIL_REMOVED_SQL, FINAL_SQL): 0.90,
            }
        ),
        reward_margin=0.05,
        tie_policy="endpoint",
    )

    assert result.action_ids == ("remove_redundant_not_null_filter::predicate:0",)
    assert result.final_sql == EMAIL_REMOVED_SQL
    assert result.stopped_early is True


def test_beam_search_finds_best_complete_path() -> None:
    result = beam_search(_task(), _factory(), beam_width=2)

    assert result.strategy == "beam"
    assert result.beam_width == 2
    assert result.final_sql == FINAL_SQL
    assert result.action_ids[0].endswith("predicate:1")
    assert result.cumulative_reward == pytest.approx(math.log(2) + math.log(1.1))
    assert result.explored_nodes == 4


def test_exhaustive_search_finds_best_path_and_deduplicates_final_sql() -> None:
    result = exhaustive_search(_task(), _factory(), max_nodes=20)

    assert result.strategy == "exhaustive"
    assert result.max_nodes == 20
    assert result.search_truncated is False
    assert result.final_sql == FINAL_SQL
    assert result.action_ids[0].endswith("predicate:1")
    assert result.cumulative_reward == pytest.approx(math.log(2) + math.log(1.1))
    assert result.explored_nodes == 4


@pytest.mark.parametrize("search", [beam_search, exhaustive_search])
def test_search_prefers_shorter_path_within_reward_margin(search) -> None:
    kwargs = {"beam_width": 2} if search is beam_search else {"max_nodes": 20}
    result = search(
        _task(max_steps=1),
        _factory(
            {
                (INITIAL_SQL, EMAIL_REMOVED_SQL): 1.02,
                (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 1.03,
            }
        ),
        reward_margin=0.05,
        **kwargs,
    )

    assert result.action_ids == ()
    assert result.final_sql == INITIAL_SQL
    assert result.reward_margin == 0.05


@pytest.mark.parametrize("search", [beam_search, exhaustive_search])
def test_endpoint_policy_prefers_complete_path_within_reward_margin(search) -> None:
    kwargs = {"beam_width": 2} if search is beam_search else {"max_nodes": 20}
    result = search(
        _task(max_steps=1),
        _factory(
            {
                (INITIAL_SQL, EMAIL_REMOVED_SQL): 1.02,
                (INITIAL_SQL, DISPLAY_NAME_REMOVED_SQL): 1.03,
            }
        ),
        reward_margin=0.05,
        tie_policy="endpoint",
        **kwargs,
    )

    assert result.action_ids in (
        ("remove_redundant_not_null_filter::predicate:0",),
        ("remove_redundant_not_null_filter::predicate:1",),
    )
    assert result.final_sql in (EMAIL_REMOVED_SQL, DISPLAY_NAME_REMOVED_SQL)
    assert result.reward_margin == 0.05
    assert result.tie_policy == "endpoint"


def test_exhaustive_search_reports_node_limit() -> None:
    result = exhaustive_search(_task(), _factory(), max_nodes=1)

    assert result.search_truncated is True
    assert result.explored_nodes == 1


@pytest.mark.parametrize(
    ("search", "kwargs", "message"),
    [
        (beam_search, {"beam_width": 0}, "beam_width"),
        (exhaustive_search, {"max_nodes": 0}, "max_nodes"),
        (greedy_search, {"reward_margin": -0.1}, "reward_margin"),
        (greedy_search, {"tie_policy": "unknown"}, "tie policy"),
    ],
)
def test_search_rejects_invalid_limits(search, kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        search(_task(), _factory(), **kwargs)


class _MappedPerformanceEvaluator:
    def __init__(self, speedups: dict[tuple[str, str], float]) -> None:
        self.speedups = speedups

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        speedup = self.speedups.get((original_sql, rewritten_sql), 1.0)
        environment = BenchmarkEnvironment(
            duckdb_version="test",
            python_version="test",
            platform="test",
            database_path="fixture.duckdb",
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
                timings_ms=(speedup,),
                median_ms=speedup,
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
            speedup=speedup,
            row_counts_match=True,
        )
