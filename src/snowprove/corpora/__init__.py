from pathlib import Path


def bundled_corpus_path(name: str = "duckdb-v1") -> Path:
    path = Path(__file__).parent / name / "corpus.yml"
    if not path.is_file():
        raise ValueError(f"Unknown bundled corpus: {name}.")
    return path


__all__ = ["bundled_corpus_path"]
