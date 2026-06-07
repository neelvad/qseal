from pydantic import BaseModel, ConfigDict, Field

from snowprove.rewrites.base import VerificationStatus


class SearchStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_index: int
    action_id: str
    state_sql: str
    proposed_sql: str
    next_sql: str
    reward: float
    cumulative_reward: float
    verification_status: VerificationStatus
    terminated: bool
    truncated: bool


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: str
    task_id: str
    initial_sql: str
    final_sql: str
    action_ids: tuple[str, ...] = Field(default_factory=tuple)
    steps: tuple[SearchStep, ...] = Field(default_factory=tuple)
    cumulative_reward: float = 0.0
    terminated: bool
    truncated: bool
    stopped_early: bool = False
    search_truncated: bool = False
    explored_nodes: int = 0
    seed: int | None = None
    beam_width: int | None = None
    max_nodes: int | None = None
