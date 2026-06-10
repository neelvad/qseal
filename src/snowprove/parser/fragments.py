import sqlglot
from pydantic import BaseModel, ConfigDict
from sqlglot import exp
from sqlglot.errors import SqlglotError

from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.ir.model import SelectQuery
from snowprove.parser.sqlglot_parser import (
    UnsupportedSqlError,
    _cte_map,
    _parse_select_expression,
)


class QueryFragment(BaseModel):
    model_config = ConfigDict(frozen=True)

    location: str
    cte_name: str | None = None
    query: SelectQuery | None = None
    error: str | None = None

    def describe(self) -> str:
        if self.cte_name is not None:
            return f"CTE '{self.cte_name}'"
        return "the outer query"


def parse_select_fragments(
    sql: str,
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> tuple[QueryFragment, ...]:
    """Parse the CTE bodies and outer SELECT of a WITH query as fragments.

    Each fragment is parsed with only the CTEs defined before it in scope, so
    pass-through CTE references resolve to base tables while references to
    later CTE names keep their base-table meaning.
    """
    parsed = _parse_statement(sql, dialect)
    with_expr = parsed.args.get("with_")
    if with_expr is None:
        return ()

    ctes = _cte_map(with_expr)
    fragments = []
    in_scope: dict[str, exp.Select] = {}
    for name, body in ctes.items():
        fragments.append(_fragment(f"cte:{name}", name, body, dict(in_scope), dialect))
        in_scope[name] = body

    outer = parsed.copy()
    outer.set("with_", None)
    fragments.append(_fragment("query", None, outer, in_scope, dialect))
    return tuple(fragments)


def replace_fragment_sql(
    sql: str,
    location: str,
    fragment_sql: str,
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> str:
    """Return the full query SQL with one fragment's body replaced."""
    parsed = _parse_statement(sql, dialect)
    replacement = _parse_statement(fragment_sql, dialect)
    if replacement.args.get("with_") is not None:
        raise UnsupportedSqlError("Fragment replacements must not declare WITH clauses.")

    if location == "query":
        with_expr = parsed.args.get("with_")
        if with_expr is not None:
            replacement.set("with_", with_expr.copy())
        return replacement.sql(dialect=dialect, pretty=True)

    cte_name = location.removeprefix("cte:")
    with_expr = parsed.args.get("with_")
    for cte in with_expr.expressions if with_expr is not None else []:
        if cte.alias == cte_name:
            cte.set("this", replacement)
            return parsed.sql(dialect=dialect, pretty=True)
    raise ValueError(f"Unknown query fragment location: {location}.")


def _parse_statement(sql: str, dialect: SqlDialect) -> exp.Select:
    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError as error:
        raise UnsupportedSqlError(f"Could not parse SQL: {error}") from error
    if not isinstance(parsed, exp.Select):
        raise UnsupportedSqlError("Only SELECT statements are supported.")
    return parsed


def _fragment(
    location: str,
    cte_name: str | None,
    body: exp.Select,
    ctes: dict[str, exp.Select],
    dialect: SqlDialect,
) -> QueryFragment:
    try:
        query = _parse_select_expression(body, ctes, dialect)
    except UnsupportedSqlError as error:
        return QueryFragment(location=location, cte_name=cte_name, error=str(error))
    return QueryFragment(location=location, cte_name=cte_name, query=query)
