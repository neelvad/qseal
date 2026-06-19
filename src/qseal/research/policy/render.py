from __future__ import annotations

from qseal.research.policy.model import (
    BaselinePolicyEvaluation,
    BaselinePolicyInspection,
    BaselinePolicyModel,
    LinearPolicyModel,
    PolicyDataFilter,
    PolicyHoldoutComparison,
    PolicyHoldoutEvaluation,
    PolicyLabelInspection,
)


def render_baseline_policy_training(model: BaselinePolicyModel) -> str:
    return "\n".join(
        [
            f"Model: {model.model_type}",
            f"States: {model.state_count}",
            f"Labeled states: {model.labeled_state_count}",
            f"Stop margin: {model.stop_margin:.6f}",
            f"Feature stats: {len(model.feature_stats)}",
            f"Default score: {model.default_score:.6f}",
            f"Filter: {_render_filter(model.data_filter)}",
        ]
    )


def render_linear_policy_training(model: LinearPolicyModel) -> str:
    return "\n".join(
        [
            f"Model: {model.model_type}",
            f"States: {model.state_count}",
            f"Labeled states: {model.labeled_state_count}",
            f"Choice states: {model.choice_state_count}",
            f"Stop margin: {model.stop_margin:.6f}",
            f"Epochs: {model.epochs}",
            f"Learning rate: {model.learning_rate:.6f}",
            f"Training margin: {model.training_margin:.6f}",
            f"Unknown preference scale: {model.unknown_preference_scale:.6f}",
            f"Unknown preference group by: {_render_tuple(model.unknown_preference_group_by)}",
            (
                "Unknown preference group scales: "
                f"{_render_group_scales(model.unknown_preference_group_scales)}"
            ),
            f"Updates: {model.update_count}",
            f"Skipped preferences: {model.skipped_preference_count}",
            f"Skipped unknown preferences: {model.skipped_unknown_preference_count}",
            f"Skipped endpoint-equivalent preferences: "
            f"{model.skipped_equivalent_preference_count}",
            f"Feature weights: {len(model.feature_weights)}",
            f"Filter: {_render_filter(model.data_filter)}",
        ]
    )


def render_baseline_policy_evaluation(evaluation: BaselinePolicyEvaluation) -> str:
    accuracy = "n/a" if evaluation.accuracy is None else f"{evaluation.accuracy:.4f}"
    adjusted_accuracy = (
        "n/a"
        if evaluation.adjusted_accuracy is None
        else f"{evaluation.adjusted_accuracy:.4f}"
    )
    mean_gap = (
        "n/a"
        if evaluation.mean_known_reward_gap is None
        else f"{evaluation.mean_known_reward_gap:.6f}"
    )
    lines = [
        f"Model: {evaluation.model_type}",
        f"States: {evaluation.state_count}",
        f"Predicted states: {evaluation.predicted_state_count}",
        f"Top-1 accuracy: {accuracy}",
        f"Adjusted accuracy: {adjusted_accuracy}",
        f"Reward margin: {evaluation.reward_margin:.6f}",
        f"Stop margin: {evaluation.stop_margin:.6f}",
        f"Endpoint-equivalent misses: {evaluation.endpoint_equivalent_count}",
        f"Known reward gaps: {evaluation.known_reward_gap_count}",
        f"Mean known reward gap: {mean_gap}",
        f"Filter: {_render_filter(evaluation.data_filter)}",
    ]
    if evaluation.per_oracle_rule:
        lines.append("")
        lines.append("Per oracle rule:")
        for rule in evaluation.per_oracle_rule:
            adjusted = (
                "n/a"
                if rule.adjusted_accuracy is None
                else f"{rule.adjusted_accuracy:.4f}"
            )
            lines.append(
                f"  {rule.rule_name}: {rule.correct_count}/{rule.state_count} "
                f"({rule.accuracy:.4f}), adjusted={rule.acceptable_count}/"
                f"{rule.state_count} ({adjusted})"
            )
    return "\n".join(lines)


