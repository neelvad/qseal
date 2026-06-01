from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import SelectQuery
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


class RemoveRedundantDistinct:
    rule_name = "remove_redundant_distinct"

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        if not query.distinct:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query does not use DISTINCT.",
            )

        if query.joins:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="DISTINCT removal with joins is not supported yet.",
            )

        table_name = query.table_name()
        if table_name is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="DISTINCT removal is only supported for direct table queries.",
            )

        table = constraints.table(table_name)
        if table is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=f"No trusted constraints found for table {table_name}.",
            )

        projected_columns = tuple(column.name for column in query.projections)
        if not table.has_unique_key(projected_columns):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="Projected columns are not known to contain a unique key.",
            )

        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=query.without_distinct_sql(),
            assumptions=(
                f"{table_name} has a trusted unique key contained in "
                f"({', '.join(projected_columns)}).",
            ),
        )
