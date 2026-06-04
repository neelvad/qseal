import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from snowprove.ir.model import (
    ColumnRef,
    ExistsPredicate,
    Join,
    JoinCondition,
    LiteralValue,
    Predicate,
    SelectQuery,
)


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

    _reject_unsupported_clauses(parsed)

    source = _source(from_expr.this)
    joins = [_join(join) for join in parsed.args.get("joins") or []]
    projections = [_projection_to_column(expr) for expr in parsed.expressions]
    predicates = _where_predicates(parsed.args.get("where"))

    return SelectQuery(
        **source,
        joins=tuple(joins),
        projections=tuple(projections),
        predicates=tuple(predicates),
        distinct=parsed.args.get("distinct") is not None,
        raw_sql=sql.strip(),
    )


def _source(node: exp.Expression) -> dict[str, object]:
    if isinstance(node, exp.Table):
        return {
            "table": node.name,
            "table_sql": _relation_sql_without_alias(node),
            "table_alias": node.alias or None,
        }
    if isinstance(node, exp.Subquery):
        if not isinstance(node.this, exp.Select):
            raise UnsupportedSqlError("Only SELECT subqueries are supported.")
        return {
            "subquery": _parse_select_expression(node.this),
            "alias": node.alias or None,
        }
    raise UnsupportedSqlError("Only direct tables and simple subqueries are supported.")


def _parse_select_expression(parsed: exp.Select) -> SelectQuery:
    from_expr = parsed.args.get("from_")
    if from_expr is None or from_expr.this is None:
        raise UnsupportedSqlError("SELECT statements must include a FROM table.")

    _reject_unsupported_clauses(parsed)

    source = _source(from_expr.this)
    joins = [_join(join) for join in parsed.args.get("joins") or []]
    projections = [_projection_to_column(expr) for expr in parsed.expressions]
    predicates = _where_predicates(parsed.args.get("where"))

    return SelectQuery(
        **source,
        joins=tuple(joins),
        projections=tuple(projections),
        predicates=tuple(predicates),
        distinct=parsed.args.get("distinct") is not None,
        raw_sql=parsed.sql(dialect="snowflake"),
    )


def _projection_to_column(node: exp.Expression) -> ColumnRef:
    if isinstance(node, exp.Column):
        return ColumnRef(table=node.table or None, name=node.name)
    if isinstance(node, exp.Alias) and isinstance(node.this, exp.Column):
        return ColumnRef(
            table=node.this.table or None,
            name=node.this.name,
            alias=node.alias,
        )
    raise UnsupportedSqlError("Only direct column projections are supported.")


def _join(node: exp.Join) -> Join:
    join_type = _join_type(node)
    if join_type is None:
        raise UnsupportedSqlError("Only INNER JOIN and LEFT JOIN are supported yet.")
    if not isinstance(node.this, exp.Table):
        raise UnsupportedSqlError("Only direct table JOIN targets are supported.")

    condition = node.args.get("on")
    if not isinstance(condition, exp.EQ):
        raise UnsupportedSqlError("JOIN conditions must be column equality predicates.")
    condition_sides_are_columns = isinstance(condition.this, exp.Column) and isinstance(
        condition.expression,
        exp.Column,
    )
    if not condition_sides_are_columns:
        raise UnsupportedSqlError("JOIN conditions must compare two columns.")

    return Join(
        join_type=join_type,
        table=node.this.name,
        table_sql=_relation_sql_without_alias(node.this),
        alias=node.this.alias or None,
        condition=JoinCondition(
            left=ColumnRef(table=condition.this.table or None, name=condition.this.name),
            right=ColumnRef(
                table=condition.expression.table or None,
                name=condition.expression.name,
            ),
        ),
    )


def _join_type(node: exp.Join) -> str | None:
    if node.side == "LEFT":
        return "LEFT"
    if node.side == "" and node.kind in ("", "INNER"):
        return "INNER"
    return None


