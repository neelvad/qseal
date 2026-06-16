import json
from pathlib import Path

from qseal.candidates.verification import merge_reports, verify_candidate
from qseal.constraints.model import ConstraintCatalog, TableConstraints
from qseal.verifier.backends.builtin import BuiltinVerifierBackend

UNIQUE_NON_NULL = ConstraintCatalog(
    tables={
        "users": TableConstraints(
            columns={"user_id": {"nullable": False}}, unique=[("user_id",)]
        )
    }
)


def test_verify_candidate_detects_identity() -> None:
    row = verify_candidate(
        "SELECT user_id FROM users",
        "SELECT  user_id  FROM users",
        ConstraintCatalog(),
        "snowflake",
        builtin=BuiltinVerifierBackend(),
        solver=None,
        qed=None,
        refuter=None,
    )
    assert row["bucket"] == "identity"


def test_verify_candidate_proven_by_builtin() -> None:
    row = verify_candidate(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        UNIQUE_NON_NULL,
        "snowflake",
        builtin=BuiltinVerifierBackend(),
        solver=None,
        qed=None,
        refuter=None,
    )
    assert row["bucket"] == "proven"
    assert row["prover"] == "builtin"


def test_verify_candidate_unknown_without_premise() -> None:
    row = verify_candidate(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        ConstraintCatalog(),
        "snowflake",
        builtin=BuiltinVerifierBackend(),
        solver=None,
        qed=None,
        refuter=None,
    )
    assert row["bucket"] == "unknown"


def test_merge_reports_takes_best_verdict_and_flags_conflicts(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"results": [
        {"model": "m", "candidate": "1", "bucket": "unknown"},
        {"model": "m", "candidate": "2", "bucket": "proven"},
    ]}))
    b.write_text(json.dumps({"results": [
        {"model": "m", "candidate": "1", "bucket": "proven"},
        {"model": "m", "candidate": "2", "bucket": "refuted"},
    ]}))

    result = merge_reports([a, b], tmp_path / "merged.json")

    # candidate 1: unknown + proven -> proven wins
    assert result["buckets"].get("proven") == 1
    # candidate 2: proven + refuted -> conflict alarm
    assert result["buckets"].get("conflict") == 1
    assert result["conflicts"] == ["m/2"]


def test_llm_verify_cli_on_bundle(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from qseal.cli import main

    bundle = tmp_path / "users_distinct"
    bundle.mkdir()
    (bundle / "original.sql").write_text("SELECT DISTINCT user_id FROM users")
    (bundle / "001_llm.sql").write_text("SELECT user_id FROM users")
    (bundle / "metadata.json").write_text(json.dumps({
        "original_path": "original.sql",
        "candidates": [{"path": "001_llm.sql", "description": "drop distinct"}],
    }))
    (tmp_path / "constraints.json").write_text(UNIQUE_NON_NULL.model_dump_json())

    result = CliRunner().invoke(main, ["llm", "verify", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert '"proven": 1' in result.output
