from qseal.constraints.model import ConstraintCatalog, TableConstraints
from qseal.ir.model import InPredicate, LiteralValue, Predicate, SelectQuery
from qseal.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class RemoveRedundantAcceptedValuesFilter:
    rule_name = "remove_redundant_accepted_values_filter"

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
                    f"Remove redundant accepted-values IN predicate on "
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
        return _rewrite(query, table_name, (index,))

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        in_predicates = [
            predicate
            for predicate in query.predicates
            if isinstance(predicate, InPredicate) and not predicate.negated
        ]
        if not in_predicates:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query has no positive IN predicates.",
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
                reason="Accepted-values filter removal is only supported for direct table queries.",
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

        redundant_indexes = _redundant_indexes(query, table_name, table)
        if not redundant_indexes:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query has no redundant accepted-values IN predicates.",
            )

        return _rewrite(query, table_name, redundant_indexes)


def _rewrite(
    query: SelectQuery,
    table_name: str,
    redundant_indexes: tuple[int, ...],
) -> RewriteSuggestion:
    rewritten = query.model_copy(
        update={
            "predicates": tuple(
                predicate
                for index, predicate in enumerate(query.predicates)
                if index not in redundant_indexes
            )
        }
    )
    assumptions = []
    for index in redundant_indexes:
        predicate = query.predicates[index]
        if not isinstance(predicate, InPredicate):
            continue
        values = ", ".join(value.to_sql() for value in predicate.values)
        assumptions.extend(
            [
                f"{table_name}.{predicate.left.name} has accepted values ({values}).",
                f"{table_name}.({predicate.left.name}) is trusted non-null.",
            ]
        )
    return RewriteSuggestion(
        rule_name=RemoveRedundantAcceptedValuesFilter.rule_name,
        status=VerificationStatus.PROVEN_EQUIVALENT,
        original_sql=query.raw_sql,
        rewritten_sql=rewritten.to_sql(),
        assumptions=tuple(dict.fromkeys(assumptions)),
        reason=(
            "A trusted non-null accepted-values domain always satisfies "
            "the removed IN predicate."
        ),
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
    redundant_indexes = _redundant_indexes(query, table_name, table)
    if not redundant_indexes:
        return None
    return table_name, redundant_indexes


def _redundant_indexes(
    query: SelectQuery,
    table_name: str,
    table: TableConstraints,
) -> tuple[int, ...]:
    return tuple(
        index
        for index, predicate in enumerate(query.predicates)
        if _is_redundant_accepted_values_predicate(
            predicate,
            query.table_alias,
            table_name,
            table,
        )
    )


def _is_redundant_accepted_values_predicate(
    predicate: Predicate | InPredicate,
    table_alias: str | None,
    table_name: str,
    table: TableConstraints,
) -> bool:
    if not isinstance(predicate, InPredicate):
        return False
    if predicate.negated:
        return False
    if predicate.left.table is not None:
        if table_alias is not None:
            valid_prefixes = {table_alias}
        else:
            valid_prefixes = {table_name, table_name.split(".")[-1]}
        if predicate.left.table not in valid_prefixes:
            return False

    column = table.columns.get(predicate.left.name)
    if column is None or column.nullable is not False or not column.accepted_values:
        return False

    accepted = {
        (accepted_value.value, accepted_value.is_string)
        for accepted_value in column.accepted_values
    }
    predicate_values = {_literal_key(value) for value in predicate.values}
    return accepted == predicate_values


def _literal_key(value: LiteralValue) -> tuple[str, bool]:
    return value.value, value.is_string
