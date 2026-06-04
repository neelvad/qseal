import subprocess
from pathlib import Path

import yaml

from snowprove.constraints.loader import load_constraint_catalog
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.builtin import BuiltinVerifierBackend
from snowprove.verifier.backends.external import ExternalVerifierBackend
from snowprove.verifier.backends.external_contract import ExternalSolverRequest
from snowprove.verifier.backends.sqlsolver import SqlSolverBackend

FIXTURE = Path(__file__).parent / "fixtures" / "solver_compat"


def test_solver_compat_fixture_matches_builtin_expectations() -> None:
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    cases = yaml.safe_load((FIXTURE / "cases.yml").read_text())["cases"]
    backend = BuiltinVerifierBackend()

    for case in cases:
        result = backend.verify(
            (FIXTURE / case["original"]).read_text(),
            (FIXTURE / case["rewritten"]).read_text(),
            constraints,
        )

        assert result.status == VerificationStatus(case["expected_builtin_status"]), case["name"]


def test_external_solver_request_serializes_contract() -> None:
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    request = ExternalSolverRequest(
        original_sql=" SELECT DISTINCT user_id FROM users \n",
        rewritten_sql=" SELECT user_id FROM users \n",
        constraints=constraints,
        solver_command="sqlsolver",
        timeout_seconds=10,
        metadata={"case": "redundant_distinct"},
    )
    payload = request.model_dump(mode="json")

    assert request.normalized_original_sql() == "SELECT DISTINCT user_id FROM users"
    assert request.normalized_rewritten_sql() == "SELECT user_id FROM users"
    assert payload["solver_command"] == "sqlsolver"
    assert payload["timeout_seconds"] == 10
    assert payload["metadata"] == {"case": "redundant_distinct"}
    assert payload["constraints"]["tables"]["users"]["unique"] == [["user_id"]]


def test_external_backend_stub_preserves_request_metadata() -> None:
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    backend = ExternalVerifierBackend(solver_command="sqlsolver", timeout_seconds=10)

    result = backend.verify(
        " SELECT DISTINCT user_id FROM users \n",
        " SELECT user_id FROM users \n",
        constraints,
    )

    assert result.status == VerificationStatus.UNSUPPORTED
    assert result.rule_name == "external"
    assert result.original_sql == "SELECT DISTINCT user_id FROM users"
    assert result.rewritten_sql == "SELECT user_id FROM users"
    assert "sqlsolver integration is not implemented yet" in str(result.reason)


def test_sqlsolver_backend_maps_eq_result(tmp_path: Path) -> None:
    command = _fake_sqlsolver(tmp_path, "[EQ]")
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    backend = SqlSolverBackend(solver_command=str(command), timeout_seconds=5)

    result = backend.verify(
        (FIXTURE / "redundant_distinct" / "original.sql").read_text(),
        (FIXTURE / "redundant_distinct" / "rewritten.sql").read_text(),
        constraints,
    )

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.rule_name == "sqlsolver"
    assert result.reason == "SQLSolver returned EQ."


def test_sqlsolver_backend_maps_neq_result(tmp_path: Path) -> None:
    command = _fake_sqlsolver(tmp_path, "[NEQ]")
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    backend = SqlSolverBackend(solver_command=str(command))

    result = backend.verify(
        (FIXTURE / "unsafe_distinct" / "original.sql").read_text(),
        (FIXTURE / "unsafe_distinct" / "rewritten.sql").read_text(),
        constraints,
    )

    assert result.status == VerificationStatus.NOT_EQUIVALENT
    assert result.reason == "SQLSolver returned NEQ."


def test_sqlsolver_backend_requires_solver_command() -> None:
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    backend = SqlSolverBackend()

    result = backend.verify("SELECT user_id FROM users", "SELECT user_id FROM users", constraints)

    assert result.status == VerificationStatus.UNSUPPORTED
    assert result.reason == "SQLSolver requires --solver-command."


def test_sqlsolver_backend_writes_one_line_sql_and_schema(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    command = _fake_sqlsolver(tmp_path, "[EQ]", capture_path=capture)
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    backend = SqlSolverBackend(
        solver_command=f"{command} -sql1={{sql1}} -sql2={{sql2}} -schema={{schema}}"
    )

    result = backend.verify(
        "SELECT DISTINCT user_id\nFROM users\n",
        "SELECT user_id\nFROM users\n",
        constraints,
    )

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    captured = capture.read_text()
    assert "SQL1=SELECT DISTINCT user_id FROM users" in captured
    assert "SQL2=SELECT user_id FROM users" in captured
    assert "CREATE TABLE users" in captured
    assert "user_id INT PRIMARY KEY" in captured


def test_sqlsolver_backend_schema_includes_unconstrained_fixture_tables(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    command = _fake_sqlsolver(tmp_path, "[EQ]", capture_path=capture)
    constraints = load_constraint_catalog(FIXTURE / "schema.yml", "auto")
    backend = SqlSolverBackend(solver_command=str(command))

    result = backend.verify(
        (FIXTURE / "unused_left_join" / "original.sql").read_text(),
        (FIXTURE / "unused_left_join" / "rewritten.sql").read_text(),
        constraints,
    )

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    captured = capture.read_text()
    assert "CREATE TABLE fact_orders" in captured
    assert "revenue INT" in captured
    assert "CREATE TABLE dim_users" in captured


def test_sqlsolver_command_wrapper_reports_missing_jar() -> None:
    wrapper = Path("scripts/sqlsolver_command.sh").resolve()

    completed = subprocess.run(
        [str(wrapper), "-print"],
        check=False,
        capture_output=True,
        text=True,
        env={"SQLSOLVER_DIR": "/tmp/snowprove-missing-sqlsolver"},
    )

    assert completed.returncode == 2
    assert "SQLSolver jar not found" in completed.stderr


def _fake_sqlsolver(
    tmp_path: Path,
    output: str,
    capture_path: Path | None = None,
) -> Path:
    script = tmp_path / "fake_sqlsolver.sh"
    capture = capture_path or tmp_path / "capture"
    script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
sql1=""
sql2=""
schema=""
for arg in "$@"; do
  case "$arg" in
    -sql1=*) sql1="${{arg#-sql1=}}" ;;
    -sql2=*) sql2="${{arg#-sql2=}}" ;;
    -schema=*) schema="${{arg#-schema=}}" ;;
  esac
done
{{
  echo "SQL1=$(cat "$sql1")"
  echo "SQL2=$(cat "$sql2")"
  echo "SCHEMA=$(cat "$schema")"
}} > "{capture}"
echo "Verifying pair 1"
echo "1 {output.strip("[]")}"
echo "{output}"
"""
    )
    script.chmod(0o755)
    return script
