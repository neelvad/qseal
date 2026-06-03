from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.distinct import RemoveRedundantDistinct


def test_removes_distinct_when_projection_contains_unique_key() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveRedundantDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM users;"


def test_removes_distinct_from_qualified_relation() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM analytics.public.users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveRedundantDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM analytics.public.users;"


def test_removes_distinct_while_preserving_column_alias() -> None:
    query = parse_select("SELECT DISTINCT user_id AS id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveRedundantDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id AS id\nFROM users;"


def test_removes_distinct_while_preserving_where_predicates() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM users WHERE status = 'active'")
    constraints = ConstraintCatalog(tables={"users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveRedundantDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM users\nWHERE status = 'active';"


def test_keeps_distinct_when_uniqueness_is_unknown() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM users")
    constraints = ConstraintCatalog(tables={"users": TableConstraints()})

    suggestion = RemoveRedundantDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN
    assert suggestion.rewritten_sql is None
