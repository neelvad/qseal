from qseal.constraints.model import ConstraintCatalog
from qseal.ir.model import ExistsPredicate, InPredicate, Join, Predicate, SelectQuery
from qseal.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class RewriteJoinDistinctToExists:
    rule_name = "rewrite_join_distinct_to_exists"

    def matches(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
    ) -> tuple[RewriteMatch, ...]:
        suggestion = self._suggest(query, constraints)
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            return ()
        join = query.joins[0]
        return (
            RewriteMatch(
                rule_name=self.rule_name,
                match_id="join:0",
                target_kind="join",
                target_index=0,
                description=f"Replace INNER JOIN to {join.relation_name()} with EXISTS.",
                metadata={"relation": join.relation_name()},
            ),
        )

    def apply_match(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        match: RewriteMatch,
    ) -> RewriteSuggestion:
        if match.rule_name != self.rule_name or match.match_id != "join:0":
            raise ValueError(f"Invalid match for {self.rule_name}: {match.match_id}.")
        suggestion = self._suggest(query, constraints)
        if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
            raise ValueError(f"Match is no longer applicable: {match.match_id}.")
        return suggestion

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        return self._suggest(query, constraints)

    def _suggest(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        del constraints

        if not query.distinct or len(query.joins) != 1:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query is not a SELECT DISTINCT with exactly one JOIN.",
            )

        if query.group_by or query.having:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="JOIN to EXISTS rewrite with GROUP BY or HAVING is not supported yet.",
            )

        if query.qualify:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=(
                    "Rewriting the JOIN to EXISTS would change the rows QUALIFY "
                    "window functions evaluate over."
                ),
            )

        join = query.joins[0]
        if join.join_type != "INNER":
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="JOIN to EXISTS rewrite only applies to INNER JOIN.",
            )

        if join.extra_conditions:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="JOIN to EXISTS rewrite with composite join keys is not supported yet.",
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

        if not query.is_direct_table():
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="JOIN to EXISTS rewrite is only supported for direct table queries.",
            )

        left_relation = query.table_alias or query.table
        if left_relation is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNSUPPORTED,
                original_sql=query.raw_sql,
                reason="Could not identify the left relation.",
            )

        if not _predicates_only_reference_left_relation(query.predicates, left_relation):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=(
                    "Existing WHERE predicates must be simple filters on the left relation."
                ),
            )

        if any(
            not column.is_direct_column() or column.table != left_relation
            for column in query.projections
        ):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="Projected columns must be qualified from the left relation.",
            )

        if not _join_condition_connects_left_and_right(join, left_relation):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="JOIN condition must connect the left relation and joined relation.",
            )

        rewritten = query.model_copy(
            update={
                "distinct": False,
                "joins": (),
                "predicates": (
                    *query.predicates,
                    ExistsPredicate(
                        table=join.table,
                        table_sql=join.table_sql,
                        alias=join.alias,
                        condition=join.condition,
                    ),
                ),
            }
        )
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            reason=(
                "The INNER JOIN is only used to require at least one matching row; "
                "EXISTS preserves that condition without join row multiplication."
            ),
        )


def _join_condition_connects_left_and_right(join: Join, left_relation: str) -> bool:
    right_relation = join.relation_name()
    left = join.condition.left.table
    right = join.condition.right.table
    return {left, right} == {left_relation, right_relation}


def _predicates_only_reference_left_relation(
    predicates: tuple[Predicate | InPredicate | ExistsPredicate, ...],
    left_relation: str,
) -> bool:
    return all(
        isinstance(predicate, Predicate | InPredicate) and predicate.left.table == left_relation
        for predicate in predicates
    )
