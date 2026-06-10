from collections.abc import Sequence

from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.parser.fragments import parse_select_fragments, replace_fragment_sql
from snowprove.parser.sqlglot_parser import UnsupportedSqlError
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.rewrites.registry import DEFAULT_RULES, RewriteRule, suggest_rewrites


def suggest_subtree_rewrites(
    sql: str,
    constraints: ConstraintCatalog,
    rules: Sequence[RewriteRule] = DEFAULT_RULES,
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> list[RewriteSuggestion]:
    """Suggest proven rewrites for supported fragments of a larger WITH query.

    Each proven fragment rewrite is spliced back into the full query, so the
    returned suggestions always rewrite the whole query. Replacing a fragment
    with a proven-equivalent body preserves the semantics of the enclosing
    query, even when the enclosing query itself is outside the supported
    subset.
    """
    try:
        fragments = parse_select_fragments(sql, dialect)
    except UnsupportedSqlError:
        return []

    suggestions = []
    for fragment in fragments:
        if fragment.query is None:
            continue
        for suggestion in suggest_rewrites(fragment.query, constraints, rules=rules):
            if suggestion.status != VerificationStatus.PROVEN_EQUIVALENT:
                continue
            if suggestion.rewritten_sql is None:
                continue
            full_sql = replace_fragment_sql(
                sql,
                fragment.location,
                suggestion.rewritten_sql,
                dialect,
            )
            reason = suggestion.reason or "Fragment rewrite is proven equivalent."
            suggestions.append(
                RewriteSuggestion(
                    rule_name=suggestion.rule_name,
                    status=VerificationStatus.PROVEN_EQUIVALENT,
                    original_sql=sql.strip(),
                    rewritten_sql=full_sql,
                    assumptions=suggestion.assumptions,
                    reason=f"{reason} Applied inside {fragment.describe()}.",
                )
            )
    return suggestions
