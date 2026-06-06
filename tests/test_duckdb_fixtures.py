import json

import duckdb
import pytest

from snowprove.fixtures import DuckDbFixtureSpec, create_duckdb_fixture


def test_generates_reproducible_seeded_fixture(tmp_path) -> None:
    spec = DuckDbFixtureSpec(
        seed=42,
        user_rows=1_000,
        order_rows=5_000,
        event_rows=2_000,
        active_fraction=0.2,
        null_fraction=0.1,
        duplicate_fraction=0.25,
        skew_fraction=0.8,
        segment_count=10,
    )

    first = create_duckdb_fixture(tmp_path / "first.duckdb", spec=spec)
    second = create_duckdb_fixture(tmp_path / "second.duckdb", spec=spec)

    assert first.spec == second.spec
    assert first.tables == second.tables
    assert first.tables["users"].row_count == 1_000
    assert first.tables["orders"].row_count == 5_000
    assert first.tables["events"].row_count == 2_000

    users = first.tables["users"].statistics
    orders = first.tables["orders"].statistics
    events = first.tables["events"].statistics
    assert users["active_fraction"] == pytest.approx(0.2, abs=0.02)
    assert users["null_email_fraction"] == pytest.approx(0.1, abs=0.02)
    assert users["segment_one_fraction"] == pytest.approx(0.8, abs=0.02)
    assert orders["null_coupon_fraction"] == pytest.approx(0.1, abs=0.02)
    assert orders["maximum_orders_per_user"] > orders["average_orders_per_observed_user"] * 5
    assert events["duplicate_fraction"] == pytest.approx(0.25)
    assert events["distinct_natural_keys"] == 1_500


def test_different_seed_changes_fixture_content(tmp_path) -> None:
    settings = {
        "user_rows": 100,
        "order_rows": 500,
        "event_rows": 200,
    }
    first = create_duckdb_fixture(
        tmp_path / "first.duckdb",
        spec=DuckDbFixtureSpec(seed=1, **settings),
    )
    second = create_duckdb_fixture(
        tmp_path / "second.duckdb",
        spec=DuckDbFixtureSpec(seed=2, **settings),
    )

    assert first.tables["users"].fingerprint != second.tables["users"].fingerprint
    assert first.tables["orders"].fingerprint != second.tables["orders"].fingerprint


def test_fixture_database_and_manifest_are_reusable(tmp_path) -> None:
    database = tmp_path / "fixture.duckdb"
    manifest_path = tmp_path / "fixture.json"
    manifest = create_duckdb_fixture(
        database,
        manifest_path=manifest_path,
        spec=DuckDbFixtureSpec(user_rows=20, order_rows=50, event_rows=30),
    )

    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone() == (20,)
        assert connection.execute("SELECT count(*) FROM orders").fetchone() == (50,)
        assert connection.execute("SELECT count(*) FROM events").fetchone() == (30,)

    payload = json.loads(manifest_path.read_text())
    assert payload == manifest.model_dump(mode="json")


def test_fixture_refuses_to_replace_existing_outputs_without_force(tmp_path) -> None:
    database = tmp_path / "fixture.duckdb"
    spec = DuckDbFixtureSpec(user_rows=10, order_rows=10, event_rows=10)
    create_duckdb_fixture(database, spec=spec)

    with pytest.raises(FileExistsError, match="Use --force"):
        create_duckdb_fixture(database, spec=spec)

    replacement = create_duckdb_fixture(
        database,
        spec=spec.model_copy(update={"seed": 2}),
        force=True,
    )
    assert replacement.spec.seed == 2
