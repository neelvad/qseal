from sqlglot import exp, parse_one

from qseal.constraints.model import ConstraintCatalog, TableConstraints
from qseal.dialects import SqlDialect
from qseal.ir.model import ColumnRef, LiteralValue, SelectQuery
from qseal.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class SimplifyAcceptedValuesCase:
    rule_name = "simplify_accepted_values_case"

    def matches(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
    ) -> tuple[RewriteMatch, ...]:
        return tuple(
            RewriteMatch(
                rule_name=self.rule_name,
                match_id=f"projection:{index}",
                target_kind="projection",
                target_index=index,
                description="Simplify accepted-values CASE projection.",
            )
            for index in range(len(query.projections))
            if self._suggest_for_index(query, constraints, index).status
            == VerificationStatus.PROVEN_EQUIVALENT
        )

    def apply_match(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        match: RewriteMatch,
    ) -> RewriteSuggestion:
        if match.rule_name != self.rule_name or not match.match_id.startswith(
            "projection:"
        ):
            raise ValueError(f"Invalid match for {self.rule_name}: {match.match_id}.")
        index = int(match.match_id.split(":", maxsplit=1)[1])
        suggestion = self._suggest_for_index(query, constraints, index)
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            raise ValueError(f"Match is no longer applicable: {match.match_id}.")
        return suggestion

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        first_blocker = None
        for index in range(len(query.projections)):
            suggestion = self._suggest_for_index(query, constraints, index)
            if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT:
                return suggestion
            if (
                suggestion.status != VerificationStatus.NOT_APPLICABLE
                and first_blocker is None
            ):
                first_blocker = suggestion
        if first_blocker is not None:
            return first_blocker
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.NOT_APPLICABLE,
            original_sql=query.raw_sql,
            reason="Query has no accepted-values CASE simplification.",
        )

    def _suggest_for_index(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        index: int,
    ) -> RewriteSuggestion:
        projection = query.projections[index]
        case = _case_expression(projection, query.dialect)
        if case is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Projection is not a searched CASE expression.",
            )

        if query.joins or query.group_by or query.having or query.qualify:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason=(
                    "Accepted-values CASE simplification with joins, GROUP BY, "
                    "HAVING, or QUALIFY is not supported yet."
                ),
            )

        if query.references_cte_relation():
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=(
                    "The query references a CTE relation, so a standalone "
                    "rewritten query cannot be generated."
                ),
            )

        table_name = query.table_name()
        table = constraints.table(table_name) if table_name is not None else None
        if table_name is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason=(
                    "Accepted-values CASE simplification is only supported for "
                    "direct table queries."
                ),
            )
        if table is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason=f"No trusted constraints found for table {table_name}.",
            )

        result = _simplified_case(
            case,
            table=table,
            table_name=table_name,
            table_alias=query.table_alias,
            dialect=query.dialect,
        )
        if result is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="No CASE branches are proven redundant.",
            )

        projections = list(query.projections)
        projections[index] = projection.model_copy(update={"expression_sql": result.sql})
        rewritten = query.model_copy(update={"projections": tuple(projections)})
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=result.assumptions,
            reason=(
                "Accepted-values and non-null premises prove one or more CASE "
                "branches unreachable or always selected."
            ),
        )


class _SimplifiedCase:
    def __init__(self, sql: str, assumptions: tuple[str, ...]) -> None:
        self.sql = sql
        self.assumptions = assumptions


def _case_expression(projection: ColumnRef, dialect: SqlDialect) -> exp.Case | None:
    if projection.expression_sql is None:
        return None
    try:
        parsed = parse_one(f"SELECT {projection.expression_sql}", read=dialect)
    except Exception:
        return None
    expression = parsed.expressions[0]
    expression = expression.this if isinstance(expression, exp.Alias) else expression
    if isinstance(expression, exp.Case) and expression.args.get("this") is None:
        return expression
    return None


