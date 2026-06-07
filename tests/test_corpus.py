from pathlib import Path
from shutil import copytree

import pytest
import yaml

from snowprove.corpora import bundled_corpus_path
from snowprove.corpus import load_task_corpus, materialize_corpus_fixtures
from snowprove.environment import RewriteEnvironment
from snowprove.rewrites.registry import select_rules

CORPUS_PATH = bundled_corpus_path()


def test_loads_versioned_duckdb_corpus() -> None:
    corpus = load_task_corpus(CORPUS_PATH)

    assert corpus.manifest.corpus_id == "duckdb-foundations"
    assert corpus.manifest.corpus_version == "2"
    assert corpus.manifest.dialect == "duckdb"
    assert len(corpus.manifest.fixtures) == 4
    assert len(corpus.manifest.task_families) == 5
    assert len(corpus.tasks) == 25
    assert [task.definition.task_id for task in corpus.tasks[:5]] == [
        "redundant-distinct-users",
        "redundant-not-null-user-id",
        "unused-left-join-users",
        "join-distinct-to-exists",
        "distinct-and-not-null",
    ]
    assert len(corpus.fingerprint) == 64

    task = corpus.task("distinct-and-not-null")
    assert task.environment_task.dialect == "duckdb"
    assert task.environment_task.max_steps == 4
    assert task.environment_task.metadata == {
        "corpus_id": "duckdb-foundations",
        "corpus_version": "2",
        "fixture_id": "standard-small",
        "tags": ["distinct", "filter", "multi-action", "order-sensitive"],
    }
    assert task.fixture.spec.seed == 42
    assert len(task.fingerprint) == 64

    generated = corpus.task("distinct-orders-duplicate-heavy-small")
    assert generated.definition.family_id == "distinct"
    assert generated.definition.variant_id == "orders"
    assert generated.environment_task.metadata == {
        "corpus_id": "duckdb-foundations",
        "corpus_version": "2",
        "fixture_id": "duplicate-heavy-small",
        "tags": [
            "distinct",
            "uniqueness",
            "single-action",
            "table:orders",
            "fixture:duplicate-heavy-small",
            "generated",
        ],
        "family_id": "distinct",
        "variant_id": "orders",
    }


def test_bundled_corpus_path_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown bundled corpus"):
        bundled_corpus_path("missing")


def test_every_corpus_task_has_an_initial_rewrite_action() -> None:
    corpus = load_task_corpus(CORPUS_PATH)

    for task in corpus.tasks:
        environment = RewriteEnvironment(
            rules=select_rules(task.definition.enabled_rules)
        )
        observation = environment.reset(task.environment_task)

        assert observation.actions, task.definition.task_id
        assert {
            action.match.rule_name for action in observation.actions
        } <= set(task.definition.enabled_rules)


def test_corpus_fingerprint_is_independent_of_checkout_path(tmp_path: Path) -> None:
    original = load_task_corpus(CORPUS_PATH)
    copied_root = copytree(CORPUS_PATH.parent, tmp_path / "copied-corpus")
    copied = load_task_corpus(copied_root / "corpus.yml")

    assert copied.fingerprint == original.fingerprint
    assert [task.fingerprint for task in copied.tasks] == [
        task.fingerprint for task in original.tasks
    ]


def test_materializes_each_named_fixture_once(tmp_path: Path) -> None:
    copied_root = copytree(CORPUS_PATH.parent, tmp_path / "small-corpus")
    manifest_path = copied_root / "corpus.yml"
    payload = yaml.safe_load(manifest_path.read_text())
    payload["fixtures"] = [
        {
            "fixture_id": "tiny",
            "spec": {
                "seed": 7,
                "user_rows": 20,
                "order_rows": 30,
                "event_rows": 10,
            },
        }
    ]
    for task in payload["tasks"]:
        task["fixture_id"] = "tiny"
    for family in payload["task_families"]:
        family["fixture_ids"] = ["tiny"]
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    corpus = load_task_corpus(manifest_path)

    manifests = materialize_corpus_fixtures(corpus, tmp_path / "databases")

    assert tuple(manifests) == ("tiny",)
    assert manifests["tiny"].tables["users"].row_count == 20
    assert (tmp_path / "databases" / "tiny.duckdb").is_file()
    assert (tmp_path / "databases" / "tiny.manifest.json").is_file()


def test_query_change_updates_task_and_corpus_fingerprints(tmp_path: Path) -> None:
    original = load_task_corpus(CORPUS_PATH)
    copied_root = copytree(CORPUS_PATH.parent, tmp_path / "changed-corpus")
    query_path = copied_root / "queries" / "redundant-distinct-users.sql"
    query_path.write_text(f"{query_path.read_text().strip()}\n\n")

    whitespace_only = load_task_corpus(copied_root / "corpus.yml")
    assert whitespace_only.fingerprint == original.fingerprint

    query_path.write_text(
        query_path.read_text().replace("FROM users", "FROM users WHERE status = 'active'")
    )
    changed = load_task_corpus(copied_root / "corpus.yml")

    assert changed.task("redundant-distinct-users").fingerprint != original.task(
        "redundant-distinct-users"
    ).fingerprint
    assert changed.fingerprint != original.fingerprint


def test_rejects_unknown_rule(tmp_path: Path) -> None:
    copied_root = copytree(CORPUS_PATH.parent, tmp_path / "unknown-rule")
    manifest_path = copied_root / "corpus.yml"
    payload = yaml.safe_load(manifest_path.read_text())
    payload["tasks"][0]["enabled_rules"] = ["missing_rule"]
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="unknown rewrite rules: missing_rule"):
        load_task_corpus(manifest_path)


def test_rejects_paths_outside_corpus_root(tmp_path: Path) -> None:
    copied_root = copytree(CORPUS_PATH.parent, tmp_path / "escaped-path")
    outside_query = tmp_path / "outside.sql"
    outside_query.write_text("SELECT 1")
    manifest_path = copied_root / "corpus.yml"
    payload = yaml.safe_load(manifest_path.read_text())
    payload["tasks"][0]["query_path"] = "../outside.sql"
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="escapes the corpus directory"):
        load_task_corpus(manifest_path)


def test_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    copied_root = copytree(CORPUS_PATH.parent, tmp_path / "duplicate-task")
    manifest_path = copied_root / "corpus.yml"
    payload = yaml.safe_load(manifest_path.read_text())
    payload["tasks"][1]["task_id"] = payload["tasks"][0]["task_id"]
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="Duplicate task IDs"):
        load_task_corpus(manifest_path)


def test_rejects_expanded_task_id_collision(tmp_path: Path) -> None:
    copied_root = copytree(CORPUS_PATH.parent, tmp_path / "expanded-collision")
    manifest_path = copied_root / "corpus.yml"
    payload = yaml.safe_load(manifest_path.read_text())
    payload["tasks"][0]["task_id"] = (
        "distinct-users-active-heavy-small"
    )
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="Expanded corpus contains duplicate task IDs"):
        load_task_corpus(manifest_path)


def test_unknown_loaded_task_raises_key_error() -> None:
    corpus = load_task_corpus(CORPUS_PATH)

    with pytest.raises(KeyError, match="Unknown corpus task"):
        corpus.task("missing")
