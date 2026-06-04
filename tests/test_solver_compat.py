from pathlib import Path

import yaml

from snowprove.constraints.loader import load_constraint_catalog
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.builtin import BuiltinVerifierBackend
from snowprove.verifier.backends.external import ExternalVerifierBackend
from snowprove.verifier.backends.external_contract import ExternalSolverRequest

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
