from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from qseal.dialects import DEFAULT_DIALECT, SqlDialect

STOP_ACTION_ID = "__stop__"


class PolicyDataFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    include_tasks: tuple[str, ...] = Field(default_factory=tuple)
    exclude_tasks: tuple[str, ...] = Field(default_factory=tuple)
    include_fixtures: tuple[str, ...] = Field(default_factory=tuple)
    exclude_fixtures: tuple[str, ...] = Field(default_factory=tuple)
    include_tags: tuple[str, ...] = Field(default_factory=tuple)
    exclude_tags: tuple[str, ...] = Field(default_factory=tuple)


class FeatureStat(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    appearances: int = Field(ge=0)
    oracle_count: int = Field(ge=0)
    win_rate: float


class FeatureWeight(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    weight: float


class PolicyActionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    step_index: int = Field(ge=0)
    available_action_ids: tuple[str, ...] = Field(default_factory=tuple)
    state_sql: str | None = None
    dialect: SqlDialect = DEFAULT_DIALECT


class BaselinePolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["baseline_policy_model"] = "baseline_policy_model"
    model_type: Literal["feature_mean_action_ranker"] = "feature_mean_action_ranker"
    generated_at: datetime
    source_trajectories: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    state_count: int
    labeled_state_count: int
    stop_margin: float = Field(default=0.0, ge=0)
    feature_stats: tuple[FeatureStat, ...]
    default_score: float


class LinearPolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["linear_policy_model"] = "linear_policy_model"
    model_type: Literal["linear_action_ranker"] = "linear_action_ranker"
    generated_at: datetime
    source_trajectories: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    state_count: int
    labeled_state_count: int
    choice_state_count: int
    stop_margin: float = Field(default=0.0, ge=0)
    epochs: int = Field(ge=1)
    learning_rate: float = Field(gt=0)
    training_margin: float = Field(default=0.0, ge=0)
    unknown_preference_scale: float = Field(default=1.0, ge=0)
    unknown_preference_group_by: tuple[str, ...] = Field(default_factory=tuple)
    unknown_preference_group_scales: dict[str, float] = Field(default_factory=dict)
    update_count: int = Field(ge=0)
    skipped_preference_count: int = Field(default=0, ge=0)
    skipped_unknown_preference_count: int = Field(default=0, ge=0)
    skipped_equivalent_preference_count: int = Field(default=0, ge=0)
    feature_weights: tuple[FeatureWeight, ...]
    default_score: float = 0.0


type PolicyModel = BaselinePolicyModel | LinearPolicyModel


class RuleAccuracy(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_name: str
    state_count: int
    correct_count: int
    acceptable_count: int = 0
    accuracy: float
    adjusted_accuracy: float | None = None


class BaselinePolicyEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["baseline_policy_evaluation"] = "baseline_policy_evaluation"
    model_type: str
    source_trajectories: str | None = None
    model_path: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    state_count: int
    labeled_state_count: int
    predicted_state_count: int
    correct_count: int
    acceptable_count: int = 0
    accuracy: float | None
    adjusted_accuracy: float | None = None
    reward_margin: float = Field(default=0.0, ge=0)
    stop_margin: float = Field(default=0.0, ge=0)
    endpoint_equivalent_count: int = 0
    known_reward_gap_count: int
    mean_known_reward_gap: float | None
    max_known_reward_gap: float | None
    per_oracle_rule: tuple[RuleAccuracy, ...]


class BaselinePolicyInspectionRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    fixture_id: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    step_index: int = Field(ge=0)
    state_sql: str
    available_action_ids: tuple[str, ...]
    oracle_action_id: str
    predicted_action_id: str
    correct: bool
    acceptable: bool
    endpoint_equivalent: bool = False
    reward_gap: float | None
    oracle_suffix_reward: float | None
    predicted_suffix_reward: float | None
    action_scores: dict[str, float]


class BaselinePolicyInspection(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["baseline_policy_inspection"] = "baseline_policy_inspection"
    model_type: str
    source_trajectories: str | None = None
    model_path: str | None = None
    data_filter: PolicyDataFilter = Field(default_factory=PolicyDataFilter)
    reward_margin: float = Field(default=0.0, ge=0)
    state_count: int
    predicted_state_count: int
    row_count: int
    miss_count: int
    unacceptable_count: int
    rows: tuple[BaselinePolicyInspectionRow, ...]
    stop_margin: float = Field(default=0.0, ge=0)


class PolicyHoldoutEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["policy_holdout_evaluation"] = "policy_holdout_evaluation"
    generated_at: datetime
    source_trajectories: str
    train_filter: PolicyDataFilter
    holdout_filter: PolicyDataFilter
    trained_state_count: int
    heldout_state_count: int
    offline_evaluation: BaselinePolicyEvaluation
    corpus_report_path: str
    heldout_task_ids: tuple[str, ...]
    strategy_rewards: dict[str, float | None]
    strategy_wins: dict[str, int]
    strategy_benchmark_requests: dict[str, int]
    strategy_verifier_requests: dict[str, int]


class PolicyHoldoutComparisonRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    path: str
    model_type: str
    trained_state_count: int
    heldout_state_count: int
    exact_accuracy: float | None
    adjusted_accuracy: float | None
    greedy_reward: float | None
    policy_reward: float | None
    reward_delta_vs_greedy: float | None
    greedy_wins: int | None
    policy_wins: int | None
    win_delta_vs_greedy: int | None
    greedy_oracle_requests: int | None
    policy_oracle_requests: int | None
    oracle_request_delta_vs_greedy: int | None


class PolicyHoldoutComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["policy_holdout_comparison"] = "policy_holdout_comparison"
    baseline_label: str
    rows: tuple[PolicyHoldoutComparisonRow, ...]


class PolicyPreferenceExample(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    fixture_id: str
    tags: tuple[str, ...] = Field(default_factory=tuple)
    state_sql: str
    available_action_ids: tuple[str, ...]
    preferred_action_id: str
    alternative_action_id: str
    reward_gap: float | None


class PolicyPreferenceGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_key: str
    coverage_status: Literal["matched", "train_only", "holdout_only"]
    train_count: int
    holdout_count: int
    train_preferences: dict[str, int]
    holdout_preferences: dict[str, int]
    train_majority_preference: str | None
    holdout_majority_preference: str | None
    train_majority_ratio: float | None
    holdout_majority_ratio: float | None
    disagreement_count: int
    mean_train_reward_gap: float | None
    mean_holdout_reward_gap: float | None
    examples: tuple[PolicyPreferenceExample, ...] = Field(default_factory=tuple)


class PolicyLabelInspection(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["policy_label_inspection"] = "policy_label_inspection"
    source_trajectories: str | None = None
    train_filter: PolicyDataFilter
    holdout_filter: PolicyDataFilter
    group_by: tuple[str, ...]
    reward_margin: float = Field(ge=0)
    stop_margin: float = Field(default=0.0, ge=0)
    train_preference_count: int
    holdout_preference_count: int
    train_preferences: dict[str, int]
    holdout_preferences: dict[str, int]
    group_count: int
    disagreement_group_count: int
    train_only_group_count: int
    holdout_only_group_count: int
    groups: tuple[PolicyPreferenceGroup, ...]
