from typing import Literal

SqlDialect = Literal["duckdb", "snowflake"]
DEFAULT_DIALECT: SqlDialect = "snowflake"
SUPPORTED_DIALECTS: tuple[SqlDialect, ...] = ("duckdb", "snowflake")
