from datetime import UTC, datetime

from qseal.corpora import bundled_corpus_path
from qseal.corpus import (
    CorpusRunConfig,
    CorpusRunEnvironment,
    CorpusRunReport,
    CorpusTaskRun,
    OracleCallMetrics,
    StrategyRunResult,
    export_corpus_trajectories,
    load_corpus_trajectory_records,
    load_task_corpus,
)
from qseal.rewrites.base import VerificationStatus
from qseal.search import SearchResult, SearchStep


def test_exports_state_and_task_oracle_labels(tmp_path) -> None:
    corpus = load_task_corpus(bundled_corpus_path())
    task = corpus.task("distinct-and-not-null")
    initial_sql = task.environment_task.sql
    distinct_action = "remove_redundant_distinct::query:distinct"
    not_null_action = "remove_redundant_not_null_filter::predicate:0"
    report = CorpusRunReport(
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
                task_id=task.definition.task_id,
                task_fingerprint=task.fingerprint,
                fixture_id=task.fixture.fixture_id,
                enabled_rules=task.definition.enabled_rules,
                tags=task.definition.tags,
                results=(
                    _result(
                        "fixed_order",
                        task.definition.task_id,
                        initial_sql,
                        distinct_action,
                        "SELECT user_id\nFROM users\nWHERE user_id IS NOT NULL;",
                        reward=0.1,
                    ),
                    _result(
                        "greedy",
                        task.definition.task_id,
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
    output_path = tmp_path / "trajectories.jsonl"

    export = export_corpus_trajectories(report, corpus, output_path)

    assert export.record_count == 2
    assert export.state_count == 1
    assert export.labeled_state_count == 1
    records = load_corpus_trajectory_records(output_path)
    assert {
        record.action_id: record.is_state_oracle_best_action for record in records
    } == {
        distinct_action: False,
        not_null_action: True,
    }
    assert all(
        record.available_action_ids == (distinct_action, not_null_action)
        for record in records
    )
    assert all(record.task_oracle_strategy == "greedy" for record in records)
    assert all(record.task_oracle_action_ids == (not_null_action,) for record in records)


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
