from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import Predicate, SelectQuery
from snowprove.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class RemoveRedundantNotNullFilter:
    rule_name = "remove_redundant_not_null_filter"

    def matches(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
    ) -> tuple[RewriteMatch, ...]:
        context = _redundant_predicate_context(query, constraints)
        if context is None:
            return ()
        _, redundant_indexes = context
        return tuple(
            RewriteMatch(
                rule_name=self.rule_name,
                match_id=f"predicate:{index}",
                target_kind="predicate",
                target_index=index,
                description=(
                    f"Remove redundant IS NOT NULL predicate on "
                    f"{query.predicates[index].left.name}."
                ),
                metadata={"column": query.predicates[index].left.name},
            )
            for index in redundant_indexes
        )

    def apply_match(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        match: RewriteMatch,
    ) -> RewriteSuggestion:
        context = _redundant_predicate_context(query, constraints)
        if (
            match.rule_name != self.rule_name
            or match.target_kind != "predicate"
            or match.target_index is None
            or context is None
        ):
            raise ValueError(f"Invalid match for {self.rule_name}: {match.match_id}.")

        table_name, redundant_indexes = context
        index = match.target_index
        if match.match_id != f"predicate:{index}" or index not in redundant_indexes:
            raise ValueError(f"Match is no longer applicable: {match.match_id}.")

        predicate = query.predicates[index]
        rewritten = query.model_copy(
            update={
                "predicates": tuple(
                    item for item_index, item in enumerate(query.predicates)
                    if item_index != index
                )
            }
        )
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=(f"{table_name}.({predicate.left.name}) is trusted non-null.",),
            reason="A trusted non-null column always satisfies IS NOT NULL.",
        )

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        not_null_predicates = [
            predicate
            for predicate in query.predicates
            if isinstance(predicate, Predicate) and predicate.operator == "IS NOT NULL"
        ]
        if not not_null_predicates:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query has no IS NOT NULL predicates.",
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

        if not query.is_direct_table() or query.joins:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="NOT NULL filter removal is only supported for direct table queries.",
            )

        table_name = query.table_name()
        table = constraints.table(table_name) if table_name is not None else None
        if table is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=f"No trusted constraints found for table {table_name}.",
            )

        redundant_indexes = tuple(
            index
            for index, predicate in enumerate(query.predicates)
            if _is_trusted_not_null_predicate(predicate, query.table_alias, table)
        )
        if not redundant_indexes:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query has no redundant IS NOT NULL predicates.",
            )

        rewritten = query.model_copy(
            update={
                "predicates": tuple(
                    predicate
                    for index, predicate in enumerate(query.predicates)
                    if index not in redundant_indexes
                )
            }
        )
        columns = ", ".join(query.predicates[index].left.name for index in redundant_indexes)
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=(f"{table_name}.({columns}) is trusted non-null.",),
            reason="A trusted non-null column always satisfies IS NOT NULL.",
        )


def _redundant_predicate_context(
    query: SelectQuery,
    constraints: ConstraintCatalog,
) -> tuple[str, tuple[int, ...]] | None:
    if not query.is_direct_table() or query.joins:
        return None
    table_name = query.table_name()
    table = constraints.table(table_name) if table_name is not None else None
    if table_name is None or table is None:
        return None
    redundant_indexes = tuple(
        index
        for index, predicate in enumerate(query.predicates)
        if _is_trusted_not_null_predicate(predicate, query.table_alias, table)
    )
    if not redundant_indexes:
        return None
    return table_name, redundant_indexes


def _is_trusted_not_null_predicate(
    predicate: Predicate,
    table_alias: str | None,
    table,
) -> bool:
    if predicate.operator != "IS NOT NULL":
        return False
    if predicate.left.table is not None and predicate.left.table != table_alias:
        return False

    column = table.columns.get(predicate.left.name)
    return column is not None and column.nullable is False
