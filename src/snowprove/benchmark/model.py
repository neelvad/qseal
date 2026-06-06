from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkStatus(StrEnum):
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class QueryBenchmark(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: BenchmarkStatus
    sql: str
    timings_ms: tuple[float, ...] = Field(default_factory=tuple)
    median_ms: float | None = None
    median_absolute_deviation_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    row_count: int | None = None
    explain: str | None = None
    error: str | None = None


class BenchmarkEnvironment(BaseModel):
    model_config = ConfigDict(frozen=True)

    duckdb_version: str
    python_version: str
    platform: str
    database_path: str
    threads: int
    warmups: int
    repetitions: int
    timeout_seconds: float


class BenchmarkResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: BenchmarkStatus
    original: QueryBenchmark
    rewritten: QueryBenchmark
    environment: BenchmarkEnvironment
    speedup: float | None = None
    row_counts_match: bool | None = None
    reason: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)
