from __future__ import annotations

import json
from pathlib import Path

from qseal.research.policy.model import (
    BaselinePolicyEvaluation,
    BaselinePolicyModel,
    LinearPolicyModel,
    PolicyHoldoutEvaluation,
    PolicyModel,
)


def write_baseline_policy(model: PolicyModel, path: Path) -> None:
    write_policy_model(model, path)


def write_policy_model(model: PolicyModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2))


def load_baseline_policy(path: Path) -> PolicyModel:
    return load_policy_model(path)


def load_policy_model(path: Path) -> PolicyModel:
    payload = json.loads(path.read_text())
    artifact_type = payload.get("artifact_type")
    if artifact_type == "baseline_policy_model":
        return BaselinePolicyModel.model_validate(payload)
    if artifact_type == "linear_policy_model":
        return LinearPolicyModel.model_validate(payload)
    raise ValueError(f"Unknown policy model artifact_type: {artifact_type}.")


def load_policy_holdout_evaluation(path: Path) -> PolicyHoldoutEvaluation:
    return PolicyHoldoutEvaluation.model_validate(json.loads(path.read_text()))


def load_baseline_policy_evaluation(path: Path) -> BaselinePolicyEvaluation:
    return BaselinePolicyEvaluation.model_validate(json.loads(path.read_text()))
