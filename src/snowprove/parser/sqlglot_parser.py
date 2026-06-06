import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from snowprove.ir.model import (
    ColumnRef,
    ExistsPredicate,
    HavingPredicate,
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

    ctes = _cte_map(parsed.args.get("with_"))
    parsed = _resolve_top_level_cte_select(parsed, ctes)

    from_expr = parsed.args.get("from_")
    if from_expr is None or from_expr.this is None:
        raise UnsupportedSqlError("SELECT statements must include a FROM table.")

    _reject_unsupported_clauses(parsed)

    source = _source(from_expr.this, ctes)
    joins = [_join(join, ctes) for join in parsed.args.get("joins") or []]
    group_by = _group_by_columns(parsed.args.get("group"))
    having = _having_predicates(parsed.args.get("having"), has_group_by=bool(group_by))
    projections = [
        _projection_to_column(expr, allow_aggregate=bool(group_by))
        for expr in parsed.expressions
    ]
    predicates = _where_predicates(parsed.args.get("where"))

    return SelectQuery(
        **source,
        joins=tuple(joins),
        projections=tuple(projections),
        predicates=tuple(predicates),
        group_by=tuple(group_by),
        having=tuple(having),
        distinct=parsed.args.get("distinct") is not None,
        raw_sql=sql.strip(),
    )


def _source(node: exp.Expression, ctes: dict[str, exp.Select] | None = None) -> dict[str, object]:
    ctes = ctes or {}
    if isinstance(node, exp.Table):
        if node.name in ctes:
            return _cte_source(node, ctes)
        return {
            "table": node.name,
            "table_sql": _relation_sql_without_alias(node),
            "table_alias": node.alias or None,
        }
    if isinstance(node, exp.Subquery):
        if not isinstance(node.this, exp.Select):
            raise UnsupportedSqlError("Only SELECT subqueries are supported.")
        return {
            "subquery": _parse_select_expression(node.this, ctes),
            "alias": node.alias or None,
        }
    raise UnsupportedSqlError("Only direct tables and simple subqueries are supported.")


def _parse_select_expression(
    parsed: exp.Select,
    ctes: dict[str, exp.Select] | None = None,
) -> SelectQuery:
    ctes = ctes or {}
    if parsed.args.get("with_") is not None:
        raise UnsupportedSqlError("Nested WITH clauses are not supported yet.")

    parsed = _resolve_top_level_cte_select(parsed, ctes)
    from_expr = parsed.args.get("from_")
    if from_expr is None or from_expr.this is None:
        raise UnsupportedSqlError("SELECT statements must include a FROM table.")

    _reject_unsupported_clauses(parsed)

    source = _source(from_expr.this, ctes)
    joins = [_join(join, ctes) for join in parsed.args.get("joins") or []]
    group_by = _group_by_columns(parsed.args.get("group"))
    having = _having_predicates(parsed.args.get("having"), has_group_by=bool(group_by))
    projections = [
        _projection_to_column(expr, allow_aggregate=bool(group_by))
        for expr in parsed.expressions
    ]
    predicates = _where_predicates(parsed.args.get("where"))

    return SelectQuery(
        **source,
        joins=tuple(joins),
        projections=tuple(projections),
        predicates=tuple(predicates),
        group_by=tuple(group_by),
        having=tuple(having),
        distinct=parsed.args.get("distinct") is not None,
        raw_sql=parsed.sql(dialect="snowflake"),
    )


def _cte_map(with_expr: exp.With | None) -> dict[str, exp.Select]:
    if with_expr is None:
        return {}
    if with_expr.args.get("recursive"):
        raise UnsupportedSqlError("Recursive CTEs are not supported yet.")

    ctes = {}
    for cte in with_expr.expressions:
        if not isinstance(cte, exp.CTE) or not isinstance(cte.this, exp.Select):
            raise UnsupportedSqlError("Only SELECT CTEs are supported yet.")
        if cte.alias in ctes:
            raise UnsupportedSqlError(f"Duplicate CTE name is not supported: {cte.alias}.")
        ctes[cte.alias] = cte.this
    return ctes


def _resolve_top_level_cte_select(
    parsed: exp.Select,
    ctes: dict[str, exp.Select],
    seen: frozenset[str] = frozenset(),
) -> exp.Select:
    from_expr = parsed.args.get("from_")
    if from_expr is None or not isinstance(from_expr.this, exp.Table):
        return parsed
    if from_expr.this.name not in ctes:
        return parsed

    cte_name = from_expr.this.name
    if cte_name in seen:
        raise UnsupportedSqlError(f"Recursive CTE reference is not supported: {cte_name}.")

    if _select_is_star_passthrough(parsed, allow_with=True):
        resolved = _resolve_top_level_cte_select(ctes[cte_name], ctes, seen | {cte_name})
        if parsed.args.get("distinct") is not None:
            resolved = resolved.copy()
            resolved.set("distinct", parsed.args.get("distinct"))
        return resolved

    if _select_is_projection_passthrough(parsed):
        return _inline_cte_projection(parsed, ctes[cte_name], ctes, seen | {cte_name})

    return parsed


def _inline_cte_projection(
    outer: exp.Select,
    cte: exp.Select,
    ctes: dict[str, exp.Select],
    seen: frozenset[str],
) -> exp.Select:
    resolved = _resolve_top_level_cte_select(cte, ctes, seen)
    if not _select_is_simple_projection(resolved):
        return outer

    projection_map = _projection_map(resolved.expressions)
    expressions = []
    for projection in outer.expressions:
        if isinstance(projection, exp.Star):
            expressions.extend(expression.copy() for expression in resolved.expressions)
            continue

        projection_name = _projection_reference_name(projection)
        if projection_name is None or projection_name not in projection_map:
            return outer

        inner_projection = projection_map[projection_name]
        outer_alias = projection.alias if isinstance(projection, exp.Alias) else None
        expressions.append(_project_with_alias(inner_projection, outer_alias))

    inlined = resolved.copy()
    inlined.set("expressions", expressions)
    inlined.set("distinct", outer.args.get("distinct"))
    return inlined


def _cte_source(node: exp.Table, ctes: dict[str, exp.Select]) -> dict[str, object]:
    cte_name = node.name
    try:
        source = _passthrough_cte_source(cte_name, ctes)
    except UnsupportedSqlError:
        _validate_opaque_cte_relation(cte_name, ctes)
        source = {
            "table": cte_name,
            "table_sql": cte_name,
            "table_alias": node.alias or None,
        }
    alias = node.alias or None
    if alias is not None:
        source = {**source, "table_alias": alias}
    return source


def _validate_opaque_cte_relation(
    cte_name: str,
    ctes: dict[str, exp.Select],
    seen: frozenset[str] = frozenset(),
) -> None:
    if cte_name in seen:
        raise UnsupportedSqlError(f"Recursive CTE reference is not supported: {cte_name}.")

    cte = ctes[cte_name]
    if cte.args.get("with_") is not None:
        raise UnsupportedSqlError("Nested WITH clauses are not supported yet.")
    if cte.args.get("joins"):
        raise UnsupportedSqlError("CTE relation references with JOINs are not supported yet.")
    if cte.args.get("distinct") is not None:
        raise UnsupportedSqlError("CTE relation references with DISTINCT are not supported yet.")
    for arg_name, clause_name in (
        ("qualify", "QUALIFY"),
        ("order", "ORDER BY"),
        ("limit", "LIMIT"),
    ):
        if cte.args.get(arg_name) is not None:
            raise UnsupportedSqlError(
                f"CTE relation references with {clause_name} are not supported yet."
            )

    from_expr = cte.args.get("from_")
    if from_expr is None or not isinstance(from_expr.this, exp.Table):
        raise UnsupportedSqlError("CTE relation references must read from one direct table.")
    if from_expr.this.name in ctes:
        _validate_opaque_cte_relation(from_expr.this.name, ctes, seen | {cte_name})

    group_by = _group_by_columns(cte.args.get("group"))
    for projection in cte.expressions:
        _projection_to_column(projection, allow_aggregate=bool(group_by))
    _where_predicates(cte.args.get("where"))
    _having_predicates(cte.args.get("having"), has_group_by=bool(group_by))


def _passthrough_cte_source(
    cte_name: str,
    ctes: dict[str, exp.Select],
    seen: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if cte_name in seen:
        raise UnsupportedSqlError(f"Recursive CTE reference is not supported: {cte_name}.")

    cte = ctes[cte_name]
    if not _select_is_star_passthrough(cte):
        raise UnsupportedSqlError(
            "CTE references in FROM are only supported for SELECT * pass-through CTEs."
        )

    from_expr = cte.args.get("from_")
    if from_expr is None or not isinstance(from_expr.this, exp.Table):
        raise UnsupportedSqlError("CTE pass-through sources must read from one direct table.")

    table = from_expr.this
    if table.name in ctes:
        return _passthrough_cte_source(table.name, ctes, seen | {cte_name})

    return {
        "table": table.name,
        "table_sql": _relation_sql_without_alias(table),
        "table_alias": table.alias or None,
    }


def _select_is_star_passthrough(parsed: exp.Select, allow_with: bool = False) -> bool:
    if parsed.args.get("with_") is not None and not allow_with:
        return False
    if parsed.args.get("joins"):
        return False
    if parsed.args.get("where") is not None:
        return False
    if parsed.args.get("distinct") is not None:
        return False
    for arg_name in ("group", "having", "qualify", "order", "limit"):
        if parsed.args.get(arg_name) is not None:
            return False
    return len(parsed.expressions) == 1 and isinstance(parsed.expressions[0], exp.Star)


def _select_is_projection_passthrough(parsed: exp.Select) -> bool:
    if parsed.args.get("joins"):
        return False
    if parsed.args.get("where") is not None:
        return False
    for arg_name in ("group", "having", "qualify", "order", "limit"):
        if parsed.args.get(arg_name) is not None:
            return False
    return all(
        _projection_reference_name(projection) is not None
        for projection in parsed.expressions
    )


def _select_is_simple_projection(parsed: exp.Select) -> bool:
    if parsed.args.get("with_") is not None:
        return False
    if parsed.args.get("joins"):
        return False
    if parsed.args.get("where") is not None:
        return False
    if parsed.args.get("distinct") is not None:
        return False
    for arg_name in ("group", "having", "qualify", "order", "limit"):
        if parsed.args.get(arg_name) is not None:
            return False
    return all(_projection_output_name(projection) is not None for projection in parsed.expressions)


def _projection_map(projections: list[exp.Expression]) -> dict[str, exp.Expression]:
    return {
        name: projection
        for projection in projections
        if (name := _projection_output_name(projection)) is not None
    }


def _projection_output_name(projection: exp.Expression) -> str | None:
    if isinstance(projection, exp.Alias):
        return projection.alias
    if isinstance(projection, exp.Column):
        return projection.name
    return None


def _projection_reference_name(projection: exp.Expression) -> str | None:
    if isinstance(projection, exp.Star):
        return "*"
    if isinstance(projection, exp.Column):
        return projection.name
    if isinstance(projection, exp.Alias) and isinstance(projection.this, exp.Column):
        return projection.this.name
    return None


def _project_with_alias(projection: exp.Expression, alias: str | None) -> exp.Expression:
    if alias is None:
        return projection.copy()
    expression = projection.this if isinstance(projection, exp.Alias) else projection
    return exp.alias_(expression.copy(), alias, copy=False)


def _projection_to_column(
    node: exp.Expression,
    allow_aggregate: bool = False,
) -> ColumnRef:
    if isinstance(node, exp.Star):
        return ColumnRef(name="*", is_star=True)
    if isinstance(node, exp.Column):
        if isinstance(node.this, exp.Star):
            return ColumnRef(table=node.table or None, name="*", is_star=True)
        return ColumnRef(table=node.table or None, name=node.name)
    if isinstance(node, exp.Alias) and isinstance(node.this, exp.Column):
        return ColumnRef(
            table=node.this.table or None,
            name=node.this.name,
            alias=node.alias,
        )
    if isinstance(
        node,
        exp.Alias,
    ) and _is_supported_opaque_projection(node.this, allow_aggregate=allow_aggregate):
        return ColumnRef(
            name=node.alias,
            alias=node.alias,
            expression_sql=node.this.sql(dialect="snowflake"),
        )
    raise UnsupportedSqlError(
        "Only direct columns, stars, and simple aliased scalar projections are supported."
    )


def _is_supported_opaque_projection(
    node: exp.Expression,
    allow_aggregate: bool = False,
) -> bool:
    if _contains_aggregate(node) and not allow_aggregate:
        return False
    if isinstance(node, exp.AggFunc):
        return allow_aggregate
    return isinstance(
        node,
        exp.EQ
        | exp.NEQ
        | exp.GT
        | exp.GTE
        | exp.LT
        | exp.LTE
        | exp.Case
        | exp.Coalesce
        | exp.Add
        | exp.Sub
        | exp.Mul
        | exp.Div,
    )


def _contains_aggregate(node: exp.Expression) -> bool:
    return any(isinstance(child, exp.AggFunc) for child in node.walk())


def _group_by_columns(group: exp.Group | None) -> list[ColumnRef]:
    if group is None:
        return []
    if group.args.get("all"):
        raise UnsupportedSqlError("GROUP BY ALL is not supported yet.")

    columns = []
    for expression in group.expressions:
        if not isinstance(expression, exp.Column):
            raise UnsupportedSqlError("GROUP BY only supports direct column references.")
        columns.append(ColumnRef(table=expression.table or None, name=expression.name))
    return columns


def _having_predicates(
    having: exp.Having | None,
    has_group_by: bool,
) -> list[HavingPredicate]:
    if having is None:
        return []
    if not has_group_by:
        raise UnsupportedSqlError("HAVING without GROUP BY is not supported yet.")
    return [
        HavingPredicate(expression_sql=expression.sql(dialect="snowflake"))
        for expression in _having_expression(having.this)
    ]


def _having_expression(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return [
            *_having_expression(node.this),
            *_having_expression(node.expression),
        ]
    if isinstance(node, exp.EQ | exp.NEQ | exp.GT | exp.GTE | exp.LT | exp.LTE):
        _validate_having_comparison(node)
        return [node]
    raise UnsupportedSqlError(
        "Only ANDed aggregate or column comparisons are supported in HAVING."
    )


def _validate_having_comparison(node: exp.Expression) -> None:
    if not _is_supported_having_side(node.this):
        raise UnsupportedSqlError(
            "HAVING comparisons must compare an aggregate or column to a literal."
        )
    if not isinstance(node.expression, exp.Literal):
        raise UnsupportedSqlError(
            "HAVING comparisons must compare an aggregate or column to a literal."
        )


def _is_supported_having_side(node: exp.Expression) -> bool:
    return isinstance(node, exp.AggFunc | exp.Column)


def _join(node: exp.Join, ctes: dict[str, exp.Select] | None = None) -> Join:
    ctes = ctes or {}
    join_type = _join_type(node)
    if join_type is None:
        raise UnsupportedSqlError("Only INNER JOIN and LEFT JOIN are supported yet.")
    if not isinstance(node.this, exp.Table):
        raise UnsupportedSqlError("Only direct table JOIN targets are supported.")
    if node.this.name in ctes:
        _validate_opaque_cte_relation(node.this.name, ctes)

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
