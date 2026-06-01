import sqlglot
from sqlglot import exp

from snowprove.ir.model import ColumnRef, SelectQuery


class UnsupportedSqlError(ValueError):
    pass


def parse_select(sql: str) -> SelectQuery:
    parsed = sqlglot.parse_one(sql, read="snowflake")
    if not isinstance(parsed, exp.Select):
        raise UnsupportedSqlError("Only SELECT statements are supported.")

    from_expr = parsed.args.get("from_")
    if from_expr is None or from_expr.this is None:
        raise UnsupportedSqlError("SELECT statements must include a FROM table.")

    joins = parsed.args.get("joins") or []
    if joins:
        raise UnsupportedSqlError("Joins are not supported by this rewrite yet.")

    table = _table_name(from_expr.this)
    projections = [_projection_to_column(expr) for expr in parsed.expressions]

    return SelectQuery(
        table=table,
        projections=tuple(projections),
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
