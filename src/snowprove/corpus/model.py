from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from snowprove.environment import EnvironmentTask
from snowprove.fixtures import DuckDbFixtureSpec


class CorpusFixture(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    spec: DuckDbFixtureSpec


class CorpusTaskDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    query_path: str = Field(min_length=1)
    constraints_path: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    max_steps: int = Field(default=8, ge=1)
    enabled_rules: tuple[str, ...] = Field(min_length=1)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    expected_verifiers: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_values(self) -> CorpusTaskDefinition:
        _require_unique("enabled_rules", self.enabled_rules)
        _require_unique("tags", self.tags)
        _require_unique("expected_verifiers", self.expected_verifiers)
        return self


class CorpusManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["rewrite_task_corpus"] = "rewrite_task_corpus"
    corpus_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    corpus_version: str = Field(min_length=1)
    dialect: Literal["duckdb"] = "duckdb"
    fixtures: tuple[CorpusFixture, ...] = Field(min_length=1)
    tasks: tuple[CorpusTaskDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> CorpusManifest:
        fixture_ids = tuple(fixture.fixture_id for fixture in self.fixtures)
        task_ids = tuple(task.task_id for task in self.tasks)
        _require_unique("fixture IDs", fixture_ids)
        _require_unique("task IDs", task_ids)

        known_fixtures = set(fixture_ids)
        missing = sorted(
            {
                task.fixture_id
                for task in self.tasks
                if task.fixture_id not in known_fixtures
            }
        )
        if missing:
            raise ValueError(f"Tasks reference unknown fixtures: {', '.join(missing)}.")
        return self


class LoadedCorpusTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    definition: CorpusTaskDefinition
    environment_task: EnvironmentTask
    fixture: CorpusFixture
    query_path: Path
    constraints_path: Path
    fingerprint: str


class LoadedTaskCorpus(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest: CorpusManifest
    root: Path
    manifest_path: Path
    tasks: tuple[LoadedCorpusTask, ...]
    fingerprint: str

    def task(self, task_id: str) -> LoadedCorpusTask:
        for task in self.tasks:
            if task.definition.task_id == task_id:
                return task
        raise KeyError(f"Unknown corpus task: {task_id}.")


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"Duplicate {label}: {', '.join(duplicates)}.")
