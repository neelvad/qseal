from pathlib import Path

from qseal.corpus.model import LoadedTaskCorpus
from qseal.fixtures import DuckDbFixtureManifest, create_duckdb_fixture


def materialize_corpus_fixtures(
    corpus: LoadedTaskCorpus,
    output_dir: Path,
    *,
    force: bool = False,
) -> dict[str, DuckDbFixtureManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests = {}
    for fixture in corpus.manifest.fixtures:
        database_path = output_dir / f"{fixture.fixture_id}.duckdb"
        manifest_path = output_dir / f"{fixture.fixture_id}.manifest.json"
        manifests[fixture.fixture_id] = create_duckdb_fixture(
            database_path,
            spec=fixture.spec,
            manifest_path=manifest_path,
            force=force,
        )
    return manifests
