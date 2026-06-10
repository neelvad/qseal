from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from snowprove.dialects import DEFAULT_DIALECT, SqlDialect


class ColumnRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    table: str | None = None
    alias: str | None = None
    expression_sql: str | None = None
    is_star: bool = False

    def to_sql(self) -> str:
        if self.expression_sql is not None:
            if self.alias:
                return f"{self.expression_sql} AS {self.alias}"
            return self.expression_sql
        if self.is_star:
            return f"{self.table}.*" if self.table else "*"
        column = f"{self.table}.{self.name}" if self.table else self.name
        if self.alias:
            return f"{column} AS {self.alias}"
        return column

    def is_direct_column(self) -> bool:
        return self.expression_sql is None and not self.is_star

    def unqualified(self) -> ColumnRef:
        return self.model_copy(update={"table": None})

    def without_alias(self) -> ColumnRef:
        return self.model_copy(update={"alias": None})


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
    right: LiteralValue | None = None

    def to_sql(self) -> str:
        if self.right is None:
            return f"{self.left.to_sql()} {self.operator}"
        return f"{self.left.to_sql()} {self.operator} {self.right.to_sql()}"

    def unqualified(self) -> Predicate:
        return Predicate(left=self.left.unqualified(), operator=self.operator, right=self.right)


class InPredicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: ColumnRef
    values: tuple[LiteralValue, ...]
    negated: bool = False

    def to_sql(self) -> str:
        operator = "NOT IN" if self.negated else "IN"
        values = ", ".join(value.to_sql() for value in self.values)
        return f"{self.left.to_sql()} {operator} ({values})"


class HavingPredicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    expression_sql: str

    def to_sql(self) -> str:
        return self.expression_sql


class JoinCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: ColumnRef
    right: ColumnRef

    def to_sql(self) -> str:
        return f"{self.left.to_sql()} = {self.right.to_sql()}"


class ExistsPredicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    table_sql: str | None = None
    alias: str | None = None
    condition: JoinCondition

    def source_sql(self) -> str:
        table_sql = self.table_sql or self.table
        alias = f" {self.alias}" if self.alias else ""
        return f"{table_sql}{alias}"

    def to_sql(self) -> str:
        return (
            "EXISTS (\n"
            "  SELECT 1\n"
            f"  FROM {self.source_sql()}\n"
            f"  WHERE {self.condition.to_sql()}\n"
            ")"
        )


class Join(BaseModel):
    model_config = ConfigDict(frozen=True)

    join_type: str
    table: str
    table_sql: str | None = None
    alias: str | None = None
    # True when the join target is a CTE reference, so trusted base-table
    # constraints sharing the CTE's name must not be applied to it.
    table_is_cte: bool = False
    condition: JoinCondition

    def relation_name(self) -> str:
        return self.alias or self.table

    def to_sql(self) -> str:
        table_sql = self.table_sql or self.table
        alias = f" {self.alias}" if self.alias else ""
        return f"{self.join_type} JOIN {table_sql}{alias} ON {self.condition.to_sql()}"


class SelectQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str | None = None
    table_sql: str | None = None
    table_alias: str | None = None
    # True when the source is a CTE reference, so trusted base-table
    # constraints sharing the CTE's name must not be applied to it.
    table_is_cte: bool = False
    subquery: SelectQuery | None = None
    alias: str | None = None
    joins: tuple[Join, ...] = ()
    projections: tuple[ColumnRef, ...]
    predicates: tuple[Predicate | InPredicate | ExistsPredicate, ...] = ()
    group_by: tuple[ColumnRef, ...] = ()
    having: tuple[HavingPredicate, ...] = ()
    distinct: bool
    raw_sql: str
    dialect: SqlDialect = DEFAULT_DIALECT

    def is_direct_table(self) -> bool:
        return self.table is not None and self.subquery is None

    def table_name(self) -> str | None:
        if self.table_is_cte:
            return None
        return self.table if self.is_direct_table() else None

    def source_sql(self) -> str:
        if self.table is not None:
            table_sql = self.table_sql or self.table
            alias = f" {self.table_alias}" if self.table_alias else ""
            return f"{table_sql}{alias}"
        if self.subquery is not None:
            subquery_sql = self.subquery.to_sql().removesuffix(";")
            alias = f" {self.alias}" if self.alias else ""
            return f"({subquery_sql}){alias}"
        raise ValueError("SelectQuery must have either a table or subquery source.")

    def to_sql(self) -> str:
        distinct = " DISTINCT" if self.distinct else ""
        projected = ", ".join(column.to_sql() for column in self.projections)
        sql = f"SELECT{distinct} {projected}\nFROM {self.source_sql()}"
        if self.joins:
            joins = "\n".join(join.to_sql() for join in self.joins)
            sql = f"{sql}\n{joins}"
        if self.predicates:
            predicates = " AND ".join(predicate.to_sql() for predicate in self.predicates)
            sql = f"{sql}\nWHERE {predicates}"
        if self.group_by:
            grouped = ", ".join(column.to_sql() for column in self.group_by)
            sql = f"{sql}\nGROUP BY {grouped}"
        if self.having:
            having = " AND ".join(predicate.to_sql() for predicate in self.having)
            sql = f"{sql}\nHAVING {having}"
        return f"{sql};"

    def without_distinct_sql(self) -> str:
        return self.model_copy(update={"distinct": False}).to_sql()
