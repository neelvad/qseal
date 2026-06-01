from pydantic import BaseModel, ConfigDict


class ColumnRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    table: str | None = None

    def to_sql(self) -> str:
        if self.table:
            return f"{self.table}.{self.name}"
        return self.name


class LiteralValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    is_string: bool = False

    def to_sql(self) -> str:
        if self.is_string:
            escaped = self.value.replace("'", "''")
            return f"'{escaped}'"
        return self.value


class Predicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: ColumnRef
    operator: str
    right: LiteralValue

    def to_sql(self) -> str:
        return f"{self.left.to_sql()} {self.operator} {self.right.to_sql()}"


class SelectQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    projections: tuple[ColumnRef, ...]
    predicates: tuple[Predicate, ...] = ()
    distinct: bool
    raw_sql: str

    def without_distinct_sql(self) -> str:
        projected = ", ".join(column.to_sql() for column in self.projections)
        sql = f"SELECT {projected}\nFROM {self.table}"
        if self.predicates:
            predicates = " AND ".join(predicate.to_sql() for predicate in self.predicates)
            sql = f"{sql}\nWHERE {predicates}"
        return f"{sql};"
