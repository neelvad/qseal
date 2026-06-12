from pathlib import Path

from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.qed import QedBackend, _qed_case

UNIQUE_NON_NULL_USERS = ConstraintCatalog(
    tables={
        "users": TableConstraints(
            columns={"user_id": {"nullable": False}},
            unique=[("user_id",)],
        )
    }
)


def _fake_backend(tmp_path: Path, prover_output: str) -> QedBackend:
    fake_java = tmp_path / "fake-java"
    fake_java.write_text(
        '#!/bin/sh\nfor arg; do path="$arg"; done\n: > "${path%.sql}.json"\n'
    )
    fake_java.chmod(0o755)
    fake_prover = tmp_path / "fake-prover"
    fake_prover.write_text(f"#!/bin/sh\nprintf '%s\\n' '{prover_output}'\n")
    fake_prover.chmod(0o755)
    return QedBackend(
        parser_jar=tmp_path / "parser.jar",
        prover_path=fake_prover,
        java_path=fake_java,
    )


def test_verify_requires_configuration(monkeypatch) -> None:
    monkeypatch.delenv("SNOWPROVE_QED_PARSER_JAR", raising=False)
    monkeypatch.delenv("SNOWPROVE_QED_PROVER", raising=False)

    result = QedBackend().verify(
        "SELECT user_id FROM users",
        "SELECT user_id FROM users",
        ConstraintCatalog(),
    )

    assert result.status == VerificationStatus.UNSUPPORTED


def test_verify_maps_provable(tmp_path: Path) -> None:
    backend = _fake_backend(tmp_path, "/tmp/pair.json\tProvable(Stats {})")

    result = backend.verify(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        UNIQUE_NON_NULL_USERS,
    )

    assert result.status == VerificationStatus.PROVEN_EQUIVALENT
    assert result.safety_claim == "SOLVER_PROVEN_EQUIVALENT"


def test_verify_maps_not_provable_to_unknown(tmp_path: Path) -> None:
    backend = _fake_backend(tmp_path, "/tmp/pair.json\tNotProvable(Stats {})")

    result = backend.verify(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        ConstraintCatalog(tables={"users": TableConstraints()}),
    )

    assert result.status == VerificationStatus.UNKNOWN
    assert "NotProvable" in result.reason


def test_qed_case_emits_unique_only_with_non_null() -> None:
    # QED's UNIQUE is strict (NULLs included), so a nullable unique key must
    # be omitted rather than overstated.
    schema = {"users": {"user_id", "status"}, "orders": {"order_id"}}
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"user_id": {"nullable": False}},
                unique=[("user_id",)],
            ),
            "orders": TableConstraints(unique=[("order_id",)]),
        }
    )

    case = _qed_case(schema, constraints, "SELECT 1 FROM users", "SELECT 1 FROM users")

    assert "user_id integer not null" in case
    assert "unique (user_id)" in case
    assert "order_id integer" in case
    assert "unique (order_id)" not in case
