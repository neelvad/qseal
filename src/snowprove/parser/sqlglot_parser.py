import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from snowprove.ir.model import ColumnRef, LiteralValue, Predicate, SelectQuery


class UnsupportedSqlError(ValueError):
    pass


def parse_select(sql: str) -> SelectQuery:
    try:
        parsed = sqlglot.parse_one(sql, read="snowflake")
    except ParseError as error:
        raise UnsupportedSqlError(f"Could not parse SQL: {error}") from error

    if not isinstance(parsed, exp.Select):
        raise UnsupportedSqlError("Only SELECT statements are supported.")

    from_expr = parsed.args.get("from_")
    if from_expr is None or from_expr.this is None:
        raise UnsupportedSqlError("SELECT statements must include a FROM table.")

    joins = parsed.args.get("joins") or []
    if joins:
        raise UnsupportedSqlError("Joins are not supported by this rewrite yet.")

    _reject_unsupported_clauses(parsed)

    table = _table_name(from_expr.this)
    projections = [_projection_to_column(expr) for expr in parsed.expressions]
    predicates = _where_predicates(parsed.args.get("where"))

    return SelectQuery(
        table=table,
        projections=tuple(projections),
        predicates=tuple(predicates),
        distinct=parsed.args.get("distinct") is not None,
        raw_sql=sql.strip(),
    )


def _table_name(node: exp.Expression) -> str:
    if not isinstance(node, exp.Table):
        raise UnsupportedSqlError("Only direct table references are supported.")
    return node.name


def _projection_to_column(node: exp.Expression) -> ColumnRef:
    if isinstance(node, exp.Column):
        return ColumnRef(table=node.table or None, name=node.name)
    raise UnsupportedSqlError("Only direct column projections are supported.")


def _reject_unsupported_clauses(parsed: exp.Select) -> None:
    unsupported = {
        "group": "GROUP BY",
        "having": "HAVING",
        "qualify": "QUALIFY",
        "order": "ORDER BY",
        "limit": "LIMIT",
    }
    for arg_name, clause_name in unsupported.items():
        if parsed.args.get(arg_name) is not None:
            raise UnsupportedSqlError(f"{clause_name} is not supported yet.")


def _where_predicates(where: exp.Where | None) -> list[Predicate]:
    if where is None:
        return []
    return _predicate_expression(where.this)


def _predicate_expression(node: exp.Expression) -> list[Predicate]:
    if isinstance(node, exp.And):
        return [
            *_predicate_expression(node.this),
            *_predicate_expression(node.expression),
        ]
    if isinstance(node, exp.EQ | exp.GT | exp.GTE | exp.LT | exp.LTE):
        return [_comparison(node)]
    raise UnsupportedSqlError("Only ANDed column/literal WHERE comparisons are supported.")


def _comparison(node: exp.Expression) -> Predicate:
    if not isinstance(node.this, exp.Column) or not isinstance(node.expression, exp.Literal):
        raise UnsupportedSqlError("WHERE comparisons must compare a column to a literal.")

    return Predicate(
        left=ColumnRef(table=node.this.table or None, name=node.this.name),
        operator=_operator(node),
        right=LiteralValue(
            value=str(node.expression.this),
            is_string=bool(node.expression.is_string),
        ),
    )


def _operator(node: exp.Expression) -> str:
    if isinstance(node, exp.EQ):
        return "="
    if isinstance(node, exp.GT):
        return ">"
    if isinstance(node, exp.GTE):
        return ">="
    if isinstance(node, exp.LT):
        return "<"
    if isinstance(node, exp.LTE):
        return "<="
    raise UnsupportedSqlError("Unsupported WHERE comparison operator.")