def _simplified_case(
    case: exp.Case,
    *,
    table: TableConstraints,
    table_name: str,
    table_alias: str | None,
    dialect: SqlDialect,
) -> _SimplifiedCase | None:
    kept_ifs = []
    assumptions = []
    changed = False
    for branch in case.args.get("ifs") or []:
        verdict = _condition_verdict(branch.this, table, table_name, table_alias)
        if verdict is None:
            kept_ifs.append(branch)
            continue
        assumptions.extend(verdict.assumptions)
        if verdict.always_false:
            changed = True
            continue
        if verdict.always_true and not kept_ifs:
            return _SimplifiedCase(
                sql=branch.args["true"].sql(dialect=dialect),
                assumptions=tuple(dict.fromkeys(assumptions)),
            )
        kept_ifs.append(branch)

    if not changed:
        return None
    default = case.args.get("default")
    if not kept_ifs:
        if default is None:
            return _SimplifiedCase(
                sql="NULL",
                assumptions=tuple(dict.fromkeys(assumptions)),
            )
        return _SimplifiedCase(
            sql=default.sql(dialect=dialect),
            assumptions=tuple(dict.fromkeys(assumptions)),
        )
    rewritten = case.copy()
    rewritten.set("ifs", kept_ifs)
    return _SimplifiedCase(
        sql=rewritten.sql(dialect=dialect),
        assumptions=tuple(dict.fromkeys(assumptions)),
    )


class _ConditionVerdict:
    def __init__(
        self,
        *,
        always_true: bool = False,
        always_false: bool = False,
        assumptions: tuple[str, ...],
    ) -> None:
        self.always_true = always_true
        self.always_false = always_false
        self.assumptions = assumptions


def _condition_verdict(
    condition: exp.Expression,
    table: TableConstraints,
    table_name: str,
    table_alias: str | None,
) -> _ConditionVerdict | None:
    if isinstance(condition, exp.EQ):
        if not isinstance(condition.this, exp.Column | exp.Literal) or not isinstance(
            condition.expression,
            exp.Column | exp.Literal,
        ):
            return None
        column, literal = _column_literal(condition.this, condition.expression)
        if column is None or literal is None:
            return None
        domain = _accepted_domain(column, table, table_name, table_alias)
        if domain is None:
            return None
        literal_key = _literal_key(literal)
        return _domain_verdict(
            column,
            table_name,
            domain,
            {literal_key},
        )

    if isinstance(condition, exp.In):
        if not isinstance(condition.this, exp.Column):
            return None
        if any(not isinstance(expression, exp.Literal) for expression in condition.expressions):
            return None
        domain = _accepted_domain(condition.this, table, table_name, table_alias)
        if domain is None:
            return None
        predicate_values = {_literal_key(expression) for expression in condition.expressions}
        return _domain_verdict(condition.this, table_name, domain, predicate_values)

    return None


def _domain_verdict(
    column: exp.Column,
    table_name: str,
    domain: set[tuple[str, bool]],
    predicate_values: set[tuple[str, bool]],
) -> _ConditionVerdict | None:
    if domain <= predicate_values:
        return _ConditionVerdict(
            always_true=True,
            assumptions=_domain_assumptions(table_name, column.name, domain),
        )
    if domain.isdisjoint(predicate_values):
        return _ConditionVerdict(
            always_false=True,
            assumptions=_domain_assumptions(table_name, column.name, domain),
        )
    return None


def _column_literal(
    left: exp.Expression,
    right: exp.Expression,
) -> tuple[exp.Column | None, exp.Literal | None]:
    if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
        return left, right
    if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
        return right, left
    return None, None


def _accepted_domain(
    column: exp.Column,
    table: TableConstraints,
    table_name: str,
    table_alias: str | None,
) -> set[tuple[str, bool]] | None:
    if column.table:
        valid_prefixes = {table_alias} if table_alias is not None else {
            table_name,
            table_name.split(".")[-1],
        }
        if column.table not in valid_prefixes:
            return None
    constraint = table.columns.get(column.name)
    if (
        constraint is None
        or constraint.nullable is not False
        or not constraint.accepted_values
    ):
        return None
    return {
        (accepted_value.value, accepted_value.is_string)
        for accepted_value in constraint.accepted_values
    }


def _literal_key(literal: exp.Literal) -> tuple[str, bool]:
    return str(literal.this), bool(literal.is_string)


def _domain_assumptions(
    table_name: str,
    column_name: str,
    domain: set[tuple[str, bool]],
) -> tuple[str, ...]:
    values = ", ".join(_value_sql(value) for value in sorted(domain))
    return (
        f"{table_name}.{column_name} has accepted values ({values}).",
        f"{table_name}.({column_name}) is trusted non-null.",
    )


def _value_sql(value: tuple[str, bool]) -> str:
    literal = LiteralValue(value=value[0], is_string=value[1])
    return literal.to_sql()
