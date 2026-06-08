from datetime import UTC, datetime

from snowprove.corpora import bundled_corpus_path
from snowprove.corpus import (
    CorpusRunConfig,
    CorpusRunEnvironment,
    CorpusRunReport,
    CorpusTaskRun,
    OracleCallMetrics,
    StrategyRunResult,
    export_corpus_trajectories,
    load_task_corpus,
)
from snowprove.policy import PolicyDataFilter, evaluate_baseline_policy, train_baseline_policy
from snowprove.rewrites.base import VerificationStatus
from snowprove.search import SearchResult, SearchStep


def test_baseline_policy_trains_and_evaluates_state_oracle_actions(tmp_path) -> None:
    corpus = load_task_corpus(bundled_corpus_path())
    task = corpus.task("distinct-and-not-null")
    trajectory_path = tmp_path / "trajectories.jsonl"
    distinct_action = "remove_redundant_distinct::query:distinct"
    not_null_action = "remove_redundant_not_null_filter::predicate:0"
    export_corpus_trajectories(
        _report(
            corpus,
            task.definition.task_id,
            task.fingerprint,
            task.fixture.fixture_id,
            task.definition.enabled_rules,
            task.definition.tags,
            task.environment_task.sql,
            distinct_action,
            not_null_action,
        ),
        corpus,
        trajectory_path,
    )

    model = train_baseline_policy(trajectory_path)
    evaluation = evaluate_baseline_policy(trajectory_path, model)

    assert model.artifact_type == "baseline_policy_model"
    assert model.state_count == 1
    assert model.labeled_state_count == 1
    assert any(
        stat.feature == f"action:{not_null_action}" and stat.win_rate == 1.0
        for stat in model.feature_stats
    )
    assert evaluation.artifact_type == "baseline_policy_evaluation"
    assert evaluation.predicted_state_count == 1
    assert evaluation.correct_count == 1
    assert evaluation.accuracy == 1.0
    assert evaluation.known_reward_gap_count == 1
    assert evaluation.mean_known_reward_gap == 0.0


def test_baseline_policy_filters_train_and_evaluation_splits(tmp_path) -> None:
    corpus = load_task_corpus(bundled_corpus_path())
    task = corpus.task("distinct-and-not-null")
    trajectory_path = tmp_path / "trajectories.jsonl"
    distinct_action = "remove_redundant_distinct::query:distinct"
    not_null_action = "remove_redundant_not_null_filter::predicate:0"
    export_corpus_trajectories(
        _report(
            corpus,
            task.definition.task_id,
            task.fingerprint,
            task.fixture.fixture_id,
            task.definition.enabled_rules,
            task.definition.tags,
            task.environment_task.sql,
            distinct_action,
            not_null_action,
        ),
        corpus,
        trajectory_path,
    )

    model = train_baseline_policy(
        trajectory_path,
        data_filter=PolicyDataFilter(exclude_fixtures=("standard-small",)),
    )
    evaluation = evaluate_baseline_policy(
        trajectory_path,
        model,
        data_filter=PolicyDataFilter(include_fixtures=("standard-small",)),
    )
    excluded = evaluate_baseline_policy(
        trajectory_path,
        model,
        data_filter=PolicyDataFilter(exclude_tags=("multi-action",)),
    )

    assert model.state_count == 0
    assert model.data_filter.exclude_fixtures == ("standard-small",)
    assert evaluation.state_count == 1
    assert evaluation.data_filter.include_fixtures == ("standard-small",)
    assert evaluation.predicted_state_count == 1
    assert excluded.state_count == 0


def _report(
    corpus,
    task_id: str,
    task_fingerprint: str,
    fixture_id: str,
    enabled_rules: tuple[str, ...],
    tags: tuple[str, ...],
    initial_sql: str,
    distinct_action: str,
    not_null_action: str,
) -> CorpusRunReport:
    return CorpusRunReport(
        generated_at=datetime.now(UTC),
        corpus_id=corpus.manifest.corpus_id,
        corpus_version=corpus.manifest.corpus_version,
        corpus_fingerprint=corpus.fingerprint,
        config=CorpusRunConfig(strategies=("fixed_order", "greedy")),
        environment=CorpusRunEnvironment(
            python_version="test",
            duckdb_version="test",
            platform="test",
        ),
        tasks=(
            CorpusTaskRun(
                task_id=task_id,
                task_fingerprint=task_fingerprint,
                fixture_id=fixture_id,
                enabled_rules=enabled_rules,
                tags=tags,
                results=(
                    _result(
                        "fixed_order",
                        task_id,
                        initial_sql,
                        distinct_action,
                        "SELECT user_id\nFROM users\nWHERE user_id IS NOT NULL;",
                        reward=0.1,
                    ),
                    _result(
                        "greedy",
                        task_id,
                        initial_sql,
                        not_null_action,
                        "SELECT DISTINCT user_id\nFROM users;",
                        reward=0.3,
                    ),
                ),
            ),
        ),
        strategy_summaries=(),
    )


def _result(
    strategy: str,
    task_id: str,
    initial_sql: str,
    action_id: str,
    next_sql: str,
    *,
    reward: float,
) -> StrategyRunResult:
    return StrategyRunResult(
        strategy=strategy,
        status="COMPLETED",
        elapsed_seconds=0.1,
        verification_calls=_calls(),
        benchmark_calls=_calls(),
        search_result=SearchResult(
            strategy=strategy,
            task_id=task_id,
            initial_sql=initial_sql,
            final_sql=next_sql,
            action_ids=(action_id,),
            steps=(
                SearchStep(
                    step_index=0,
                    action_id=action_id,
                    state_sql=initial_sql,
                    proposed_sql=next_sql,
                    next_sql=next_sql,
                    reward=reward,
                    cumulative_reward=reward,
                    verification_status=VerificationStatus.PROVEN_EQUIVALENT,
                    terminated=True,
                    truncated=False,
                ),
            ),
            cumulative_reward=reward,
            terminated=True,
            truncated=False,
            explored_nodes=1,
        ),
    )


def _calls() -> OracleCallMetrics:
    return OracleCallMetrics(
        requests=0,
        cache_hits=0,
        cache_misses=0,
    )
