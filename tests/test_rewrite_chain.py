import json
from pathlib import Path

from click.testing import CliRunner

from qseal.cli import main
from qseal.constraints.model import ConstraintCatalog, TableConstraints
from qseal.rewrites.chain import suggest_rewrite_chain
from qseal.rewrites.registry import DEFAULT_RULES

USERS = ConstraintCatalog(
    tables={
        "users": TableConstraints(
            columns={"user_id": {"nullable": False}},
            unique=[("user_id",)],
        )
    }
)


def test_rewrite_chain_applies_verified_steps_until_fixed_point() -> None:
    chain = suggest_rewrite_chain(
        "SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL",
        USERS,
        rules=DEFAULT_RULES,
    )

    assert chain.status == "FIXED_POINT"
    assert chain.step_count == 2
    assert [step.suggestion.rule_name for step in chain.steps] == [
        "remove_redundant_not_null_filter",
        "remove_redundant_distinct",
    ]
    assert chain.final_sql == "SELECT user_id\nFROM users;"


def test_rewrite_chain_can_apply_cte_fragment_rewrites() -> None:
    chain = suggest_rewrite_chain(
        """
WITH source AS (
  SELECT DISTINCT user_id FROM users
)
SELECT user_id FROM source
""",
        USERS,
        rules=DEFAULT_RULES,
    )

    assert chain.status == "FIXED_POINT"
    assert chain.step_count == 1
    assert chain.steps[0].suggestion.rule_name == "remove_redundant_distinct"
    assert chain.steps[0].suggestion.fragment_location == "cte:source"
    assert "DISTINCT" not in chain.final_sql
    assert "FROM users" in chain.final_sql


def test_suggest_chain_cli_reports_steps(tmp_path: Path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL")
    schema.write_text(
        """
tables:
  users:
    columns:
      user_id:
        nullable: false
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "suggest",
            str(query),
            "--schema",
            str(schema),
            "--chain",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "rewrite_chain"
    assert payload["status"] == "FIXED_POINT"
    assert payload["step_count"] == 2
    assert payload["steps"][0]["suggestion"]["status"] == "PROVEN_EQUIVALENT"
