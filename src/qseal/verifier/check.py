from qseal.constraints.model import ConstraintCatalog
from qseal.ir.model import SelectQuery
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.join_distinct_exists import RewriteJoinDistinctToExists
from qseal.rewrites.join_elimination import RemoveUnusedLeftJoin
from qseal.rewrites.not_null_filter import RemoveRedundantNotNullFilter
from qseal.rewrites.predicate_pushdown import PredicatePushdown
from qseal.rewrites.registry import apply_rewrite_match, available_rewrite_matches
from qseal.verifier.model import VerificationResult


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
            rule_name="normalized_identity",
            reason="Queries normalize to the same supported IR.",
        )

    for match in available_rewrite_matches(original, constraints):
        suggestion = apply_rewrite_match(original, constraints, match)
        if suggestion.rewritten_sql is None:
            continue
        expected = _parse_expected(suggestion.rewritten_sql, rewritten)
        if expected is not None and _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                rule_name=suggestion.rule_name,
                assumptions=suggestion.assumptions,
                reason=suggestion.reason,
            )

    if _is_distinct_removal(original, rewritten):
        return _check_distinct_removal(original, rewritten, constraints)

    not_null_filter = RemoveRedundantNotNullFilter().apply(original, constraints)
    if (
        not_null_filter.status == VerificationStatus.PROVEN_EQUIVALENT
        and not_null_filter.rewritten_sql is not None
    ):
        expected = _parse_expected(not_null_filter.rewritten_sql, rewritten)
        if expected is not None and _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                rule_name=not_null_filter.rule_name,
                assumptions=not_null_filter.assumptions,
                reason=not_null_filter.reason,
            )

    join_elimination = RemoveUnusedLeftJoin().apply(original, constraints)
    if (
        join_elimination.status == VerificationStatus.PROVEN_EQUIVALENT
        and join_elimination.rewritten_sql is not None
    ):
        expected = _parse_expected(join_elimination.rewritten_sql, rewritten)
        if expected is not None and _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                rule_name=join_elimination.rule_name,
                assumptions=join_elimination.assumptions,
                reason=join_elimination.reason,
            )

    join_distinct_to_exists = RewriteJoinDistinctToExists().apply(original, constraints)
    if (
        join_distinct_to_exists.status == VerificationStatus.PROVEN_EQUIVALENT
        and join_distinct_to_exists.rewritten_sql is not None
    ):
        expected = _parse_expected(join_distinct_to_exists.rewritten_sql, rewritten)
        if expected is not None and _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                rule_name=join_distinct_to_exists.rule_name,
                assumptions=join_distinct_to_exists.assumptions,
                reason=join_distinct_to_exists.reason,
            )

    pushdown = PredicatePushdown().apply(original, constraints)
    if (
        pushdown.status == VerificationStatus.PROVEN_EQUIVALENT
        and pushdown.rewritten_sql is not None
    ):
        expected = _parse_expected(pushdown.rewritten_sql, rewritten)

        if expected is not None and _same_normalized_query(expected, rewritten):
            return VerificationResult(
                status=VerificationStatus.PROVEN_EQUIVALENT,
                original_sql=original.raw_sql,
                rewritten_sql=rewritten.raw_sql,
                rule_name=pushdown.rule_name,
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
    # Compare every semantic IR field via full structural equality, blanking only
    # the non-semantic ``raw_sql`` provenance string (which always differs between
    # a rule's rendered output and the candidate it is checked against). Enumerating
    # fields by hand here is a soundness hazard: any field omitted from the
    # comparison -- as ``qualify`` once was -- lets a row-changing difference slip
    # through as PROVEN_EQUIVALENT. Comparing whole models means a newly added
    # SelectQuery field is included automatically.
    return left.model_copy(update={"raw_sql": ""}) == right.model_copy(
        update={"raw_sql": ""}
    )


def _parse_expected(sql: str, reference: SelectQuery) -> SelectQuery | None:
    # ``reference`` supplies only the dialect for re-parsing. On failure we must
    # return ``None`` -- never ``reference`` (the candidate). Returning the
    # candidate would make ``_same_normalized_query`` compare it against itself
    # and report a spurious PROVEN_EQUIVALENT: any rule whose rendered SQL fails
    # to parse (e.g. a quoted identifier like "user-id" that to_sql could not
    # round trip) would then "prove" an arbitrary candidate equivalent. A parse
    # failure means the rewrite is unverifiable here, which must not certify
    # equivalence. Callers must guard on ``expected is not None``.
    try:
        from qseal.parser.sqlglot_parser import parse_select

        return parse_select(sql, dialect=reference.dialect)
    except Exception:
        return None


def _is_distinct_removal(original: SelectQuery, rewritten: SelectQuery) -> bool:
    # A clean DISTINCT removal means the rewrite is identical to the original with
    # only the DISTINCT flag dropped. Comparing the original-without-DISTINCT to the
    # candidate over the full IR (including qualify) ensures a rewrite that also
    # drops a QUALIFY or any other row-affecting clause is not mistaken for one.
    if not (original.distinct and not rewritten.distinct):
        return False
    return _same_normalized_query(
        original.model_copy(update={"distinct": False}), rewritten
    )


def _check_distinct_removal(
    original: SelectQuery,
    rewritten: SelectQuery,
    constraints: ConstraintCatalog,
) -> VerificationResult:
    projected_columns = tuple(column.name for column in original.projections)
    table_name = original.table_name()
    if original.group_by or original.having:
        return VerificationResult(
            status=VerificationStatus.UNKNOWN,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            rule_name="remove_redundant_distinct",
            reason="DISTINCT removal with GROUP BY or HAVING is not supported yet.",
        )

    if table_name is None:
        return VerificationResult(
            status=VerificationStatus.UNSUPPORTED,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            rule_name="remove_redundant_distinct",
            reason="DISTINCT removal checks are only supported for direct table queries.",
        )

    if not original.group_by and any(
        getattr(column, "is_aggregate", False) for column in original.projections
    ):
        # Whole-table aggregates (e.g. ``SELECT DISTINCT MAX(x) FROM t``) always
        # collapse to one row, so DISTINCT is a no-op. The unique-key reasoning
        # below cannot account for that and would otherwise return
        # NOT_EQUIVALENT, which is a false refutation. Soundness guard.
        return VerificationResult(
            status=VerificationStatus.UNKNOWN,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            rule_name="remove_redundant_distinct",
            reason=(
                "DISTINCT removal over a whole-table aggregate cannot be refuted; "
                "the aggregate always yields one row."
            ),
        )

    table = constraints.table(table_name)

    unique_key = (
        None if table is None else table.non_null_unique_key_contained_in(projected_columns)
    )
    if unique_key is not None:
        return VerificationResult(
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            rule_name="remove_redundant_distinct",
            assumptions=(
                f"{table_name} has a trusted non-null unique key contained in "
                f"({', '.join(unique_key)}).",
            ),
            reason="DISTINCT cannot remove rows when the projection contains a unique key.",
        )

    if table is not None and table.has_unique_key(projected_columns):
        # Unique keys exempt NULL rows (dbt-test semantics), so duplicate NULL
        # rows remain possible and DISTINCT removal cannot be proven or refuted.
        return VerificationResult(
            status=VerificationStatus.UNKNOWN,
            original_sql=original.raw_sql,
            rewritten_sql=rewritten.raw_sql,
            rule_name="remove_redundant_distinct",
            reason=(
                "The unique key is not trusted non-null, so duplicate NULL rows "
                "may make DISTINCT removal unsafe."
            ),
        )

    return VerificationResult(
        status=VerificationStatus.NOT_EQUIVALENT,
        original_sql=original.raw_sql,
        rewritten_sql=rewritten.raw_sql,
        rule_name="remove_redundant_distinct",
        reason="Removing DISTINCT is unsafe without a trusted uniqueness constraint.",
        counterexample=(
            f"If {table_name} contains two rows with the same "
            f"({', '.join(projected_columns)}) values, the original returns one row "
            "and the rewrite returns both rows."
        ),
    )
