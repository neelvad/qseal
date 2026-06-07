from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from snowprove.benchmark.model import BenchmarkResult
from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import SqlDialect
from snowprove.rewrites.base import RewriteMatch
from snowprove.verifier.model import VerificationResult


class EnvironmentTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    sql: str
    constraints: ConstraintCatalog = Field(default_factory=ConstraintCatalog)
    dialect: SqlDialect = "duckdb"
    max_steps: int = Field(default=8, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    match: RewriteMatch


class EnvironmentObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    initial_sql: str
    current_sql: str
    dialect: SqlDialect
    step_index: int
    actions: tuple[EnvironmentAction, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: EnvironmentAction
    observation: EnvironmentObservation
    proposed_sql: str
    reward: float
    terminated: bool
    truncated: bool
    verification: VerificationResult
    benchmark: BenchmarkResult | None = None
    reason: str | None = None
