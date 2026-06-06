from enum import StrEnum
from typing import Any

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


class RewriteMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_name: str
    match_id: str
    target_kind: str
    target_index: int | None = None
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)
