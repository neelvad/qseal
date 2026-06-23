from qseal.constraints.model import ConstraintCatalog
from qseal.ir.model import ColumnRef, InPredicate, Join, Predicate, SelectQuery
from qseal.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus


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

        if _uses_joined_relation(query, join):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="The joined relation is referenced outside the join condition.",
            )

        left_relation = query.table_alias or query.table
        right_key = _right_join_keys(join, left_relation)
        if right_key is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="Could not identify the joined table key columns in the join condition.",
            )

        table = None if join.table_is_cte else constraints.table(join.table)
        if table is None or not table.has_unique_key(right_key):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=f"{_qualified_columns(join.table, right_key)} is not known to be unique.",
            )

        rewritten = query.model_copy(update={"joins": ()})
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=(f"{_qualified_columns(join.table, right_key)} is a trusted unique key.",),
            reason="The unused LEFT JOIN cannot filter rows and cannot duplicate rows.",
        )


class RemoveForeignKeyInnerJoin:
    rule_name = "remove_foreign_key_inner_join"

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
                description=f"Remove FK-backed INNER JOIN to {join.relation_name()}.",
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
                reason=(
                    "FK-backed INNER JOIN elimination with GROUP BY or HAVING "
                    "is not supported yet."
                ),
            )

        join = query.joins[0]
        if join.join_type != "INNER":
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason="Only INNER JOIN elimination is supported.",
            )

        if query.references_cte_relation() or query.table is None or query.table_is_cte:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=(
                    "The query references a CTE or subquery relation, so a standalone "
                    "rewritten query cannot be generated."
                ),
            )

        parent_relation = join.relation_name()
        if _may_use_relation(query, parent_relation):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="The joined parent relation is referenced outside the join condition.",
            )

        join_key = _foreign_key_join_key(query, join)
        if join_key is None:
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason="Could not identify a child-to-parent key in the join condition.",
            )
        child_table, child_key, parent_table, parent_key = join_key

        child_constraints = constraints.table(child_table)
        parent_constraints = None if join.table_is_cte else constraints.table(parent_table)
        if (
            child_constraints is None
            or not child_constraints.has_foreign_key(
                child_key,
                ref_table=parent_table,
                ref_columns=parent_key,
            )
        ):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.NOT_APPLICABLE,
                original_sql=query.raw_sql,
                reason=(
                    f"{_qualified_columns(child_table, child_key)} is not known to reference "
                    f"{_qualified_columns(parent_table, parent_key)}."
                ),
            )

        if not all(child_constraints.is_non_null(column) for column in child_key):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=f"{_qualified_columns(child_table, child_key)} is not trusted non-null.",
            )

        if parent_constraints is None or not parent_constraints.has_unique_key(parent_key):
            return RewriteSuggestion(
                rule_name=self.rule_name,
                status=VerificationStatus.UNKNOWN,
                original_sql=query.raw_sql,
                reason=f"{_qualified_columns(parent_table, parent_key)} is not known to be unique.",
            )

        rewritten = query.model_copy(update={"joins": ()})
        return RewriteSuggestion(
            rule_name=self.rule_name,
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql=query.raw_sql,
            rewritten_sql=rewritten.to_sql(),
            assumptions=(
                f"{_qualified_columns(child_table, child_key)} has a trusted relationship to "
                f"{_qualified_columns(parent_table, parent_key)}.",
                f"{child_table}.({', '.join(child_key)}) is trusted non-null.",
                f"{_qualified_columns(parent_table, parent_key)} is a trusted unique key.",
            ),
            reason=(
                "The trusted non-null foreign key guarantees each child row "
                "matches exactly one parent row, and the parent columns are unused."
            ),
        )


def _uses_joined_relation(query: SelectQuery, join: Join) -> bool:
    joined_name = join.relation_name()
    projected = any(
        (column.is_star and column.table is None)
        or column.table == joined_name
        or column.may_reference_relation(joined_name)
        for column in query.projections
    )
    filtered = any(
        _predicate_uses_joined_relation(predicate, joined_name)
        for predicate in query.predicates
    )
    qualified = any(
        predicate.may_reference_relation(joined_name) for predicate in query.qualify
    )
    return projected or filtered or qualified


def _may_use_relation(query: SelectQuery, relation: str) -> bool:
    projected = any(
        _column_may_reference_relation(column, relation)
        for column in query.projections
    )
    grouped = any(
        key.column is None or _column_may_reference_relation(key.column, relation)
        for key in query.group_by
    )
    filtered = any(
        _predicate_may_reference_relation(predicate, relation)
        for predicate in query.predicates
    )
    qualified = any(
        predicate.references_unqualified_columns or predicate.may_reference_relation(relation)
        for predicate in query.qualify
    )
    return projected or grouped or filtered or qualified


def _column_may_reference_relation(column: ColumnRef, relation: str) -> bool:
    if column.is_star and column.table is None:
        return True
    if column.table is None:
        return True
    return column.table == relation or column.may_reference_relation(relation)


def _predicate_may_reference_relation(predicate, relation: str) -> bool:
    if isinstance(predicate, Predicate | InPredicate):
        return predicate.left.table is None or predicate.left.table == relation
    return True


def _foreign_key_join_key(
    query: SelectQuery,
    join: Join,
) -> tuple[str, tuple[str, ...], str, tuple[str, ...]] | None:
    if query.table is None:
        return None
    child_relation = query.table_alias or query.table
    parent_relation = join.relation_name()
    child_keys = []
    parent_keys = []
    for condition in join.conditions():
        left = condition.left
        right = condition.right
        if left.table == child_relation and right.table == parent_relation:
            child_keys.append(left.name)
            parent_keys.append(right.name)
            continue
        if right.table == child_relation and left.table == parent_relation:
            child_keys.append(right.name)
            parent_keys.append(left.name)
            continue
        return None
    if not child_keys or len(set(child_keys)) != len(child_keys):
        return None
    if len(set(parent_keys)) != len(parent_keys):
        return None
    return query.table, tuple(child_keys), join.table, tuple(parent_keys)


def _predicate_uses_joined_relation(predicate, joined_name: str) -> bool:
    if not isinstance(predicate, Predicate | InPredicate):
        return True
    return predicate.left.table == joined_name


def _qualified_columns(table: str, columns: tuple[str, ...]) -> str:
    if len(columns) == 1:
        return f"{table}.{columns[0]}"
    return f"{table}.({', '.join(columns)})"


def _right_join_keys(join: Join, left_relation: str | None) -> tuple[str, ...] | None:
    if left_relation is None:
        return None
    joined_name = join.relation_name()
    keys = []
    for condition in join.conditions():
        if condition.right.table == joined_name and condition.left.table == left_relation:
            keys.append(condition.right.name)
            continue
        if condition.left.table == joined_name and condition.right.table == left_relation:
            keys.append(condition.left.name)
            continue
        return None
    if not keys or len(set(keys)) != len(keys):
        return None
    return tuple(keys)
