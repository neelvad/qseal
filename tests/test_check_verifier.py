from qseal.constraints.model import (
    ColumnConstraint,
    ConstraintCatalog,
    ForeignKeyConstraint,
    TableConstraints,
)
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.check import check_equivalence


def test_check_proves_distinct_removal_with_unique_key() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users")
    rewritten = parse_select("SELECT user_id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(
        columns={"user_id": {"nullable": False}},
        unique=[("user_id",)],
    )})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "remove_redundant_distinct"
    assert result.assumptions


def test_check_proves_distinct_removal_with_composite_unique_key() -> None:
    original = parse_select("SELECT DISTINCT tenant_id, order_id, status FROM orders")
    rewritten = parse_select("SELECT tenant_id, order_id, status FROM orders")
    constraints = ConstraintCatalog(
        tables={
            "orders": TableConstraints(
                columns={
                    "tenant_id": ColumnConstraint(nullable=False),
                    "order_id": ColumnConstraint(nullable=False),
                },
                unique=[("tenant_id", "order_id")],
            )
        }
    )

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "remove_redundant_distinct"
    assert result.assumptions == (
        "orders has a trusted non-null unique key contained in (tenant_id, order_id).",
    )


def test_check_proves_count_distinct_removal_with_unique_key() -> None:
    original = parse_select("SELECT COUNT(DISTINCT user_id) AS unique_users FROM users")
    rewritten = parse_select("SELECT COUNT(user_id) AS unique_users FROM users")
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"user_id": ColumnConstraint(nullable=False)},
                unique=[("user_id",)],
            )
        }
    )

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "remove_redundant_count_distinct"


def test_check_proves_distinct_removal_with_matching_where_predicates() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users WHERE status = 'active'")
    rewritten = parse_select("SELECT user_id FROM users WHERE status = 'active'")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(
        columns={"user_id": {"nullable": False}},
        unique=[("user_id",)],
    )})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT


def test_check_does_not_apply_distinct_rule_when_predicates_differ() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users WHERE status = 'active'")
    rewritten = parse_select("SELECT user_id FROM users WHERE status = 'inactive'")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(
        columns={"user_id": {"nullable": False}},
        unique=[("user_id",)],
    )})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.UNKNOWN


def test_check_does_not_equate_different_qualified_relations() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM analytics.public.users")
    rewritten = parse_select("SELECT user_id FROM analytics.staging.users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(
        columns={"user_id": {"nullable": False}},
        unique=[("user_id",)],
    )})

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
    assert result.rule_name == "predicate_pushdown"


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
    assert result.rule_name == "remove_unused_left_join"


def test_check_proves_fk_backed_inner_join_elimination() -> None:
    original = parse_select(
        """
        SELECT f.order_id, f.user_id
        FROM fact_orders f
        INNER JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    rewritten = parse_select("SELECT f.order_id, f.user_id FROM fact_orders f")
    constraints = ConstraintCatalog(
        tables={
            "fact_orders": TableConstraints(
                columns={"user_id": ColumnConstraint(nullable=False)},
                foreign_keys=[
                    ForeignKeyConstraint(
                        columns=("user_id",),
                        ref_table="dim_users",
                        ref_columns=("user_id",),
                    )
                ],
            ),
            "dim_users": TableConstraints(unique=[("user_id",)]),
        }
    )

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "remove_foreign_key_inner_join"


def test_check_proves_join_distinct_to_exists() -> None:
    original = parse_select(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        """
    )
    rewritten = parse_select(
        """
        SELECT u.user_id
        FROM users u
        WHERE EXISTS (
          SELECT 1
          FROM orders o
          WHERE u.user_id = o.user_id
        )
        """
    )

    result = check_equivalence(original, rewritten, ConstraintCatalog())

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "rewrite_join_distinct_to_exists"


