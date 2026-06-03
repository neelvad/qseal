from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import SelectQuery
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.join_elimination import RemoveUnusedLeftJoin
from snowprove.rewrites.not_null_filter import RemoveRedundantNotNullFilter
from snowprove.rewrites.predicate_pushdown import PredicatePushdown
from snowprove.verifier.model import VerificationResult


def check_equivalence(
    original: SelectQuery,
    rewritten: SelectQuery,
    constraints: ConstraintCatalog,
) -> VerificationResult:
    if original == rewritten:
        return VerificationResult(
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            reason="Queries normalize to the same supported IR.",
        )

    if _is_distinct_removal(original, rewritten):
        return _check_distinct_removal(original, rewritten, constraints)

    not_null_filter = RemoveRedundantNotNullFilter().apply(original, constraints)
    if (
        not_null_filter.status == VerificationStatus.PROVEN_EQUIVALENT
        and not_null_filter.rewritten_sql is not None
    ):
        expected = _parse_expected(not_null_filter.rewritten_sql, rewritten)
        if _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                assumptions=not_null_filter.assumptions,
                reason=not_null_filter.reason,
            )

    join_elimination = RemoveUnusedLeftJoin().apply(original, constraints)
    if (
        join_elimination.status == VerificationStatus.PROVEN_EQUIVALENT
        and join_elimination.rewritten_sql is not None
    ):
        expected = _parse_expected(join_elimination.rewritten_sql, rewritten)
        if _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                assumptions=join_elimination.assumptions,
                reason=join_elimination.reason,
            )

    pushdown = PredicatePushdown().apply(original, constraints)
    if (
        pushdown.status == VerificationStatus.PROVEN_EQUIVALENT
        and pushdown.rewritten_sql is not None
    ):
        expected = _parse_expected(pushdown.rewritten_sql, rewritten)

        if _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                assumptions=pushdown.assumptions,
                reason=pushdown.reason,
            )

    return VerificationResult(
        status=VerificationStatus.UNKNOWN,
        original_sql=original.raw_sql,
        rewritten_sql=rewritten.raw_sql,
        reason="No verifier rule applies to this query pair.",
    )


def _same_normalized_query(left: SelectQuery, right: SelectQuery) -> bool:
    return (
        left.table == right.table
        and left.table_sql == right.table_sql
        and left.table_alias == right.table_alias
        and left.subquery == right.subquery
        and left.alias == right.alias
        and left.joins == right.joins
        and left.projections == right.projections
        and left.predicates == right.predicates
        and left.distinct == right.distinct
    )


def _parse_expected(sql: str, fallback: SelectQuery) -> SelectQuery:
    try:
        from snowprove.parser.sqlglot_parser import parse_select

        return parse_select(sql)
    except Exception:
        return fallback


def _is_distinct_removal(original: SelectQuery, rewritten: SelectQuery) -> bool:
    return (
        original.distinct
        and not rewritten.distinct
        and original.table == rewritten.table
        and original.table_sql == rewritten.table_sql
        and original.table_alias == rewritten.table_alias
        and original.subquery == rewritten.subquery
        and original.joins == rewritten.joins
        and original.projections == rewritten.projections
        and original.predicates == rewritten.predicates
    )


def _check_distinct_removal(
    original: SelectQuery,
    rewritten: SelectQuery,
    constraints: ConstraintCatalog,
) -> VerificationResult:
    projected_columns = tuple(column.name for column in original.projections)
    table_name = original.table_name()
    if table_name is None:
        return VerificationResult(
            status=VerificationStatus.UNSUPPORTED,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            reason="DISTINCT removal checks are only supported for direct table queries.",
        )

    table = constraints.table(table_name)

    if table is not None and table.has_unique_key(projected_columns):
        return VerificationResult(
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            assumptions=(
                f"{table_name} has a trusted unique key contained in "
                f"({', '.join(projected_columns)}).",
            ),
            reason="DISTINCT cannot remove rows when the projection contains a unique key.",
        )

    return VerificationResult(
        status=VerificationStatus.NOT_EQUIVALENT,
        original_sql=original.raw_sql,
        rewritten_sql=rewritten.raw_sql,
        reason="Removing DISTINCT is unsafe without a trusted uniqueness constraint.",
        counterexample=(
            f"If {table_name} contains two rows with the same "
            f"({', '.join(projected_columns)}) values, the original returns one row "
            "and the rewrite returns both rows."
        ),
    )
