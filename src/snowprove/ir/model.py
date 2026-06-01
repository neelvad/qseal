from pydantic import BaseModel, ConfigDict


class ColumnRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    table: str | None = None


class SelectQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    projections: tuple[ColumnRef, ...]
    distinct: bool
    raw_sql: str

    def without_distinct_sql(self) -> str:
        projected = ", ".join(column.name for column in self.projections)
        return f"SELECT {projected}\nFROM {self.table};"
