import json
from pathlib import Path
from typing import Any

METADATA_FILENAME = "metadata.json"


def load_candidate_metadata(candidates_dir: Path | None) -> dict[str, dict[str, Any]]:
    if candidates_dir is None:
        return {}

    metadata_path = candidates_dir / METADATA_FILENAME
    if not metadata_path.exists():
        return {}

    payload = json.loads(metadata_path.read_text())
    candidates = payload.get("candidates") or []
    metadata: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        path_value = candidate.get("path")
        if not isinstance(path_value, str):
            continue

        candidate_path = candidates_dir / path_value
        metadata[str(candidate_path)] = {
            key: value
            for key, value in candidate.items()
            if key != "path"
        }

    return metadata
