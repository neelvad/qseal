from pathlib import Path

from qseal.report.diff import render_rewrite_diff
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus


def test_render_rewrite_diff() -> None:
    diff = render_rewrite_diff(
        Path("models/users.sql"),
        RewriteSuggestion(
            rule_name="remove_redundant_distinct",
            status=VerificationStatus.PROVEN_EQUIVALENT,
            original_sql="SELECT DISTINCT user_id\nFROM users;",
            rewritten_sql="SELECT user_id\nFROM users;",
        ),
    )

    assert diff is not None
    assert "--- models/users.sql" in diff
    assert "+++ models/users.sql" in diff
    assert "-SELECT DISTINCT user_id" in diff
    assert "+SELECT user_id" in diff


def test_render_rewrite_diff_ignores_non_rewrites() -> None:
    diff = render_rewrite_diff(
        Path("models/users.sql"),
        RewriteSuggestion(
            rule_name="unknown",
            status=VerificationStatus.UNKNOWN,
            original_sql="SELECT user_id FROM users",
        ),
    )

    assert diff is None
