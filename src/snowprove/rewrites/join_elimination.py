from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import InPredicate, Join, Predicate, SelectQuery
from snowprove.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


class RemoveUnusedLeftJoin:
    rule_name = "remove_unused_left_join"

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
                description=f"Remove unused LEFT JOIN to {join.relation_name()}.",
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
        if len(query.joins) != 1:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Query does not have exactly one JOIN.",
            )

        if query.group_by or query.having:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="LEFT JOIN elimination with GROUP BY or HAVING is not supported yet.",
            )

        join = query.joins[0]
        if join.join_type != "LEFT":
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Only LEFT JOIN elimination is supported.",
            )

        if _uses_joined_relation(query, join):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="The joined relation is referenced outside the join condition.",
            )

        right_key = _right_join_key(join)
        if right_key is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="Could not identify the joined table key in the join condition.",
            )

        table = constraints.table(join.table)
        if table is None or not table.has_unique_key((right_key,)):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=f"{join.table}.{right_key} is not known to be unique.",
            )

        rewritten = query.model_copy(update={"joins": ()})
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=(f"{join.table}.{right_key} is a trusted unique key.",),
            reason="The unused LEFT JOIN cannot filter rows and cannot duplicate rows.",
        )


def _uses_joined_relation(query: SelectQuery, join: Join) -> bool:
    joined_name = join.relation_name()
    projected = any(
        (column.is_star and column.table is None) or column.table == joined_name
        for column in query.projections
    )
    filtered = any(
        _predicate_uses_joined_relation(predicate, joined_name)
        for predicate in query.predicates
    )
    return projected or filtered


def _predicate_uses_joined_relation(predicate, joined_name: str) -> bool:
    if not isinstance(predicate, Predicate | InPredicate):
        return True
    return predicate.left.table == joined_name


def _right_join_key(join: Join) -> str | None:
    joined_name = join.relation_name()
    if join.condition.right.table == joined_name:
        return join.condition.right.name
    if join.condition.left.table == joined_name:
        return join.condition.left.name
    return None
