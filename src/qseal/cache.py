from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def content_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class JsonFileCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, kind: str, key: str, model_type: type[BaseModel]) -> BaseModel | None:
        path = self.path(kind, key)
        if not path.exists():
            return None
        return model_type.model_validate_json(path.read_text())

    def store(self, kind: str, key: str, value: BaseModel) -> Path:
        path = self.path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = value.model_dump_json(indent=2)
        descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w") as handle:
                handle.write(f"{payload}\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
        return path

    def path(self, kind: str, key: str) -> Path:
        return self.root / kind / key[:2] / f"{key}.json"