def _reject_unsupported_clauses(parsed: exp.Select) -> None:
    unsupported = {
        "with_": "WITH",
        "group": "GROUP BY",
        "having": "HAVING",
        "qualify": "QUALIFY",
        "order": "ORDER BY",
        "limit": "LIMIT",
    }
    for arg_name, clause_name in unsupported.items():
        if parsed.args.get(arg_name) is not None:
            raise UnsupportedSqlError(f"{clause_name} is not supported yet.")


def _where_predicates(where: exp.Where | None) -> list[Predicate | ExistsPredicate]:
    if where is None:
        return []
    return _predicate_expression(where.this)


def _predicate_expression(node: exp.Expression) -> list[Predicate | ExistsPredicate]:
    if isinstance(node, exp.And):
        return [
            *_predicate_expression(node.this),
            *_predicate_expression(node.expression),
        ]
    if isinstance(node, exp.EQ | exp.GT | exp.GTE | exp.LT | exp.LTE):
        return [_comparison(node)]
    if isinstance(node, exp.Is | exp.Not):
        return [_null_predicate(node)]
    if isinstance(node, exp.Exists):
        return [_exists_predicate(node)]
    raise UnsupportedSqlError(
        "Only ANDed column/literal comparisons, NULL predicates, and simple EXISTS "
        "predicates are supported."
    )


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


def _null_predicate(node: exp.Expression) -> Predicate:
    if isinstance(node, exp.Not):
        inner = node.this
        operator = "IS NOT NULL"
    else:
        inner = node
        operator = "IS NULL"

    if (
        not isinstance(inner, exp.Is)
        or not isinstance(inner.this, exp.Column)
        or not isinstance(inner.expression, exp.Null)
    ):
        raise UnsupportedSqlError("Only IS NULL and IS NOT NULL predicates are supported.")

    return Predicate(
        left=ColumnRef(table=inner.this.table or None, name=inner.this.name),
        operator=operator,
        right=None,
    )


def _exists_predicate(node: exp.Exists) -> ExistsPredicate:
    select = node.this
    if not isinstance(select, exp.Select):
        raise UnsupportedSqlError("EXISTS predicates must contain a SELECT subquery.")

    _reject_unsupported_clauses(select)
    if select.args.get("joins"):
        raise UnsupportedSqlError("EXISTS subqueries with JOINs are not supported yet.")
    if select.args.get("distinct") is not None:
        raise UnsupportedSqlError("EXISTS subqueries with DISTINCT are not supported yet.")

    expressions = select.expressions
    if len(expressions) != 1 or not isinstance(expressions[0], exp.Literal):
        raise UnsupportedSqlError("EXISTS subqueries must project literal 1.")
    if str(expressions[0].this) != "1":
        raise UnsupportedSqlError("EXISTS subqueries must project literal 1.")

    from_expr = select.args.get("from_")
    if from_expr is None or not isinstance(from_expr.this, exp.Table):
        raise UnsupportedSqlError("EXISTS subqueries must read from one direct table.")

    where = select.args.get("where")
    if not isinstance(where, exp.Where) or not isinstance(where.this, exp.EQ):
        raise UnsupportedSqlError("EXISTS subqueries must use one equality WHERE predicate.")
    if not isinstance(where.this.this, exp.Column) or not isinstance(
        where.this.expression,
        exp.Column,
    ):
        raise UnsupportedSqlError("EXISTS predicates must compare two columns.")

    return ExistsPredicate(
        table=from_expr.this.name,
        table_sql=_relation_sql_without_alias(from_expr.this),
        alias=from_expr.this.alias or None,
        condition=JoinCondition(
            left=ColumnRef(table=where.this.this.table or None, name=where.this.this.name),
            right=ColumnRef(
                table=where.this.expression.table or None,
                name=where.this.expression.name,
            ),
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


def _relation_sql_without_alias(node: exp.Table) -> str:
    relation = node.copy()
    relation.set("alias", None)
    return relation.sql(dialect="snowflake")
