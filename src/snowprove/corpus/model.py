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
    family_id: str | None = None
    variant_id: str | None = None

    @model_validator(mode="after")
    def validate_unique_values(self) -> CorpusTaskDefinition:
        _require_unique("enabled_rules", self.enabled_rules)
        _require_unique("tags", self.tags)
        _require_unique("expected_verifiers", self.expected_verifiers)
        return self


class CorpusTaskVariant(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    query_path: str = Field(min_length=1)
    tags: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_tags(self) -> CorpusTaskVariant:
        _require_unique("variant tags", self.tags)
        return self


class CorpusTaskFamily(BaseModel):
    model_config = ConfigDict(frozen=True)

    family_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    constraints_path: str = Field(min_length=1)
    fixture_ids: tuple[str, ...] = Field(min_length=1)
    variants: tuple[CorpusTaskVariant, ...] = Field(min_length=1)
    max_steps: int = Field(default=8, ge=1)
    enabled_rules: tuple[str, ...] = Field(min_length=1)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    expected_verifiers: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_values(self) -> CorpusTaskFamily:
        _require_unique("family fixture IDs", self.fixture_ids)
        _require_unique(
            "family variant IDs",
            tuple(variant.variant_id for variant in self.variants),
        )
        _require_unique("family enabled_rules", self.enabled_rules)
        _require_unique("family tags", self.tags)
        _require_unique("family expected_verifiers", self.expected_verifiers)
        return self


class CorpusManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["rewrite_task_corpus"] = "rewrite_task_corpus"
    corpus_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    corpus_version: str = Field(min_length=1)
    dialect: Literal["duckdb"] = "duckdb"
    fixtures: tuple[CorpusFixture, ...] = Field(min_length=1)
    tasks: tuple[CorpusTaskDefinition, ...] = Field(default_factory=tuple)
    task_families: tuple[CorpusTaskFamily, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_references(self) -> CorpusManifest:
        fixture_ids = tuple(fixture.fixture_id for fixture in self.fixtures)
        task_ids = tuple(task.task_id for task in self.tasks)
        family_ids = tuple(family.family_id for family in self.task_families)
        _require_unique("fixture IDs", fixture_ids)
        _require_unique("task IDs", task_ids)
        _require_unique("task family IDs", family_ids)
        if not self.tasks and not self.task_families:
            raise ValueError("Corpus must define tasks or task_families.")

        known_fixtures = set(fixture_ids)
        missing_task_fixtures = {
            task.fixture_id
            for task in self.tasks
            if task.fixture_id not in known_fixtures
        }
        missing_family_fixtures = {
            fixture_id
            for family in self.task_families
            for fixture_id in family.fixture_ids
            if fixture_id not in known_fixtures
        }
        missing = sorted(
            {
                *missing_task_fixtures,
                *missing_family_fixtures,
            }
        )
        if missing:
            raise ValueError(
                f"Tasks or families reference unknown fixtures: {', '.join(missing)}."
            )
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
