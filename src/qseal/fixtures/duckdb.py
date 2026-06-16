from __future__ import annotations

import json
from pathlib import Path

import duckdb

from qseal.fixtures.model import (
    DuckDbFixtureManifest,
    DuckDbFixtureSpec,
    FixtureTableSummary,
)

_MODULUS = 2_147_483_647


def create_duckdb_fixture(
    database_path: Path,
    *,
    spec: DuckDbFixtureSpec | None = None,
    manifest_path: Path | None = None,
    force: bool = False,
) -> DuckDbFixtureManifest:
    spec = spec or DuckDbFixtureSpec()
    manifest_path = manifest_path or database_path.with_suffix(
        f"{database_path.suffix}.manifest.json"
    )
    _prepare_output(database_path, manifest_path, force)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("SET threads = 1")
        _create_users(connection, spec)
        _create_orders(connection, spec)
        _create_events(connection, spec)
        connection.execute("CHECKPOINT")
        manifest = DuckDbFixtureManifest(
            database_path=str(database_path),
            duckdb_version=duckdb.__version__,
            spec=spec,
            tables=_table_summaries(connection),
        )
    except Exception:
        connection.close()
        database_path.unlink(missing_ok=True)
        raise
    else:
        connection.close()

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        f"{json.dumps(manifest.model_dump(mode='json'), indent=2, sort_keys=True)}\n"
    )
    return manifest


def _prepare_output(database_path: Path, manifest_path: Path, force: bool) -> None:
    existing = [path for path in (database_path, manifest_path) if path.exists()]
    if existing and not force:
        paths = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Fixture output already exists: {paths}. Use --force.")
    if force:
        database_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)


def _create_users(
    connection: duckdb.DuckDBPyConnection,
    spec: DuckDbFixtureSpec,
) -> None:
    active_cutoff = _cutoff(spec.active_fraction)
    null_cutoff = _cutoff(spec.null_fraction)
    skew_cutoff = _cutoff(spec.skew_fraction)
    segment_sql = "1"
    if spec.segment_count > 1:
        segment_sql = (
            f"CASE WHEN {_score('user_id', spec.seed, 31)} < {skew_cutoff} "
            "THEN 1 ELSE "
            f"2 + ({_value('user_id', spec.seed, 47)} % {spec.segment_count - 1}) END"
        )

    connection.execute(
        f"""
        CREATE TABLE users AS
        SELECT
          user_id,
          CASE WHEN {_score("user_id", spec.seed, 11)} < {active_cutoff}
            THEN 'active' ELSE 'inactive' END AS status,
          CASE WHEN {_score("user_id", spec.seed, 23)} < {null_cutoff}
            THEN NULL ELSE 'user-' || user_id || '@example.test' END AS email,
          {segment_sql}::INTEGER AS segment_id
        FROM range(1, {spec.user_rows + 1}) AS generated(user_id)
        """
    )
    connection.execute("CREATE UNIQUE INDEX users_user_id ON users(user_id)")