def test_check_proves_join_distinct_to_exists_with_left_predicate() -> None:
    original = parse_select(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        WHERE u.status = 'active'
        """
    )
    rewritten = parse_select(
        """
        SELECT u.user_id
        FROM users u
        WHERE u.status = 'active'
          AND EXISTS (
            SELECT 1
            FROM orders o
            WHERE u.user_id = o.user_id
          )
        """
    )

    result = check_equivalence(original, rewritten, ConstraintCatalog())

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "rewrite_join_distinct_to_exists"


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
    assert result.rule_name == "remove_redundant_distinct"
    assert result.counterexample is not None


def test_check_does_not_prove_distinct_removal_with_nullable_unique_key() -> None:
    original = parse_select("SELECT DISTINCT user_id FROM users")
    rewritten = parse_select("SELECT user_id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.UNKNOWN
    assert result.rule_name == "remove_redundant_distinct"
    assert "NULL" in result.reason


def test_check_does_not_prove_distinct_removal_with_group_by() -> None:
    original = parse_select("SELECT DISTINCT status, COUNT(*) AS n FROM users GROUP BY status")
    rewritten = parse_select("SELECT status, COUNT(*) AS n FROM users GROUP BY status")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("status",)])})

    result = check_equivalence(original, rewritten, constraints)

    assert result.status == VerificationStatus.UNKNOWN
    assert result.rule_name == "remove_redundant_distinct"


def test_check_compares_having_predicates_for_identity() -> None:
    original = parse_select(
        "SELECT status, COUNT(*) AS n FROM users GROUP BY status HAVING COUNT(*) > 1"
    )
    rewritten = parse_select(
        "SELECT status, COUNT(*) AS n FROM users GROUP BY status HAVING COUNT(*) > 2"
    )

    result = check_equivalence(original, rewritten, ConstraintCatalog())

    assert result.status == VerificationStatus.UNKNOWN


# --- QUALIFY soundness: a rewrite that drops a QUALIFY changes which rows are
# returned and must never be proven equivalent, even when an unrelated rule
# (DISTINCT removal, not-null filter removal) would otherwise apply. ---

_USERS_NON_NULL_UNIQUE = ConstraintCatalog(
    tables={
        "users": TableConstraints(
            columns={"user_id": {"nullable": False}, "email": {"nullable": False}},
            unique=[("user_id",)],
        )
    }
)


def test_check_does_not_prove_distinct_removal_that_also_drops_qualify() -> None:
    original = parse_select(
        "SELECT DISTINCT user_id FROM users "
        "QUALIFY ROW_NUMBER() OVER (ORDER BY ts) = 1"
    )
    rewritten = parse_select("SELECT user_id FROM users")

    result = check_equivalence(original, rewritten, _USERS_NON_NULL_UNIQUE)

    assert result.status == VerificationStatus.UNKNOWN


def test_check_does_not_prove_not_null_removal_that_also_drops_qualify() -> None:
    original = parse_select(
        "SELECT user_id FROM users WHERE email IS NOT NULL "
        "QUALIFY ROW_NUMBER() OVER (ORDER BY ts) = 1"
    )
    rewritten = parse_select("SELECT user_id FROM users")

    result = check_equivalence(original, rewritten, _USERS_NON_NULL_UNIQUE)

    assert result.status == VerificationStatus.UNKNOWN


def test_check_does_not_prove_identity_that_drops_qualify() -> None:
    original = parse_select(
        "SELECT user_id FROM users QUALIFY ROW_NUMBER() OVER (ORDER BY ts) = 1"
    )
    rewritten = parse_select("SELECT user_id FROM users")

    result = check_equivalence(original, rewritten, _USERS_NON_NULL_UNIQUE)

    assert result.status == VerificationStatus.UNKNOWN


def test_check_proves_distinct_removal_with_matching_qualify() -> None:
    # When the QUALIFY is identical on both sides, DISTINCT removal over a
    # non-null unique key is still sound: the window filter selects the same
    # subset and a unique key stays unique within any subset.
    original = parse_select(
        "SELECT DISTINCT user_id FROM users "
        "QUALIFY ROW_NUMBER() OVER (ORDER BY ts) = 1"
    )
    rewritten = parse_select(
        "SELECT user_id FROM users QUALIFY ROW_NUMBER() OVER (ORDER BY ts) = 1"
    )

    result = check_equivalence(original, rewritten, _USERS_NON_NULL_UNIQUE)

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "remove_redundant_distinct"
