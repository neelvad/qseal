from qseal.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.group_by_unique import CollapseUniqueGroupBy


def test_collapses_group_by_over_non_null_unique_key() -> None:
    query = parse_select(
        """
        SELECT user_id, MAX(email) AS email
        FROM users
        GROUP BY user_id
        """
    )

    suggestion = CollapseUniqueGroupBy().apply(query, _user_constraints())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id, email AS email\nFROM users;"
    assert suggestion.assumptions == (
        "users has a trusted non-null unique key contained in (user_id).",
    )


def test_collapses_group_by_over_composite_unique_key() -> None:
    query = parse_select(
        """
        SELECT tenant_id, user_id, MIN(segment) AS segment
        FROM users
        GROUP BY tenant_id, user_id
        """
    )
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={
                    "tenant_id": ColumnConstraint(nullable=False),
                    "user_id": ColumnConstraint(nullable=False),
                },
                unique=[("tenant_id", "user_id")],
            )
        }
    )

    suggestion = CollapseUniqueGroupBy().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT tenant_id, user_id, segment AS segment\nFROM users;"
    )


def test_collapses_group_by_while_preserving_where() -> None:
    query = parse_select(
        """
        SELECT user_id, ANY_VALUE(email) AS email
        FROM users
        WHERE status = 'active'
        GROUP BY user_id
        """
    )

    suggestion = CollapseUniqueGroupBy().apply(query, _user_constraints())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT user_id, email AS email\n"
        "FROM users\n"
        "WHERE status = 'active';"
    )


def test_rejects_group_by_over_nullable_unique_key() -> None:
    query = parse_select("SELECT user_id, MAX(email) AS email FROM users GROUP BY user_id")
    constraints = ConstraintCatalog(
        tables={"users": TableConstraints(unique=[("user_id",)])}
    )

    suggestion = CollapseUniqueGroupBy().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN
    assert suggestion.rewritten_sql is None


def test_rejects_count_aggregate_group_by_collapse() -> None:
    query = parse_select("SELECT user_id, COUNT(*) AS n FROM users GROUP BY user_id")

    suggestion = CollapseUniqueGroupBy().apply(query, _user_constraints())

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
    assert suggestion.rewritten_sql is None


def test_group_by_unique_exposes_structured_match() -> None:
    query = parse_select("SELECT user_id, MAX(email) AS email FROM users GROUP BY user_id")
    rule = CollapseUniqueGroupBy()

    matches = rule.matches(query, _user_constraints())

    assert len(matches) == 1
    assert matches[0].match_id == "query:group_by"
    suggestion = rule.apply_match(query, _user_constraints(), matches[0])
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT


def _user_constraints() -> ConstraintCatalog:
    return ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"user_id": ColumnConstraint(nullable=False)},
                unique=[("user_id",)],
            )
        }
    )
