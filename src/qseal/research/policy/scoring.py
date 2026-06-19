from __future__ import annotations

from qseal.research.policy.examples import _StateExample
from qseal.research.policy.features import _feature_values, _features
from qseal.research.policy.model import (
    BaselinePolicyModel,
    PolicyActionContext,
    PolicyModel,
)


def score_baseline_action(
    model: PolicyModel,
    context: PolicyActionContext,
    action_id: str,
) -> float:
    return score_policy_action(model, context, action_id)


def score_policy_action(
    model: PolicyModel,
    context: PolicyActionContext,
    action_id: str,
) -> float:
    features = _feature_values(
        fixture_id=context.fixture_id,
        tags=context.tags,
        step_index=context.step_index,
        action_id=action_id,
        available_action_ids=context.available_action_ids,
        state_sql=context.state_sql,
        dialect=context.dialect,
    )
    return _score_features(model, features)


def _score_features(model: PolicyModel, features: tuple[str, ...]) -> float:
    if isinstance(model, BaselinePolicyModel):
        scores = {stat.feature: stat.win_rate for stat in model.feature_stats}
        values = [scores[feature] for feature in features if feature in scores]
        if not values:
            return model.default_score
        return sum(values) / len(values)

    weights = {item.feature: item.weight for item in model.feature_weights}
    return sum(weights.get(feature, 0.0) for feature in features) + model.default_score


def _predict_policy(example: _StateExample, model: PolicyModel) -> str | None:
    if not example.available_action_ids:
        return None
    return sorted(
        example.available_action_ids,
        key=lambda action_id: (
            -_score_policy(example, action_id, model),
            action_id,
        ),
    )[0]


def _score_policy(
    example: _StateExample,
    action_id: str,
    model: PolicyModel,
) -> float:
    return _score_features(model, _features(example, action_id))


def _score_linear_features(
    features: tuple[str, ...],
    weights: dict[str, float],
    default_score: float,
) -> float:
    return sum(weights.get(feature, 0.0) for feature in features) + default_score
