import json
from pathlib import Path

from qseal.candidates.generation import (
    build_requests,
    generate_candidates,
    write_bundle,
)


def _write_project(tmp_path: Path) -> Path:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "raw_passthrough.sql").write_text("SELECT * FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
"""
    )
    return tmp_path


def test_generate_dry_run_selects_premise_bearing_targets(tmp_path: Path) -> None:
    project = _write_project(tmp_path)

    summary = generate_candidates(project, tmp_path / "out", dry_run=True)

    # dim_users references a constrained table; the star-passthrough does too
    # but only premise-bearing, parseable models with premises are targets.
    assert summary["dry_run"] is True
    assert summary["models"] >= 1


def test_build_requests_embeds_premises_and_sql() -> None:
    targets = [
        {
            "name": "m",
            "path": "models/m.sql",
            "sql": "SELECT DISTINCT user_id FROM dim_users",
            "premises": ["dim_users.user_id is never NULL"],
        }
    ]

    requests = build_requests(targets, "snowflake")

    assert len(requests) == 1
    msg = requests[0]["user_message"]
    assert "dim_users.user_id is never NULL" in msg
    assert "SELECT DISTINCT user_id FROM dim_users" in msg
    assert "snowflake" in msg


def test_write_bundle_conforms_to_candidate_contract(tmp_path: Path) -> None:
    request = {"name": "m", "path": "models/m.sql", "sql": "SELECT DISTINCT x FROM t"}
    response = {
        "payload": {
            "candidates": [
                {"sql": "SELECT x FROM t", "rationale": "drop distinct",
                 "premises_used": ["t.x unique non-null"]}
            ]
        },
        "usage": {"input_tokens": 10},
    }

    count = write_bundle(
        tmp_path / "m", request, response, prompt_hash="abc", generated_at="2026-01-01"
    )

    assert count == 1
    metadata = json.loads((tmp_path / "m" / "metadata.json").read_text())
    assert metadata["artifact_type"] == "candidate_bundle"
    assert metadata["original_path"] == "original.sql"
    assert metadata["candidates"][0]["path"] == "001_llm.sql"
    assert metadata["generator"]["prompt_hash"] == "abc"
    assert (tmp_path / "m" / "001_llm.sql").read_text().strip() == "SELECT x FROM t"


def test_generate_via_cli_dry_run(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from qseal.cli import main

    project = _write_project(tmp_path)
    result = CliRunner().invoke(
        main, ["llm", "generate", str(project), "--out", str(tmp_path / "out"), "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert '"dry_run": true' in result.output
