from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.registry import (
    first_applicable_suggestion,
    rule_names,
    select_rules,
    suggest_rewrites,
)


def test_registry_returns_rules_in_default_order() -> None:
    query = parse_select(
        """
        SELECT f.user_id, f.revenue
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestions = suggest_rewrites(query, constraints)

    assert [suggestion.rule_name for suggestion in suggestions] == [
        "remove_unused_left_join",
        "remove_redundant_not_null_filter",
        "remove_redundant_distinct",
        "predicate_pushdown",
    ]


def test_first_applicable_suggestion_skips_not_applicable_results() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    suggestion = first_applicable_suggestion(suggest_rewrites(query, constraints))

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_redundant_distinct"


def test_select_rules_filters_default_rules_by_name() -> None:
    rules = select_rules(("predicate_pushdown",))

    assert [rule.rule_name for rule in rules] == ["predicate_pushdown"]


def test_rule_names_returns_cli_choices() -> None:
    assert rule_names() == (
        "remove_unused_left_join",
        "remove_redundant_not_null_filter",
        "remove_redundant_distinct",
        "predicate_pushdown",
    )
