from collections.abc import Sequence
from typing import Protocol

from snowprove.constraints.model import ConstraintCatalog
from snowprove.ir.model import SelectQuery
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.rewrites.distinct import RemoveRedundantDistinct
from snowprove.rewrites.join_distinct_exists import RewriteJoinDistinctToExists
from snowprove.rewrites.join_elimination import RemoveUnusedLeftJoin
from snowprove.rewrites.not_null_filter import RemoveRedundantNotNullFilter
from snowprove.rewrites.predicate_pushdown import PredicatePushdown


class RewriteRule(Protocol):
    rule_name: str

    def apply(self, query: SelectQuery, constraints: ConstraintCatalog) -> RewriteSuggestion:
        pass


DEFAULT_RULES: tuple[RewriteRule, ...] = (
    RemoveUnusedLeftJoin(),
    RewriteJoinDistinctToExists(),
    RemoveRedundantNotNullFilter(),
    RemoveRedundantDistinct(),
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


def first_applicable_suggestion(suggestions: Sequence[RewriteSuggestion]) -> RewriteSuggestion:
    for suggestion in suggestions:
        if suggestion.status != VerificationStatus.NOT_APPLICABLE:
            return suggestion
    return suggestions[0]
