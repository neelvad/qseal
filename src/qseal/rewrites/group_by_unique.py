from sqlglot import exp, parse_one

from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import SqlDialect
from qseal.ir.model import ColumnRef, SelectQuery
from qseal.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class CollapseUniqueGroupBy:
    rule_name = "collapse_unique_group_by"

    def matches(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
    ) -> tuple[RewriteMatch, ...]:
        suggestion = self._suggest(query, constraints)
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            return ()
        return (
            RewriteMatch(
                rule_name=self.rule_name,
                match_id="query:group_by",
                target_kind="query",
                description="Collapse GROUP BY over a trusted non-null unique key.",
            ),
        )

    def apply_match(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        match: RewriteMatch,
    ) -> RewriteSuggestion:
        if match.rule_name != self.rule_name or match.match_id != "query:group_by":
            raise ValueError(f"Invalid match for {self.rule_name}: {match.match_id}.")
        suggestion = self._suggest(query, constraints)
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            raise ValueError(f"Match is no longer applicable: {match.match_id}.")
        return suggestion

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        return self._suggest(query, constraints)

    def _suggest(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        if not query.group_by:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query has no GROUP BY.",
            )

        if query.distinct or query.joins or query.having or query.qualify:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason=(
                    "Unique GROUP BY collapse with DISTINCT, joins, HAVING, "
                    "or QUALIFY is not supported yet."
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
                reason="Unique GROUP BY collapse is only supported for direct table queries.",
            )
        if table is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason=f"No trusted constraints found for table {table_name}.",
            )

        group_columns = tuple(
            key.column.name for key in query.group_by if key.column is not None
        )
        if len(group_columns) != len(query.group_by):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Unique GROUP BY collapse only supports direct column keys.",
            )
        unique_key = table.non_null_unique_key_contained_in(group_columns)
        if unique_key is None:
            if not table.has_unique_key(group_columns):
                return RewriteSuggestion(
                    rule_name=self.rule_name,
                    status=VerificationStatus.NOT_APPLICABLE,
                    original_sql=query.raw_sql,
                    reason="GROUP BY columns do not contain a trusted unique key.",
                )
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="GROUP BY columns are not known to contain a non-null unique key.",
            )

        rewritten_projections = []
        for projection in query.projections:
            rewritten_projection = _collapsed_projection(
                projection,
                query=query,
                group_columns=group_columns,
            )
            if rewritten_projection is None:
                return RewriteSuggestion(
                    rule_name=self.rule_name,
                    status=VerificationStatus.NOT_APPLICABLE,
                    original_sql=query.raw_sql,
                    reason=(
                        "GROUP BY collapse only supports grouped columns and "
                        "MAX/MIN/ANY_VALUE over direct columns."
                    ),
                )
            rewritten_projections.append(rewritten_projection)

        rewritten = query.model_copy(
            update={"projections": tuple(rewritten_projections), "group_by": ()}
        )
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
                "Each GROUP BY key contains at most one non-null unique row, "
                "so supported aggregates over each group equal the row value."
            ),
        )


def _collapsed_projection(
    projection: ColumnRef,
    *,
    query: SelectQuery,
    group_columns: tuple[str, ...],
) -> ColumnRef | None:
    if projection.is_direct_column():
        if not _column_belongs_to_query(projection, query):
            return None
        if projection.name not in group_columns:
            return None
        return projection

    aggregate_column = _safe_single_row_aggregate_column(projection, query.dialect)
    if aggregate_column is None:
        return None
    if not _column_belongs_to_query(aggregate_column, query):
        return None
    return aggregate_column.model_copy(update={"alias": projection.alias})


def _safe_single_row_aggregate_column(
    projection: ColumnRef,
    dialect: SqlDialect,
) -> ColumnRef | None:
    if projection.expression_sql is None or projection.alias is None:
        return None
    try:
        parsed = parse_one(f"SELECT {projection.expression_sql}", read=dialect)
    except Exception:
        return None
    expression = parsed.expressions[0]
    expression = expression.this if isinstance(expression, exp.Alias) else expression
    if not isinstance(expression, exp.Max | exp.Min | exp.AnyValue):
        return None
    if not isinstance(expression.this, exp.Column):
        return None
    return ColumnRef(
        table=expression.this.table or None,
        name=expression.this.name,
    )


def _column_belongs_to_query(column: ColumnRef, query: SelectQuery) -> bool:
    if column.table is None:
        return True
    if query.table_alias is not None:
        return column.table == query.table_alias
    return column.table in {query.table, query.table.split(".")[-1] if query.table else None}
