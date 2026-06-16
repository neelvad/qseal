import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from qseal.dialects import DEFAULT_DIALECT, SqlDialect


def reduce_pair(
    original_sql: str,
    rewritten_sql: str,
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> tuple[str, str] | None:
    """Shrink a pair differing in exactly one CTE body to that fragment.

    When two WITH queries have identical CTE names in identical order,
    identical outer queries, and all CTE bodies equal except one, proving the
    differing bodies equivalent (with the shared preceding CTEs in scope)
    proves the full pair by congruence: every later reference sees the same
    relation. Solver difficulty grows sharply with query size, so the reduced
    pair is dramatically easier to discharge.

    Returns None when the reduction does not apply. The reduction is only
    valid for *proving*: a counterexample for the fragment does not imply one
    for the full pair, so refuters must keep using the full queries.
    """
    try:
        trees = [
            sqlglot.parse_one(sql, read=dialect)
            for sql in (original_sql, rewritten_sql)
        ]
    except SqlglotError:
        return None
    if not all(isinstance(tree, exp.Select) for tree in trees):
        return None

    withs = [tree.args.get("with_") for tree in trees]
    if any(item is None or item.args.get("recursive") for item in withs):
        return None
    cte_lists = [item.expressions for item in withs]
    if len(cte_lists[0]) != len(cte_lists[1]):
        return None

    outers = []
    for tree in trees:
        outer = tree.copy()
        outer.set("with_", None)
        outers.append(outer)
    if outers[0] != outers[1]:
        return None

    differing = []
    for index, (left, right) in enumerate(zip(*cte_lists, strict=True)):
        if left.alias != right.alias:
            return None
        if left.this != right.this:
            differing.append(index)
    if len(differing) != 1:
        return None

    index = differing[0]
    if any(cte_list[index].this.args.get("with_") for cte_list in cte_lists):
        return None
    reduced = []
    for cte_list in cte_lists:
        body = cte_list[index].this.copy()
        if index > 0:
            body.set(
                "with_",
                exp.With(expressions=[cte.copy() for cte in cte_list[:index]]),
            )
        reduced.append(body.sql(dialect=dialect))
    return tuple(reduced)
