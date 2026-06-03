from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.check import check_equivalence


def test_check_proves_distinct_removal_with_unique_key() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users")
    rewritten = parse_select("SELECT user_id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.assumptions


def test_check_proves_distinct_removal_with_matching_where_predicates() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users WHERE status = 'active'")
    rewritten = parse_select("SELECT user_id FROM users WHERE status = 'active'")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT


def test_check_does_not_apply_distinct_rule_when_predicates_differ() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users WHERE status = 'active'")
    rewritten = parse_select("SELECT user_id FROM users WHERE status = 'inactive'")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.UNKNOWN


def test_check_does_not_equate_different_qualified_relations() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM analytics.public.users")
    rewritten = parse_select("SELECT user_id FROM analytics.staging.users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.UNKNOWN


def test_check_proves_predicate_pushdown() -> None:
    original = parse_select(
        """
        SELECT user_id, revenue
        FROM (
          SELECT user_id, revenue
          FROM orders
        ) x
        WHERE revenue > 0
        """
    )
    rewritten = parse_select("SELECT user_id, revenue FROM orders WHERE revenue > 0")

    result = check_equivalence(original, rewritten, ConstraintCatalog())

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT


def test_check_proves_unused_left_join_elimination() -> None:
    original = parse_select(
        """
        SELECT f.user_id, f.revenue
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    rewritten = parse_select("SELECT f.user_id, f.revenue FROM fact_orders f")
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT


def test_check_proves_redundant_not_null_filter_removal() -> None:
    original = parse_select("SELECT user_id FROM users WHERE email IS NOT NULL")
    rewritten = parse_select("SELECT user_id FROM users")
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"email": {"nullable": False}},
            )
        }
    )

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT


def test_check_disproves_distinct_removal_without_unique_key() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users")
    rewritten = parse_select("SELECT user_id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints()})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.NOT_EQUIVALENT
    assert result.counterexample is not None
