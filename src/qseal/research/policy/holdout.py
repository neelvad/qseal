from __future__ import annotations

from pathlib import Path

from qseal.research.policy.io import load_policy_holdout_evaluation
from qseal.research.policy.model import (
    PolicyHoldoutComparison,
    PolicyHoldoutComparisonRow,
    PolicyHoldoutEvaluation,
)


def compare_policy_holdouts(
    paths: tuple[Path, ...],
    *,
    labels: tuple[str, ...] = (),
) -> PolicyHoldoutComparison:
    if not paths:
        raise ValueError("At least one holdout evaluation path is required.")
    if labels and len(labels) != len(paths):
        raise ValueError("If labels are provided, their count must match paths.")
    resolved_labels = labels or tuple(path.stem for path in paths)
    rows = tuple(
        _holdout_comparison_row(
            load_policy_holdout_evaluation(path),
            label=label,
            path=path,
        )
        for label, path in zip(resolved_labels, paths, strict=True)
    )
    return PolicyHoldoutComparison(
        baseline_label=resolved_labels[0],
        rows=rows,
    )


def _holdout_comparison_row(
    evaluation: PolicyHoldoutEvaluation,
    *,
    label: str,
    path: Path,
) -> PolicyHoldoutComparisonRow:
    greedy_reward = evaluation.strategy_rewards.get("greedy")
    policy_reward = evaluation.strategy_rewards.get("policy_baseline_abstain")
    greedy_wins = evaluation.strategy_wins.get("greedy")
    policy_wins = evaluation.strategy_wins.get("policy_baseline_abstain")
    greedy_requests = _strategy_oracle_requests(evaluation, "greedy")
    policy_requests = _strategy_oracle_requests(evaluation, "policy_baseline_abstain")
    return PolicyHoldoutComparisonRow(
        label=label,
        path=str(path),
        model_type=evaluation.offline_evaluation.model_type,
        trained_state_count=evaluation.trained_state_count,
        heldout_state_count=evaluation.heldout_state_count,
        exact_accuracy=evaluation.offline_evaluation.accuracy,
        adjusted_accuracy=evaluation.offline_evaluation.adjusted_accuracy,
        greedy_reward=greedy_reward,
        policy_reward=policy_reward,
        reward_delta_vs_greedy=(
            None
            if greedy_reward is None or policy_reward is None
            else policy_reward - greedy_reward
        ),
        greedy_wins=greedy_wins,
        policy_wins=policy_wins,
        win_delta_vs_greedy=(
            None
            if greedy_wins is None or policy_wins is None
            else policy_wins - greedy_wins
        ),
        greedy_oracle_requests=greedy_requests,
        policy_oracle_requests=policy_requests,
        oracle_request_delta_vs_greedy=(
            None
            if greedy_requests is None or policy_requests is None
            else policy_requests - greedy_requests
        ),
    )


def _strategy_oracle_requests(
    evaluation: PolicyHoldoutEvaluation,
    strategy: str,
) -> int | None:
    verifier = evaluation.strategy_verifier_requests.get(strategy)
    benchmark = evaluation.strategy_benchmark_requests.get(strategy)
    if verifier is None and benchmark is None:
        return None
    return (verifier or 0) + (benchmark or 0)
