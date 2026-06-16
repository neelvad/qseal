from pydantic import BaseModel, ConfigDict, Field

from qseal.rewrites.base import VerificationStatus


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: VerificationStatus
    original_sql: str
    rewritten_sql: str
    rule_name: str | None = None
    verification_method: str | None = None
    safety_claim: str | None = None
    assumptions: tuple[str, ...] = Field(default_factory=tuple)
    reason: str | None = None
    counterexample: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)