def render_baseline_policy_inspection(
    inspection: BaselinePolicyInspection,
    *,
    limit: int | None = None,
) -> str:
    rows = inspection.rows[:limit] if limit is not None else inspection.rows
    lines = [
        "Baseline policy inspection",
        f"Model: {inspection.model_type}",
        f"States: {inspection.state_count}",
        f"Predicted states: {inspection.predicted_state_count}",
        f"Misses: {inspection.miss_count}",
        f"Unacceptable: {inspection.unacceptable_count}",
        f"Rows shown: {len(rows)}/{inspection.row_count}",
        f"Reward margin: {inspection.reward_margin:.6f}",
        f"Stop margin: {inspection.stop_margin:.6f}",
        f"Filter: {_render_filter(inspection.data_filter)}",
    ]
    if not rows:
        lines.append("")
        lines.append("No matching policy states.")
        return "\n".join(lines)

    for row in rows:
        gap = "n/a" if row.reward_gap is None else f"{row.reward_gap:.6f}"
        lines.extend(
            [
                "",
                f"Task: {row.task_id}",
                f"  Fixture: {row.fixture_id}",
                f"  Step: {row.step_index}",
                f"  Tags: {', '.join(row.tags) if row.tags else 'none'}",
                f"  Oracle: {row.oracle_action_id}",
                f"  Predicted: {row.predicted_action_id}",
                f"  Correct: {row.correct}",
                f"  Acceptable: {row.acceptable}",
                f"  Endpoint equivalent: {row.endpoint_equivalent}",
                f"  Reward gap: {gap}",
                "  Scores:",
            ]
        )
        for action_id, score in sorted(
            row.action_scores.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"    {action_id}: {score:.6f}")
        lines.append("  SQL:")
        lines.extend(f"    {line}" for line in row.state_sql.splitlines())

    return "\n".join(lines)


def render_policy_label_inspection(
    inspection: PolicyLabelInspection,
    *,
    limit: int | None = None,
) -> str:
    groups = inspection.groups[:limit] if limit is not None else inspection.groups
    lines = [
        "Policy label inspection",
        f"Train preferences: {inspection.train_preference_count}",
        f"Holdout preferences: {inspection.holdout_preference_count}",
        f"Groups: {inspection.group_count}",
        f"Disagreement groups: {inspection.disagreement_group_count}",
        f"Train-only groups: {inspection.train_only_group_count}",
        f"Holdout-only groups: {inspection.holdout_only_group_count}",
        f"Rows shown: {len(groups)}/{inspection.group_count}",
        f"Group by: {', '.join(inspection.group_by)}",
        f"Reward margin: {inspection.reward_margin:.6f}",
        f"Stop margin: {inspection.stop_margin:.6f}",
        f"Train filter: {_render_filter(inspection.train_filter)}",
        f"Holdout filter: {_render_filter(inspection.holdout_filter)}",
        f"Global train prefs: {_render_preference_counts(inspection.train_preferences)}",
        f"Global holdout prefs: {_render_preference_counts(inspection.holdout_preferences)}",
    ]
    if not groups:
        lines.append("")
        lines.append("No matching preference groups.")
        return "\n".join(lines)

    for group in groups:
        lines.extend(
            [
                "",
                f"Group: {group.group_key}",
                f"  Coverage: {group.coverage_status}",
                f"  Train count: {group.train_count}",
                f"  Holdout count: {group.holdout_count}",
                f"  Disagreements: {group.disagreement_count}",
                f"  Train prefs: {_render_preference_counts(group.train_preferences)}",
                f"  Holdout prefs: {_render_preference_counts(group.holdout_preferences)}",
                "  Train majority: "
                f"{_render_majority(group.train_majority_preference, group.train_majority_ratio)}",
                "  Holdout majority: "
                f"{_render_majority(
                    group.holdout_majority_preference,
                    group.holdout_majority_ratio,
                )}",
                f"  Mean train gap: {_render_optional_float(group.mean_train_reward_gap)}",
                f"  Mean holdout gap: {_render_optional_float(group.mean_holdout_reward_gap)}",
            ]
        )
        for example in group.examples:
            gap = _render_optional_float(example.reward_gap)
            lines.extend(
                [
                    f"  Example: {example.task_id} ({example.fixture_id})",
                    f"    preferred={example.preferred_action_id}",
                    f"    alternative={example.alternative_action_id}",
                    f"    gap={gap}",
                ]
            )
    return "\n".join(lines)


