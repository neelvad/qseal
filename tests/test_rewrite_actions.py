import pytest

from snowprove.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import RewriteMatch, VerificationStatus
from snowprove.rewrites.distinct import RemoveRedundantDistinct
from snowprove.rewrites.join_distinct_exists import RewriteJoinDistinctToExists
from snowprove.rewrites.join_elimination import RemoveUnusedLeftJoin
from snowprove.rewrites.not_null_filter import RemoveRedundantNotNullFilter
from snowprove.rewrites.predicate_pushdown import PredicatePushdown
from snowprove.rewrites.registry import apply_rewrite_match, available_rewrite_matches


@pytest.mark.parametrize(
    ("rule", "sql", "constraints", "match_id"),
    [
        (
            RemoveRedundantDistinct(),
            "SELECT DISTINCT user_id FROM users",
            ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])}),
            "query:distinct",
        ),
        (
            RemoveUnusedLeftJoin(),
            (
                "SELECT f.user_id FROM fact_orders f "
                "LEFT JOIN dim_users u ON f.user_id = u.user_id"
            ),
            ConstraintCatalog(
                tables={"dim_users": TableConstraints(unique=[("user_id",)])}
            ),
            "join:0",
        ),
        (
            RewriteJoinDistinctToExists(),
            (
                "SELECT DISTINCT u.user_id FROM users u "
                "JOIN orders o ON u.user_id = o.user_id"
            ),
            ConstraintCatalog(),
            "join:0",
        ),
        (
            PredicatePushdown(),
            (
                "SELECT user_id FROM (SELECT user_id FROM users) projected "
                "WHERE user_id > 10"
            ),
            ConstraintCatalog(),
            "subquery:0",
        ),
    ],
)
def test_single_action_rules_apply_their_structured_match(
    rule,
    sql: str,
    constraints: ConstraintCatalog,
    match_id: str,
) -> None:
    query = parse_select(sql, dialect="duckdb")

    matches = rule.matches(query, constraints)

    assert len(matches) == 1
    assert matches[0].rule_name == rule.rule_name
    assert matches[0].match_id == match_id
    suggestion = rule.apply_match(query, constraints, matches[0])
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == rule.apply(query, constraints).rewritten_sql


def test_not_null_rule_exposes_one_action_per_redundant_predicate() -> None:
    query = parse_select(
        """
        SELECT user_id
        FROM users
        WHERE email IS NOT NULL
          AND status = 'active'
          AND display_name IS NOT NULL
        """,
        dialect="duckdb",
    )
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={
                    "email": ColumnConstraint(nullable=False),
                    "display_name": ColumnConstraint(nullable=False),
                }
            )
        }
    )
    rule = RemoveRedundantNotNullFilter()

    matches = rule.matches(query, constraints)

    assert [(match.match_id, match.target_index) for match in matches] == [
        ("predicate:0", 0),
        ("predicate:2", 2),
    ]
    first = rule.apply_match(query, constraints, matches[0])
    assert first.rewritten_sql == (
        "SELECT user_id\n"
        "FROM users\n"
        "WHERE status = 'active' AND display_name IS NOT NULL;"
    )
    legacy = rule.apply(query, constraints)
    assert legacy.rewritten_sql == "SELECT user_id\nFROM users\nWHERE status = 'active';"


def test_registry_enumerates_and_applies_matches() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM users")
    constraints = ConstraintCatalog(
        tables={"users": TableConstraints(unique=[("user_id",)])}
    )

    matches = available_rewrite_matches(query, constraints)
    suggestion = apply_rewrite_match(query, constraints, matches[0])

    assert [(match.rule_name, match.match_id) for match in matches] == [
        ("remove_redundant_distinct", "query:distinct")
    ]
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM users;"


def test_apply_match_rejects_a_match_from_another_rule() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM users")
    constraints = ConstraintCatalog(
        tables={"users": TableConstraints(unique=[("user_id",)])}
    )
    invalid = RewriteMatch(
        rule_name="predicate_pushdown",
        match_id="subquery:0",
        target_kind="subquery",
        target_index=0,
        description="invalid",
    )

    with pytest.raises(ValueError, match="Invalid match"):
        RemoveRedundantDistinct().apply_match(query, constraints, invalid)
