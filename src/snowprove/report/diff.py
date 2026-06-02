from difflib import unified_diff
from pathlib import Path

from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


def render_rewrite_diff(path: Path, suggestion: RewriteSuggestion) -> str | None:
    if (
        suggestion.status != VerificationStatus.PROVEN_EQUIVALENT
        or suggestion.rewritten_sql is None
    ):
        return None

    original = _lines(suggestion.original_sql)
    rewritten = _lines(suggestion.rewritten_sql)
    return "".join(
        unified_diff(
            original,
            rewritten,
            fromfile=str(path),
            tofile=str(path),
        )
    )


def _lines(sql: str) -> list[str]:
    return [f"{line}\n" for line in sql.strip().splitlines()]