def render_policy_holdout_evaluation(evaluation: PolicyHoldoutEvaluation) -> str:
    lines = [
        "Policy holdout evaluation",
        f"Train states: {evaluation.trained_state_count}",
        f"Held-out states: {evaluation.heldout_state_count}",
        f"Held-out tasks: {len(evaluation.heldout_task_ids)}",
        f"Corpus report: {evaluation.corpus_report_path}",
        "",
        "Strategy comparison:",
    ]
    for strategy, reward in evaluation.strategy_rewards.items():
        rendered_reward = "n/a" if reward is None else f"{reward:.6f}"
        lines.append(
            f"  {strategy}: reward={rendered_reward}, "
            f"wins={evaluation.strategy_wins.get(strategy, 0)}, "
            f"vreq={evaluation.strategy_verifier_requests.get(strategy, 0)}, "
            f"breq={evaluation.strategy_benchmark_requests.get(strategy, 0)}"
        )
    lines.append("")
    lines.append("Offline label evaluation:")
    lines.append(render_baseline_policy_evaluation(evaluation.offline_evaluation))
    return "\n".join(lines)


def render_policy_holdout_comparison(comparison: PolicyHoldoutComparison) -> str:
    lines = [
        "Policy holdout comparison",
        f"Baseline: {comparison.baseline_label}",
        "",
        (
            "LABEL EXACT ADJUSTED GREEDY_REWARD POLICY_REWARD DELTA "
            "GREEDY_WINS POLICY_WINS WIN_DELTA GREEDY_REQ POLICY_REQ REQ_DELTA"
        ),
    ]
    for row in comparison.rows:
        lines.append(
            " ".join(
                [
                    row.label,
                    _render_optional_ratio(row.exact_accuracy),
                    _render_optional_ratio(row.adjusted_accuracy),
                    _render_optional_float(row.greedy_reward),
                    _render_optional_float(row.policy_reward),
                    _render_optional_float(row.reward_delta_vs_greedy),
                    _render_optional_int(row.greedy_wins),
                    _render_optional_int(row.policy_wins),
                    _render_optional_int(row.win_delta_vs_greedy),
                    _render_optional_int(row.greedy_oracle_requests),
                    _render_optional_int(row.policy_oracle_requests),
                    _render_optional_int(row.oracle_request_delta_vs_greedy),
                ]
            )
        )
    return "\n".join(lines)


def _render_filter(data_filter: PolicyDataFilter) -> str:
    parts = []
    for field_name in (
        "include_tasks",
        "exclude_tasks",
        "include_fixtures",
        "exclude_fixtures",
        "include_tags",
        "exclude_tags",
    ):
        values = getattr(data_filter, field_name)
        if values:
            parts.append(f"{field_name}={','.join(values)}")
    return "; ".join(parts) if parts else "none"


def _render_tuple(values: tuple[str, ...]) -> str:
    return ",".join(values) if values else "none"


def _render_group_scales(scales: dict[str, float]) -> str:
    if not scales:
        return "none"
    return ", ".join(
        f"{group_key}={scale:.6f}" for group_key, scale in sorted(scales.items())
    )


def _render_preference_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(
        f"{action_id}={count}"
        for action_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _render_majority(action_id: str | None, ratio: float | None) -> str:
    if action_id is None or ratio is None:
        return "none"
    return f"{action_id} ({ratio:.4f})"


def _render_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def _render_optional_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def _render_optional_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)