def _create_orders(
    connection: duckdb.DuckDBPyConnection,
    spec: DuckDbFixtureSpec,
) -> None:
    skew_cutoff = _cutoff(spec.skew_fraction)
    hot_user_count = max(1, spec.user_rows // 100)
    connection.execute(
        f"""
        CREATE TABLE orders AS
        SELECT
          order_id,
          CASE WHEN {_score("order_id", spec.seed, 59)} < {skew_cutoff}
            THEN 1 + ({_value("order_id", spec.seed, 61)} % {hot_user_count})
            ELSE 1 + ({_value("order_id", spec.seed, 67)} % {spec.user_rows})
          END AS user_id,
          1 + ({_value("order_id", spec.seed, 71)} % 10000) AS amount_cents,
          CASE WHEN {_score("order_id", spec.seed, 73)} < {_cutoff(spec.null_fraction)}
            THEN NULL ELSE 1 + ({_value("order_id", spec.seed, 79)} % 20)
          END AS coupon_id
        FROM range(1, {spec.order_rows + 1}) AS generated(order_id)
        """
    )
    connection.execute("CREATE UNIQUE INDEX orders_order_id ON orders(order_id)")
    connection.execute("CREATE INDEX orders_user_id ON orders(user_id)")


def _create_events(
    connection: duckdb.DuckDBPyConnection,
    spec: DuckDbFixtureSpec,
) -> None:
    distinct_keys = max(1, round(spec.event_rows * (1 - spec.duplicate_fraction)))
    connection.execute(
        f"""
        CREATE TABLE events AS
        SELECT
          event_id,
          1 + ((event_id - 1) % {distinct_keys}) AS natural_key,
          1 + ({_value("event_id", spec.seed, 83)} % {spec.user_rows}) AS user_id,
          {_value("event_id", spec.seed, 89)} % 100 AS payload_value
        FROM range(1, {spec.event_rows + 1}) AS generated(event_id)
        """
    )
    connection.execute("CREATE UNIQUE INDEX events_event_id ON events(event_id)")
    connection.execute("CREATE INDEX events_natural_key ON events(natural_key)")


def _table_summaries(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, FixtureTableSummary]:
    user_stats = connection.execute(
        """
        SELECT
          count(*),
          count(*) FILTER (WHERE status = 'active')::DOUBLE / count(*),
          count(*) FILTER (WHERE email IS NULL)::DOUBLE / count(*),
          count(*) FILTER (WHERE segment_id = 1)::DOUBLE / count(*),
          sum(hash(user_id, status, email, segment_id)::HUGEINT)
        FROM users
        """
    ).fetchone()
    order_stats = connection.execute(
        """
        WITH per_user AS (
          SELECT user_id, count(*) AS order_count
          FROM orders
          GROUP BY user_id
        )
        SELECT
          (SELECT count(*) FROM orders),
          avg(order_count),
          max(order_count),
          (SELECT count(*) FILTER (WHERE coupon_id IS NULL)::DOUBLE / count(*) FROM orders),
          (SELECT sum(hash(order_id, user_id, amount_cents, coupon_id)::HUGEINT) FROM orders)
        FROM per_user
        """
    ).fetchone()
    event_stats = connection.execute(
        """
        SELECT
          count(*),
          1 - count(DISTINCT natural_key)::DOUBLE / count(*),
          count(DISTINCT natural_key),
          sum(hash(event_id, natural_key, user_id, payload_value)::HUGEINT)
        FROM events
        """
    ).fetchone()

    assert user_stats is not None
    assert order_stats is not None
    assert event_stats is not None
    return {
        "users": FixtureTableSummary(
            row_count=user_stats[0],
            fingerprint=str(user_stats[4]),
            statistics={
                "active_fraction": user_stats[1],
                "null_email_fraction": user_stats[2],
                "segment_one_fraction": user_stats[3],
            },
        ),
        "orders": FixtureTableSummary(
            row_count=order_stats[0],
            fingerprint=str(order_stats[4]),
            statistics={
                "average_orders_per_observed_user": order_stats[1],
                "maximum_orders_per_user": order_stats[2],
                "null_coupon_fraction": order_stats[3],
            },
        ),
        "events": FixtureTableSummary(
            row_count=event_stats[0],
            fingerprint=str(event_stats[3]),
            statistics={
                "duplicate_fraction": event_stats[1],
                "distinct_natural_keys": event_stats[2],
            },
        ),
    }


def _value(column: str, seed: int, salt: int) -> str:
    normalized_seed = seed + 1_000_000_000
    seed_term = normalized_seed * 12345 + salt
    return f"(({column} * 1103515245::BIGINT + {seed_term}) % {_MODULUS})"


def _score(column: str, seed: int, salt: int) -> str:
    return _value(column, seed, salt)


def _cutoff(fraction: float) -> int:
    return round(fraction * _MODULUS)
