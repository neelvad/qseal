from collections.abc import Sequence
from typing import Protocol

from qseal.constraints.model import ConstraintCatalog
from qseal.ir.model import SelectQuery
from qseal.rewrites.accepted_values_case import SimplifyAcceptedValuesCase
from qseal.rewrites.accepted_values_filter import RemoveRedundantAcceptedValuesFilter
from qseal.rewrites.base import RewriteMatch, RewriteSuggestion, VerificationStatus
from qseal.rewrites.count_distinct import RemoveRedundantCountDistinct
from qseal.rewrites.distinct import RemoveRedundantDistinct
from qseal.rewrites.group_by_unique import CollapseUniqueGroupBy
from qseal.rewrites.join_distinct_exists import RewriteJoinDistinctToExists
from qseal.rewrites.join_elimination import RemoveForeignKeyInnerJoin, RemoveUnusedLeftJoin
from qseal.rewrites.not_null_filter import RemoveRedundantNotNullFilter
from qseal.rewrites.predicate_pushdown import PredicatePushdown


class RewriteRule(Protocol):
    rule_name: str

    def matches(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
    ) -> tuple[RewriteMatch, ...]:
        pass

    def apply_match(
        self,
        query: SelectQuery,
        constraints: ConstraintCatalog,
        match: RewriteMatch,
    ) -> RewriteSuggestion:
        pass

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        pass


DEFAULT_RULES: tuple[RewriteRule, ...] = (
    RemoveUnusedLeftJoin(),
    RemoveForeignKeyInnerJoin(),
    RewriteJoinDistinctToExists(),
    RemoveRedundantNotNullFilter(),
    RemoveRedundantAcceptedValuesFilter(),
    SimplifyAcceptedValuesCase(),
    RemoveRedundantDistinct(),
    RemoveRedundantCountDistinct(),
    CollapseUniqueGroupBy(),
    PredicatePushdown(),
)


def rule_names(rules: Sequence[RewriteRule] = DEFAULT_RULES) -> tuple[str, ...]:
    return tuple(rule.rule_name for rule in rules)


def rules_by_name(rules: Sequence[RewriteRule] = DEFAULT_RULES) -> dict[str, RewriteRule]:
    return {rule.rule_name: rule for rule in rules}


def select_rules(names: Sequence[str] | None) -> tuple[RewriteRule, ...]:
    if not names:
        return DEFAULT_RULES

    available = rules_by_name()
    return tuple(available[name] for name in names)


def suggest_rewrites(
    query: SelectQuery,
    constraints: ConstraintCatalog,
    rules: Sequence[RewriteRule] = DEFAULT_RULES,
) -> list[RewriteSuggestion]:
    return [rule.apply(query, constraints) for rule in rules]


def available_rewrite_matches(
    query: SelectQuery,
    constraints: ConstraintCatalog,
    rules: Sequence[RewriteRule] = DEFAULT_RULES,
) -> tuple[RewriteMatch, ...]:
    return tuple(
        match
        for rule in rules
        for match in rule.matches(query, constraints)
    )


def apply_rewrite_match(
    query: SelectQuery,
    constraints: ConstraintCatalog,
    match: RewriteMatch,
    rules: Sequence[RewriteRule] = DEFAULT_RULES,
) -> RewriteSuggestion:
    rule = rules_by_name(rules).get(match.rule_name)
    if rule is None:
        raise ValueError(f"Unknown rewrite rule: {match.rule_name}.")
    return rule.apply_match(query, constraints, match)


def first_applicable_suggestion(suggestions: Sequence[RewriteSuggestion]) -> RewriteSuggestion:
    for suggestion in suggestions:
        if suggestion.status != VerificationStatus.NOT_APPLICABLE:
            return suggestion
    return suggestions[0]
