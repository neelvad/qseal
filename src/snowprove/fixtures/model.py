from pydantic import BaseModel, ConfigDict, Field, model_validator


class DuckDbFixtureSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    seed: int = 1
    user_rows: int = Field(default=10_000, ge=1)
    order_rows: int = Field(default=100_000, ge=1)
    event_rows: int = Field(default=50_000, ge=1)
    active_fraction: float = Field(default=0.2, ge=0, le=1)
    null_fraction: float = Field(default=0.1, ge=0, le=1)
    duplicate_fraction: float = Field(default=0.25, ge=0, lt=1)
    skew_fraction: float = Field(default=0.8, ge=0, le=1)
    segment_count: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def validate_seed_range(self) -> "DuckDbFixtureSpec":
        if abs(self.seed) > 1_000_000_000:
            raise ValueError("seed must be between -1000000000 and 1000000000.")
        return self


class FixtureTableSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_count: int
    fingerprint: str
    statistics: dict[str, int | float]


class DuckDbFixtureManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    artifact_type: str = "duckdb_fixture"
    dialect: str = "duckdb"
    database_path: str
    duckdb_version: str
    spec: DuckDbFixtureSpec
    tables: dict[str, FixtureTableSummary]
