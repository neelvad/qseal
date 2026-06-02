from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import Predicate, SelectQuery
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


class RemoveRedundantNotNullFilter:
    rule_name = "remove_redundant_not_null_filter"

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        not_null_predicates = [
            predicate for predicate in query.predicates if predicate.operator == "IS NOT NULL"
        ]
        if not not_null_predicates:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query has no IS NOT NULL predicates.",
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

        redundant = [
            predicate
            for predicate in query.predicates
            if _is_trusted_not_null_predicate(predicate, query.table_alias, table)
        ]
        if not redundant:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query has no redundant IS NOT NULL predicates.",
            )

        rewritten = query.model_copy(
            update={
                "predicates": tuple(
                    predicate for predicate in query.predicates if predicate not in redundant
                )
            }
        )
        columns = ", ".join(predicate.left.name for predicate in redundant)
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=(f"{table_name}.({columns}) is trusted non-null.",),
            reason="A trusted non-null column always satisfies IS NOT NULL.",
        )


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
