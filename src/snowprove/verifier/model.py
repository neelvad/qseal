from pydantic import BaseModel, ConfigDict, Field

from snowprove.rewrites.base import VerificationStatus


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: VerificationStatus
    original_sql: str
    rewritten_sql: str
    assumptions: tuple[str, ...] = Field(default_factory=tuple)
    reason: str | None = None
    counterexample: str | None = None
