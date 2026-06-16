from qseal.verifier.pair_reduction import reduce_pair

ORIGINAL = """
with a as (select x, y from base_a),
b as (select distinct x from a where y > 0),
c as (select b.x, count(*) as n from orders join b on orders.x = b.x group by b.x)
select * from c
"""
CANDIDATE = """
with a as (select x, y from base_a),
b as (select x from a where y > 0),
c as (select b.x, count(*) as n from orders join b on orders.x = b.x group by b.x)
select * from c
"""


def test_reduces_single_differing_cte_with_preceding_scope() -> None:
    reduced = reduce_pair(ORIGINAL, CANDIDATE)

    assert reduced is not None
    left, right = reduced
    assert "DISTINCT" in left.upper()
    assert "DISTINCT" not in right.upper()
    # Both sides keep the shared preceding CTE in scope and drop the rest.
    for sql in (left, right):
        assert "WITH a AS" in sql
        assert "base_a" in sql
        assert "orders" not in sql


def test_no_reduction_when_outer_query_differs() -> None:
    changed_outer = CANDIDATE.replace("select * from c", "select x from c")
    assert reduce_pair(ORIGINAL, changed_outer) is None


def test_no_reduction_when_two_ctes_differ() -> None:
    two_changes = CANDIDATE.replace("select x, y from base_a", "select x, y, z from base_a")
    assert reduce_pair(ORIGINAL, two_changes) is None


def test_no_reduction_without_with_clause() -> None:
    assert reduce_pair("select 1 from t", "select 2 from t") is None


def test_first_cte_reduction_has_no_with_clause() -> None:
    original = "with a as (select distinct x from t), b as (select x from a) select * from b"
    candidate = "with a as (select x from t), b as (select x from a) select * from b"

    reduced = reduce_pair(original, candidate)

    assert reduced is not None
    assert "WITH" not in reduced[0].upper()
