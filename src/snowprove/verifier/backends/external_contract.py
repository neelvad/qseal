from pydantic import BaseModel, ConfigDict, Field

from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect


class ExternalSolverRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_sql: str
    rewritten_sql: str
    constraints: ConstraintCatalog
    dialect: SqlDialect = DEFAULT_DIALECT
    solver_command: str | None = None
    timeout_seconds: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    def normalized_original_sql(self) -> str:
        return self.original_sql.strip()

    def normalized_rewritten_sql(self) -> str:
        return self.rewritten_sql.strip()
