from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import SelectQuery
from snowprove.rewrites.base import VerificationStatus
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

    return VerificationResult(
        status=VerificationStatus.UNKNOWN,
        original_sql=original.raw_sql,
        rewritten_sql=rewritten.raw_sql,
        reason="No verifier rule applies to this query pair.",
    )


def _is_distinct_removal(original: SelectQuery, rewritten: SelectQuery) -> bool:
    return (
        original.distinct
        and not rewritten.distinct
        and original.table == rewritten.table
        and original.projections == rewritten.projections
        and original.predicates == rewritten.predicates
    )


def _check_distinct_removal(
    original: SelectQuery,
    rewritten: SelectQuery,
    constraints: ConstraintCatalog,
) -> VerificationResult:
    projected_columns = tuple(column.name for column in original.projections)
    table = constraints.table(original.table)

    if table is not None and table.has_unique_key(projected_columns):
        return VerificationResult(
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            assumptions=(
                f"{original.table} has a trusted unique key contained in "
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
            f"If {original.table} contains two rows with the same "
            f"({', '.join(projected_columns)}) values, the original returns one row "
            "and the rewrite returns both rows."
        ),
    )
