from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import ColumnRef, SelectQuery
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


class PredicatePushdown:
    rule_name = "predicate_pushdown"

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        del constraints

        if query.subquery is None or not query.predicates:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query is not a filtered subquery.",
            )

        inner = query.subquery
        if query.distinct or inner.distinct:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="Predicate pushdown with DISTINCT is not supported yet.",
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
            projections=tuple(column.unqualified() for column in query.projections),
            predicates=(
                *inner.predicates,
                *(predicate.unqualified() for predicate in query.predicates),
            ),
            distinct=False,
            raw_sql=query.raw_sql,
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
    return tuple(column.name for column in outer) == tuple(column.name for column in inner)


def _predicate_can_push(
    column: ColumnRef,
    alias: str | None,
    inner_projection_names: set[str],
) -> bool:
    if column.name not in inner_projection_names:
        return False
    return column.table is None or column.table == alias
