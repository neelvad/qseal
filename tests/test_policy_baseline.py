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
from snowprove.corpus.trajectories import load_corpus_trajectory_records
from snowprove.policy import (
    PolicyDataFilter,
    compare_policy_holdouts,
    evaluate_baseline_policy,
    inspect_baseline_policy,
    inspect_policy_labels,
    render_policy_holdout_comparison,
    render_policy_label_inspection,
    train_baseline_policy,
    train_linear_policy,
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


def test_linear_policy_trains_and_evaluates_choice_states(tmp_path) -> None:
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

    model = train_linear_policy(trajectory_path, epochs=3)
    filtered_model = train_linear_policy(
        trajectory_path,
        epochs=3,
        training_margin=0.25,
    )
    evaluation = evaluate_baseline_policy(trajectory_path, model)
    inspection = inspect_baseline_policy(trajectory_path, model, mode="all")

    assert model.artifact_type == "linear_policy_model"
    assert model.model_type == "linear_action_ranker"
    assert model.choice_state_count == 1
    assert model.training_margin == 0.0
    assert model.unknown_preference_scale == 1.0
    assert model.update_count >= 1
    assert model.skipped_preference_count == 0
    assert model.skipped_unknown_preference_count == 0
    assert model.feature_weights
    feature_weights = {item.feature: item.weight for item in model.feature_weights}
    assert (
        "action_projection_columns:"
        "remove_redundant_not_null_filter::predicate:1:event_id+user_id"
        in feature_weights
    )
    assert (
        "action_not_null_columns:"
        "remove_redundant_not_null_filter::predicate:1:event_id+user_id"
        in feature_weights
    )
    assert (
        "rule_action_column:remove_redundant_not_null_filter:user_id"
        in feature_weights
    )
    assert "target_column:user_id" in feature_weights
    assert evaluation.correct_count == 1
    assert evaluation.accuracy == 1.0
    assert inspection.rows[0].predicted_action_id == second_predicate
    assert filtered_model.training_margin == 0.25
    assert filtered_model.update_count == 0
    assert filtered_model.skipped_preference_count == 3
    assert filtered_model.feature_weights == ()


def test_linear_policy_can_skip_unknown_reward_preferences(tmp_path) -> None:
    corpus = load_task_corpus(bundled_corpus_path())
    task = corpus.task("distinct-and-not-null")
    trajectory_path = tmp_path / "trajectories.jsonl"
    distinct_action = "remove_redundant_distinct::query:distinct"
    not_null_action = "remove_redundant_not_null_filter::predicate:0"
    export_corpus_trajectories(
        CorpusRunReport(
            generated_at=datetime.now(UTC),
            corpus_id=corpus.manifest.corpus_id,
            corpus_version=corpus.manifest.corpus_version,
            corpus_fingerprint=corpus.fingerprint,
            config=CorpusRunConfig(strategies=("fixed_order",)),
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
                            task.environment_task.sql,
                            distinct_action,
                            "SELECT user_id\nFROM users\nWHERE user_id IS NOT NULL;",
                            reward=0.2,
                        ),
                    ),
                ),
            ),
            strategy_summaries=(),
        ),
        corpus,
        trajectory_path,
    )

    model = train_linear_policy(
        trajectory_path,
        epochs=3,
        unknown_preference_scale=0.0,
    )
    group_key = (
        "action_set="
        "remove_redundant_distinct::query:distinct+"
        "remove_redundant_not_null_filter::predicate:0 | table=table:none"
    )
    group_skipped_model = train_linear_policy(
        trajectory_path,
        epochs=3,
        unknown_preference_scale=1.0,
        unknown_preference_group_scales={group_key: 0.0},
    )

    assert model.choice_state_count == 1
    assert model.unknown_preference_scale == 0.0
    assert model.update_count == 0
    assert model.skipped_unknown_preference_count == 3
    assert model.feature_weights == ()
    assert group_skipped_model.unknown_preference_scale == 1.0
    assert group_skipped_model.unknown_preference_group_by == ("action_set", "table")
    assert group_skipped_model.unknown_preference_group_scales == {group_key: 0.0}
    assert group_skipped_model.update_count == 0
    assert group_skipped_model.skipped_unknown_preference_count == 3
    assert group_skipped_model.feature_weights == ()
    assert not_null_action in next(
        record.available_action_ids
        for record in load_corpus_trajectory_records(trajectory_path)
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


def test_compares_policy_holdout_evaluations(tmp_path) -> None:
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
    evaluation = evaluate_baseline_policy(
        trajectory_path,
        train_baseline_policy(trajectory_path),
    )
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(
        PolicyHoldoutEvaluation(
            generated_at=datetime.now(UTC),
            source_trajectories=str(trajectory_path),
            train_filter=PolicyDataFilter(),
            holdout_filter=PolicyDataFilter(include_tags=("multi-action",)),
            trained_state_count=1,
            heldout_state_count=1,
            offline_evaluation=evaluation,
            corpus_report_path="/tmp/corpus-run.json",
            heldout_task_ids=(task.definition.task_id,),
            strategy_rewards={"greedy": 1.0, "policy_baseline_abstain": 0.9},
            strategy_wins={"greedy": 1, "policy_baseline_abstain": 0},
            strategy_benchmark_requests={"greedy": 4, "policy_baseline_abstain": 2},
            strategy_verifier_requests={"greedy": 3, "policy_baseline_abstain": 1},
        ).model_dump_json(indent=2)
    )
    second_path.write_text(
        PolicyHoldoutEvaluation(
            generated_at=datetime.now(UTC),
            source_trajectories=str(trajectory_path),
            train_filter=PolicyDataFilter(),
            holdout_filter=PolicyDataFilter(include_tags=("multi-action",)),
            trained_state_count=1,
            heldout_state_count=1,
            offline_evaluation=evaluation,
            corpus_report_path="/tmp/corpus-run.json",
            heldout_task_ids=(task.definition.task_id,),
            strategy_rewards={"greedy": 1.0, "policy_baseline_abstain": 1.1},
            strategy_wins={"greedy": 1, "policy_baseline_abstain": 1},
            strategy_benchmark_requests={"greedy": 4, "policy_baseline_abstain": 3},
            strategy_verifier_requests={"greedy": 3, "policy_baseline_abstain": 2},
        ).model_dump_json(indent=2)
    )

    comparison = compare_policy_holdouts(
        (first_path, second_path),
        labels=("default", "scaled"),
    )
    rendered = render_policy_holdout_comparison(comparison)

    assert comparison.artifact_type == "policy_holdout_comparison"
    assert comparison.baseline_label == "default"
    assert abs(comparison.rows[0].reward_delta_vs_greedy + 0.1) < 0.000001
    assert comparison.rows[0].oracle_request_delta_vs_greedy == -4
    assert abs(comparison.rows[1].reward_delta_vs_greedy - 0.1) < 0.000001
    assert comparison.rows[1].win_delta_vs_greedy == 0
    assert "Policy holdout comparison" in rendered
    assert "default" in rendered
    assert "scaled" in rendered


def test_policy_label_inspection_groups_train_holdout_disagreements(tmp_path) -> None:
    corpus = load_task_corpus(bundled_corpus_path())
    train_task = corpus.task("choice-distinct-not-null-active-users-standard-small")
    holdout_task = corpus.task("distinct-and-not-null")
    trajectory_path = tmp_path / "trajectories.jsonl"
    distinct_action = "remove_redundant_distinct::query:distinct"
    not_null_action = "remove_redundant_not_null_filter::predicate:0"
    train_report = _report(
        corpus,
        train_task.definition.task_id,
        train_task.fingerprint,
        train_task.fixture.fixture_id,
        train_task.definition.enabled_rules,
        train_task.definition.tags,
        train_task.environment_task.sql,
        distinct_action,
        not_null_action,
        first_reward=0.3,
        second_reward=0.1,
    )
    holdout_report = _report(
        corpus,
        holdout_task.definition.task_id,
        holdout_task.fingerprint,
        holdout_task.fixture.fixture_id,
        holdout_task.definition.enabled_rules,
        holdout_task.definition.tags,
        holdout_task.environment_task.sql,
        distinct_action,
        not_null_action,
        first_reward=0.1,
        second_reward=0.3,
    )
    export_corpus_trajectories(
        CorpusRunReport(
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
            tasks=(train_report.tasks[0], holdout_report.tasks[0]),
            strategy_summaries=(),
        ),
        corpus,
        trajectory_path,
    )

    inspection = inspect_policy_labels(
        trajectory_path,
        train_filter=PolicyDataFilter(include_tags=("choice-calibration",)),
        holdout_filter=PolicyDataFilter(include_tags=("multi-action",)),
        group_by=("action_set",),
        reward_margin=0.05,
    )
    rendered = render_policy_label_inspection(inspection)

    assert inspection.artifact_type == "policy_label_inspection"
    assert inspection.train_preference_count == 1
    assert inspection.holdout_preference_count == 1
    assert inspection.train_preferences == {distinct_action: 1}
    assert inspection.holdout_preferences == {not_null_action: 1}
    assert inspection.disagreement_group_count == 1
    assert inspection.train_only_group_count == 0
    assert inspection.holdout_only_group_count == 0
    assert inspection.groups[0].coverage_status == "matched"
    assert inspection.groups[0].disagreement_count == 1
    assert inspection.groups[0].train_preferences == {distinct_action: 1}
    assert inspection.groups[0].holdout_preferences == {not_null_action: 1}
    assert inspection.groups[0].train_majority_preference == distinct_action
    assert inspection.groups[0].holdout_majority_preference == not_null_action
    assert inspection.groups[0].train_majority_ratio == 1.0
    assert inspection.groups[0].holdout_majority_ratio == 1.0
    assert inspection.groups[0].examples[0].reward_gap is not None
    assert "Policy label inspection" in rendered
    assert "Disagreement groups: 1" in rendered
    assert "Global train prefs:" in rendered


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
