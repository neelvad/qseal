from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(StrEnum):
    PROVEN_EQUIVALENT = "PROVEN_EQUIVALENT"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


class RewriteSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_name: str
    status: VerificationStatus
    original_sql: str
    rewritten_sql: str | None = None
    assumptions: tuple[str, ...] = Field(default_factory=tuple)
    reason: str | None = None
