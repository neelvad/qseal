import json
from pathlib import Path

from qseal.constraints.model import ConstraintCatalog, TableConstraints
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.backends.verieql import VeriEqlBackend, _build_request

UNIQUE_NON_NULL_USERS = ConstraintCatalog(
    tables={
        "users": TableConstraints(
            columns={"user_id": {"nullable": False}, "email": {"nullable": False}},
            unique=[("user_id",)],
        )
    }
)


def _fake_backend(tmp_path: Path, payload: dict) -> VeriEqlBackend:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(f"#!/bin/sh\necho '{json.dumps(payload)}'\n")
    fake_python.chmod(0o755)
    return VeriEqlBackend(verieql_dir=tmp_path, python_path=fake_python)


def test_refute_maps_counterexample_to_not_equivalent(tmp_path: Path) -> None:
    backend = _fake_backend(
        tmp_path,
        {"result": "refuted", "counterexample": "INSERT INTO users ...", "bound": 2},
    )

    result = backend.refute(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        ConstraintCatalog(),
    )

    assert result.status == VerificationStatus.NOT_EQUIVALENT
    assert result.counterexample == "INSERT INTO users ..."


def test_refute_maps_bounded_ok_to_unknown_not_proven(tmp_path: Path) -> None:
    backend = _fake_backend(
        tmp_path,
        {"result": "bounded_ok", "counterexample": None, "bound": 2},
    )

    result = backend.refute(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        UNIQUE_NON_NULL_USERS,
    )

    assert result.status == VerificationStatus.UNKNOWN
    assert "not a proof" in result.reason


def test_refute_requires_verieql_dir() -> None:
    result = VeriEqlBackend().refute(
        "SELECT user_id FROM users",
        "SELECT user_id FROM users",
        ConstraintCatalog(),
    )

    assert result.status == VerificationStatus.UNSUPPORTED


def test_refute_abstains_on_qualify(tmp_path: Path) -> None:
    backend = _fake_backend(tmp_path, {"result": "bounded_ok", "bound": 2})

    result = backend.refute(
        "SELECT user_id FROM users QUALIFY ROW_NUMBER() OVER (ORDER BY user_id) = 1",
        "SELECT user_id FROM users",
        ConstraintCatalog(),
    )

    assert result.status == VerificationStatus.UNSUPPORTED
    assert "QUALIFY" in result.reason


def test_refute_abstains_on_nullable_unique_premise(tmp_path: Path) -> None:
    backend = _fake_backend(tmp_path, {"result": "bounded_ok", "bound": 2})
    nullable_unique = ConstraintCatalog(
        tables={"users": TableConstraints(unique=[("user_id",)])}
    )

    result = backend.refute(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        nullable_unique,
    )

    assert result.status == VerificationStatus.UNSUPPORTED
    assert "cannot encode" in result.reason


def test_build_request_encodes_premises_uppercased() -> None:
    request = _build_request(
        "SELECT user_id FROM users WHERE email IS NOT NULL",
        "SELECT user_id FROM users",
        UNIQUE_NON_NULL_USERS,
        "snowflake",
        2,
    )

    assert request["schema"] == {"USERS": {"EMAIL": "INT", "USER_ID": "INT"}}
    assert {"primary": [{"value": "USERS__USER_ID"}]} in request["constraints"]
    assert {"not_null": {"value": "USERS__EMAIL"}} in request["constraints"]


def test_build_request_resolves_star_passthrough_ctes() -> None:
    request = _build_request(
        "with src as (select * from stg_users) select distinct user_id from src",
        "with src as (select * from stg_users) select user_id from src",
        ConstraintCatalog(),
        "snowflake",
        2,
    )

    assert request["schema"] == {"STG_USERS": {"USER_ID": "INT"}}


def test_build_request_abstains_on_ambiguous_unqualified_columns() -> None:
    request = _build_request(
        "SELECT name FROM a JOIN b ON a.id = b.id",
        "SELECT name FROM a JOIN b ON a.id = b.id",
        ConstraintCatalog(),
        "snowflake",
        2,
    )

    assert isinstance(request, str)
    assert "ambiguous" in request


def _write_scan_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    models = project / "models"
    models.mkdir(parents=True)
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
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
    return project


def test_dbt_crosscheck_passes_when_findings_survive(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from qseal.cli import main

    project = _write_scan_project(tmp_path)
    fake = tmp_path / "fake-python"
    fake.write_text('#!/bin/sh\necho \'{"result": "bounded_ok", "bound": 2}\'\n')
    fake.chmod(0o755)

    result = CliRunner().invoke(
        main,
        [
            "dbt",
            "crosscheck",
            str(project),
            "--verieql-dir",
            str(tmp_path),
            "--verieql-python",
            str(fake),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Proven findings cross-checked: 1" in result.output
    assert "Refuted: 0" in result.output


def test_dbt_crosscheck_fails_on_refuted_finding(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from qseal.cli import main

    project = _write_scan_project(tmp_path)
    fake = tmp_path / "fake-python"
    fake.write_text(
        '#!/bin/sh\necho \'{"result": "refuted", "counterexample": "INSERT ...", "bound": 2}\'\n'
    )
    fake.chmod(0o755)

    result = CliRunner().invoke(
        main,
        [
            "dbt",
            "crosscheck",
            str(project),
            "--verieql-dir",
            str(tmp_path),
            "--verieql-python",
            str(fake),
        ],
    )

    assert result.exit_code == 1
    assert "NOT_EQUIVALENT" in result.output
    assert "Refuted: 1" in result.output
