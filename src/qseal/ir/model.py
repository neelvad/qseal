from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from qseal.dialects import DEFAULT_DIALECT, SqlDialect

# A bare (unquoted) SQL identifier. Anything outside this shape -- hyphens,
# spaces, leading digits, reserved words rendered verbatim -- must be quoted, or
# the rendered SQL is invalid or, worse, parses to a *different* query (``user-id``
# becomes ``user - id``). Snowflake and DuckDB, QuerySeal's target dialects, both
# use ANSI double quotes for identifiers.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _quote_identifier(name: str) -> str:
    if _SAFE_IDENTIFIER.match(name):
        return name
    return '"' + name.replace('"', '""') + '"'


class ColumnRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    table: str | None = None
    alias: str | None = None
    expression_sql: str | None = None
    # Relations referenced by columns inside an opaque expression. Unqualified
    # column references cannot be attributed to a relation, so rules that
    # depend on a relation being unused must treat them as potential uses.
    referenced_tables: tuple[str, ...] = ()
    references_unqualified_columns: bool = False
    is_star: bool = False
    # True when the opaque expression contains a non-windowed aggregate. A
    # whole-table aggregate (no GROUP BY) always yields one row, so DISTINCT
    # over it is a no-op; the unique-key reasoning in distinct removal cannot
    # account for that and must not refute it.
    is_aggregate: bool = False

    def may_reference_relation(self, relation: str) -> bool:
        if self.expression_sql is None:
            return False
        return self.references_unqualified_columns or relation in self.referenced_tables

    def to_sql(self) -> str:
        if self.expression_sql is not None:
            if self.alias:
                return f"{self.expression_sql} AS {self.alias}"
            return self.expression_sql
        if self.is_star:
            return f"{_quote_identifier(self.table)}.*" if self.table else "*"
        name = _quote_identifier(self.name)
        column = f"{_quote_identifier(self.table)}.{name}" if self.table else name
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


class OpaquePredicate(BaseModel):
    """A WHERE predicate whose shape (OR, BETWEEN, LIKE, column-to-column,
    column-to-subquery, ...) is not modeled by the structured ``Predicate``.

    It is captured verbatim so the query parses and can be compared by
    normalized IR identity. Rewrite rules that need structured predicates
    (predicate pushdown, redundant non-null removal, accepted-value removal)
    bail when any opaque predicate is present, so an opaque predicate only
    ever passes through unchanged.
    """

    model_config = ConfigDict(frozen=True)

    expression_sql: str
    referenced_tables: tuple[str, ...] = ()
    references_unqualified_columns: bool = False

    def to_sql(self) -> str:
        return self.expression_sql

    def may_reference_relation(self, relation: str) -> bool:
        return self.references_unqualified_columns or relation in self.referenced_tables


class HavingPredicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    expression_sql: str

    def to_sql(self) -> str:
        return self.expression_sql


class QualifyPredicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    expression_sql: str
    referenced_tables: tuple[str, ...] = ()
    references_unqualified_columns: bool = False

    def to_sql(self) -> str:
        return self.expression_sql

    def may_reference_relation(self, relation: str) -> bool:
        return self.references_unqualified_columns or relation in self.referenced_tables


class OrderByItem(BaseModel):
    """A single ORDER BY key, captured as an opaque expression plus direction.

    ORDER BY changes row order, so it is part of result semantics and is
    included in normalized IR identity: two queries that differ only in ORDER
    BY are not considered equivalent (execution accuracy that sorts before
    comparing would miss this).
    """

    model_config = ConfigDict(frozen=True)

    expression_sql: str
    descending: bool = False

    def to_sql(self) -> str:
        return f"{self.expression_sql} DESC" if self.descending else self.expression_sql


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
    # True when the EXISTS subquery reads from a CTE reference, so trusted
    # base-table constraints sharing the CTE's name must not be applied and
    # regenerated SQL would dangle without the defining WITH clause.
    table_is_cte: bool = False
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
    extra_conditions: tuple[JoinCondition, ...] = ()

    def relation_name(self) -> str:
        return self.alias or self.table

    def conditions(self) -> tuple[JoinCondition, ...]:
        return (self.condition, *self.extra_conditions)

    def to_sql(self) -> str:
        table_sql = self.table_sql or self.table
        alias = f" {self.alias}" if self.alias else ""
        conditions = " AND ".join(condition.to_sql() for condition in self.conditions())
        return f"{self.join_type} JOIN {table_sql}{alias} ON {conditions}"


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
    predicates: tuple[Predicate | InPredicate | OpaquePredicate | ExistsPredicate, ...] = ()
    group_by: tuple[ColumnRef, ...] = ()
    having: tuple[HavingPredicate, ...] = ()
    qualify: tuple[QualifyPredicate, ...] = ()
    order_by: tuple[OrderByItem, ...] = ()
    limit: int | None = None
    offset: int | None = None
    distinct: bool
    raw_sql: str
    dialect: SqlDialect = DEFAULT_DIALECT

    def is_direct_table(self) -> bool:
        return self.table is not None and self.subquery is None

    def table_name(self) -> str | None:
        if self.table_is_cte:
            return None
        return self.table if self.is_direct_table() else None

    def references_cte_relation(self) -> bool:
        """True when regenerated SQL would reference a CTE it cannot define."""
        if self.table_is_cte or any(join.table_is_cte for join in self.joins):
            return True
        if any(
            isinstance(predicate, ExistsPredicate) and predicate.table_is_cte
            for predicate in self.predicates
        ):
            return True
        return self.subquery is not None and self.subquery.references_cte_relation()

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
        if self.qualify:
            qualify = " AND ".join(predicate.to_sql() for predicate in self.qualify)
            sql = f"{sql}\nQUALIFY {qualify}"
        if self.order_by:
            ordered = ", ".join(item.to_sql() for item in self.order_by)
            sql = f"{sql}\nORDER BY {ordered}"
        if self.limit is not None:
            sql = f"{sql}\nLIMIT {self.limit}"
        if self.offset is not None:
            sql = f"{sql}\nOFFSET {self.offset}"
        return f"{sql};"

    def without_distinct_sql(self) -> str:
        return self.model_copy(update={"distinct": False}).to_sql()
