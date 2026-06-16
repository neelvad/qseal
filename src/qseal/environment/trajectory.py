from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from qseal.environment.model import (
    EnvironmentObservation,
    EnvironmentTask,
    EnvironmentTransition,
)


class TrajectoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    artifact_type: str = "rewrite_trajectory_transition"
    task_id: str
    step_index: int
    dialect: str
    state_sql: str
    action_id: str
    proposed_sql: str
    next_state_sql: str
    reward: float
    terminated: bool
    truncated: bool
    verification: dict[str, Any]
    benchmark: dict[str, Any] | None = None
    reason: str | None = None
    task_metadata: dict[str, Any]


class JsonlTrajectoryRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(
        self,
        task: EnvironmentTask,
        before: EnvironmentObservation,
        transition: EnvironmentTransition,
    ) -> TrajectoryRecord:
        record = TrajectoryRecord(
            task_id=task.task_id,
            step_index=before.step_index,
            dialect=task.dialect,
            state_sql=before.current_sql,
            action_id=transition.action.action_id,
            proposed_sql=transition.proposed_sql,
            next_state_sql=transition.observation.current_sql,
            reward=transition.reward,
            terminated=transition.terminated,
            truncated=transition.truncated,
            verification=transition.verification.model_dump(mode="json"),
            benchmark=(
                transition.benchmark.model_dump(mode="json")
                if transition.benchmark is not None
                else None
            ),
            reason=transition.reason,
            task_metadata=task.metadata,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(
                json.dumps(
                    record.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            handle.write("\n")
        return record


def load_trajectory(path: Path) -> tuple[TrajectoryRecord, ...]:
    if not path.exists():
        return ()
    return tuple(
        TrajectoryRecord.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    )
