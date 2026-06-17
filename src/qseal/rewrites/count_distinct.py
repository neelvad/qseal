from sqlglot import exp, parse_one

from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import SqlDialect
from qseal.ir.model import ColumnRef, SelectQuery
from qseal.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class RemoveRedundantCountDistinct:
    rule_name = "remove_redundant_count_distinct"

    def matches(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
    ) -> tuple[RewriteMatch, ...]:
        matches = []
        for index, projection in enumerate(query.projections):
            suggestion = self._suggest_for_index(query, constraints, index)
            if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
                continue
            column = _count_distinct_column(projection, query.dialect)
            if column is None:
                continue
            matches.append(
                RewriteMatch(
                    rule_name=self.rule_name,
                    match_id=f"projection:{index}",
                    target_kind="projection",
                    target_index=index,
                    description=(
                        f"Rewrite COUNT(DISTINCT {column.name}) to COUNT({column.name})."
                    ),
                    metadata={"column": column.name},
                )
            )
        return tuple(matches)

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
            reason="Query does not project COUNT(DISTINCT column).",
        )

    def _suggest_for_index(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        index: int,
    ) -> RewriteSuggestion:
        projection = query.projections[index]
        column = _count_distinct_column(projection, query.dialect)
        if column is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Projection is not COUNT(DISTINCT column).",
            )

        if query.distinct:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="COUNT(DISTINCT) removal with SELECT DISTINCT is not supported yet.",
            )

        if query.joins:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="COUNT(DISTINCT) removal with joins is not supported yet.",
            )

        if query.having:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="COUNT(DISTINCT) removal with HAVING is not supported yet.",
            )

        if query.qualify:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="COUNT(DISTINCT) removal with QUALIFY is not supported yet.",
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
        if table_name is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="COUNT(DISTINCT) removal is only supported for direct table queries.",
            )

        relation = query.table_alias or query.table
        if column.table is not None and column.table != relation:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="COUNT(DISTINCT) column does not reference the base relation.",
            )

        table = constraints.table(table_name)
        unique_key = (
            None if table is None else table.non_null_unique_key_contained_in((column.name,))
        )
        if unique_key is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=(
                    f"{table_name}.{column.name} is not known to be a non-null unique key."
                ),
            )

        projections = list(query.projections)
        projections[index] = _without_distinct(projection, query.dialect)
        rewritten = query.model_copy(update={"projections": tuple(projections)})
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=(
                f"{table_name} has a trusted non-null unique key contained in "
                f"({', '.join(unique_key)}).",
            ),
            reason=(
                "COUNT(DISTINCT column) equals COUNT(column) when the counted "
                "column is trusted unique and non-null."
            ),
        )


def _count_distinct_column(
    projection: ColumnRef,
    dialect: SqlDialect,
) -> ColumnRef | None:
    expression = _projection_expression(projection, dialect)
    if expression is None:
        return None
    if not isinstance(expression, exp.Count):
        return None
    distinct = expression.this
    if (
        not isinstance(distinct, exp.Distinct)
        or len(distinct.expressions) != 1
        or not isinstance(distinct.expressions[0], exp.Column)
    ):
        return None
    column = distinct.expressions[0]
    return ColumnRef(table=column.table or None, name=column.name)


def _without_distinct(projection: ColumnRef, dialect: SqlDialect) -> ColumnRef:
    column = _count_distinct_column(projection, dialect)
    if column is None:
        raise ValueError("Projection is not COUNT(DISTINCT column).")
    column_sql = f"{column.table}.{column.name}" if column.table else column.name
    return projection.model_copy(update={"expression_sql": f"COUNT({column_sql})"})


def _projection_expression(
    projection: ColumnRef,
    dialect: SqlDialect,
) -> exp.Expression | None:
    if projection.expression_sql is None:
        return None
    try:
        parsed = parse_one(f"SELECT {projection.expression_sql}", read=dialect)
    except Exception:
        return None
    expression = parsed.expressions[0]
    return expression.this if isinstance(expression, exp.Alias) else expression
