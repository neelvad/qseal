from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import ColumnRef, Predicate, SelectQuery
from snowprove.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class PredicatePushdown:
    rule_name = "predicate_pushdown"

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
                match_id="subquery:0",
                target_kind="subquery",
                target_index=0,
                description="Push outer predicates through the projection subquery.",
                metadata={"predicate_count": len(query.predicates)},
            ),
        )

    def apply_match(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        match: RewriteMatch,
    ) -> RewriteSuggestion:
        if match.rule_name != self.rule_name or match.match_id != "subquery:0":
            raise ValueError(f"Invalid match for {self.rule_name}: {match.match_id}.")
        suggestion = self._suggest(query, constraints)
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            raise ValueError(f"Match is no longer applicable: {match.match_id}.")
        return suggestion

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        return self._suggest(query, constraints)

    def _suggest(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        del constraints

        if query.subquery is None or not query.predicates:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query is not a filtered subquery.",
            )

        inner = query.subquery
        if query.group_by or inner.group_by or query.having or inner.having:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Predicate pushdown with GROUP BY or HAVING is not supported yet.",
            )

        if query.joins or inner.joins:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="Predicate pushdown with joins is not supported yet.",
            )

        if query.distinct or inner.distinct:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="Predicate pushdown with DISTINCT is not supported yet.",
            )

        if any(not isinstance(predicate, Predicate) for predicate in query.predicates):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="Predicate pushdown with EXISTS predicates is not supported yet.",
            )

        if not inner.is_direct_table():
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="Predicate pushdown is only supported through one direct-table subquery.",
            )

        if not _same_projection_names(query.projections, inner.projections):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="Outer and inner projections do not match.",
        )

        inner_projection_names = {column.name for column in inner.projections}
        predicates_can_push = all(
            _predicate_can_push(predicate.left, query.alias, inner_projection_names)
            for predicate in query.predicates
        )
        if not predicates_can_push:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="Outer predicates reference columns not projected by the subquery.",
            )

        pushed = SelectQuery(
            table=inner.table,
            table_sql=inner.table_sql,
            table_alias=inner.table_alias,
            projections=tuple(column.unqualified() for column in query.projections),
            predicates=(
                *inner.predicates,
                *(predicate.unqualified() for predicate in query.predicates),
            ),
            distinct=False,
            raw_sql=query.raw_sql,
            dialect=query.dialect,
        )

        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=pushed.to_sql(),
            assumptions=(
                "Outer predicates reference only columns projected unchanged by the subquery.",
            ),
            reason=(
                "A filter over a simple projection can be evaluated before or after "
                "that projection."
            ),
        )


def _same_projection_names(
    outer: tuple[ColumnRef, ...],
    inner: tuple[ColumnRef, ...],
) -> bool:
    if any(not column.is_direct_column() for column in (*outer, *inner)):
        return False
    return tuple(column.name for column in outer) == tuple(column.name for column in inner)


def _predicate_can_push(
    column: ColumnRef,
    alias: str | None,
    inner_projection_names: set[str],
) -> bool:
    if column.name not in inner_projection_names:
        return False
    return column.table is None or column.table == alias
