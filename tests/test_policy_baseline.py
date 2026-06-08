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
from snowprove.policy import (
    PolicyDataFilter,
    evaluate_baseline_policy,
    inspect_baseline_policy,
    train_baseline_policy,
)
from snowprove.policy.baseline import (
    PolicyHoldoutEvaluation,
    render_baseline_policy_inspection,
    render_policy_holdout_evaluation,
)
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
    assert any(
        stat.feature
        == (
            "available_rules:"
            "remove_redundant_distinct+remove_redundant_not_null_filter"
        )
        for stat in model.feature_stats
    )
    assert any(
        stat.feature
        == "competes_with:remove_redundant_not_null_filter:remove_redundant_distinct"
        and stat.win_rate == 1.0
        for stat in model.feature_stats
    )
    assert evaluation.artifact_type == "baseline_policy_evaluation"
    assert evaluation.predicted_state_count == 1
    assert evaluation.correct_count == 1
    assert evaluation.acceptable_count == 1
    assert evaluation.accuracy == 1.0
    assert evaluation.adjusted_accuracy == 1.0
    assert evaluation.known_reward_gap_count == 1
    assert evaluation.mean_known_reward_gap == 0.0


def test_baseline_policy_features_include_same_rule_action_context(tmp_path) -> None:
    corpus = load_task_corpus(bundled_corpus_path())
    task = corpus.task("double-not-null-events-standard-medium")
    trajectory_path = tmp_path / "trajectories.jsonl"
    first_predicate = "remove_redundant_not_null_filter::predicate:0"
    second_predicate = "remove_redundant_not_null_filter::predicate:1"
    export_corpus_trajectories(
        _report(
            corpus,
            task.definition.task_id,
            task.fingerprint,
            task.fixture.fixture_id,
            task.definition.enabled_rules,
            task.definition.tags,
            task.environment_task.sql,
            first_predicate,
            second_predicate,
            first_rewrite_sql=(
                "SELECT event_id, user_id\n"
                "FROM events\n"
                "WHERE user_id IS NOT NULL;"
            ),
            second_rewrite_sql=(
                "SELECT event_id, user_id\n"
                "FROM events\n"
                "WHERE event_id IS NOT NULL;"
            ),
            first_reward=0.1,
            second_reward=0.3,
        ),
        corpus,
        trajectory_path,
    )

    model = train_baseline_policy(trajectory_path)

    stats = {stat.feature: stat for stat in model.feature_stats}
    assert (
        stats["same_rule_count:remove_redundant_not_null_filter:2"].appearances
        == 2
    )
    assert (
        stats["same_rule_position:remove_redundant_not_null_filter:1"].oracle_count
        == 1
    )
    assert (
        stats["rule_target_index:remove_redundant_not_null_filter:1"].win_rate
        == 1.0
    )


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


def test_baseline_policy_adjusted_accuracy_accepts_margin_gap(tmp_path) -> None:
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

    strict = evaluate_baseline_policy(trajectory_path, model, reward_margin=0.0)
    adjusted = evaluate_baseline_policy(trajectory_path, model, reward_margin=0.5)

    assert strict.correct_count == 0
    assert strict.acceptable_count == 0
    assert strict.accuracy == 0.0
    assert strict.adjusted_accuracy == 0.0
    assert adjusted.correct_count == 0
    assert adjusted.acceptable_count == 1
    assert adjusted.accuracy == 0.0
    assert adjusted.adjusted_accuracy == 1.0


def test_baseline_policy_inspection_reports_misses_and_unacceptable_rows(tmp_path) -> None:
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

    misses = inspect_baseline_policy(trajectory_path, model, reward_margin=0.0)
    acceptable = inspect_baseline_policy(
        trajectory_path,
        model,
        reward_margin=0.5,
        mode="unacceptable",
    )
    rendered = render_baseline_policy_inspection(misses)

    assert misses.artifact_type == "baseline_policy_inspection"
    assert misses.state_count == 1
    assert misses.predicted_state_count == 1
    assert misses.miss_count == 1
    assert misses.unacceptable_count == 1
    assert misses.row_count == 1
    assert misses.rows[0].task_id == task.definition.task_id
    assert misses.rows[0].oracle_action_id == not_null_action
    assert misses.rows[0].predicted_action_id == distinct_action
    assert misses.rows[0].reward_gap is not None
    assert abs(misses.rows[0].reward_gap - 0.2) < 0.000001
    assert set(misses.rows[0].action_scores) == {distinct_action, not_null_action}
    assert acceptable.row_count == 0
    assert "Baseline policy inspection" in rendered
    assert "Reward gap: 0.200000" in rendered


def test_renders_policy_holdout_evaluation(tmp_path) -> None:
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
    holdout = PolicyHoldoutEvaluation(
        generated_at=model.generated_at,
        source_trajectories=str(trajectory_path),
        train_filter=PolicyDataFilter(exclude_fixtures=("standard-small",)),
        holdout_filter=PolicyDataFilter(include_fixtures=("standard-small",)),
        trained_state_count=0,
        heldout_state_count=evaluation.labeled_state_count,
        offline_evaluation=evaluation,
        corpus_report_path="/tmp/corpus-run.json",
        heldout_task_ids=(task.definition.task_id,),
        strategy_rewards={"greedy": 1.0, "policy_baseline_abstain": 1.0},
        strategy_wins={"greedy": 1, "policy_baseline_abstain": 1},
        strategy_benchmark_requests={"greedy": 2, "policy_baseline_abstain": 1},
        strategy_verifier_requests={"greedy": 2, "policy_baseline_abstain": 1},
    )

    rendered = render_policy_holdout_evaluation(holdout)

    assert holdout.artifact_type == "policy_holdout_evaluation"
    assert "Policy holdout evaluation" in rendered
    assert "policy_baseline_abstain" in rendered


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
    *,
    first_rewrite_sql: str = "SELECT user_id\nFROM users\nWHERE user_id IS NOT NULL;",
    second_rewrite_sql: str = "SELECT DISTINCT user_id\nFROM users;",
    first_reward: float = 0.1,
    second_reward: float = 0.3,
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
                        first_rewrite_sql,
                        reward=first_reward,
                    ),
                    _result(
                        "greedy",
                        task_id,
                        initial_sql,
                        not_null_action,
                        second_rewrite_sql,
                        reward=second_reward,
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
