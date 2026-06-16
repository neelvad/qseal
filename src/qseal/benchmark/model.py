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
    query_ids: tuple[str, ...] = Field(default_factory=tuple)
    timings_ms: tuple[float, ...] = Field(default_factory=tuple)
    batch_timings_ms: tuple[float, ...] = Field(default_factory=tuple)
    executions_per_sample: int = Field(default=1, ge=1)
    median_ms: float | None = None
    median_absolute_deviation_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    row_count: int | None = None
    explain: str | None = None
    error: str | None = None
    bytes_scanned: tuple[int, ...] = Field(default_factory=tuple)
    compilation_time_ms: tuple[float, ...] = Field(default_factory=tuple)
    execution_time_ms: tuple[float, ...] = Field(default_factory=tuple)
    total_elapsed_time_ms: tuple[float, ...] = Field(default_factory=tuple)


class BenchmarkEnvironment(BaseModel):
    model_config = ConfigDict(frozen=True)

    engine: str = "duckdb"
    duckdb_version: str = ""
    snowflake_connector_version: str | None = None
    snowflake_account: str | None = None
    snowflake_user: str | None = None
    snowflake_role: str | None = None
    snowflake_warehouse: str | None = None
    snowflake_database: str | None = None
    snowflake_schema: str | None = None
    snowflake_query_tag: str | None = None
    python_version: str
    platform: str
    database_path: str
    threads: int
    warmups: int
    repetitions: int
    timeout_seconds: float
    minimum_duration_ms: float = 0.0


class BenchmarkResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: BenchmarkStatus
    original: QueryBenchmark
    rewritten: QueryBenchmark
    environment: BenchmarkEnvironment
    speedup: float | None = None
    row_counts_match: bool | None = None
    timing_confident: bool = True
    confidence_reason: str | None = None
    reason: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)


class QueryBenchmarkResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: BenchmarkStatus
    query: QueryBenchmark
    environment: BenchmarkEnvironment
    timing_confident: bool = True
    confidence_reason: str | None = None
    reason: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)
