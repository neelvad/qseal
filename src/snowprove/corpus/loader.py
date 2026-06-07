from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from snowprove.cache import content_hash
from snowprove.constraints.loader import load_constraint_catalog
from snowprove.corpus.model import (
    CorpusManifest,
    CorpusTaskDefinition,
    LoadedCorpusTask,
    LoadedTaskCorpus,
)
from snowprove.environment import EnvironmentTask
from snowprove.rewrites.registry import rule_names


def load_task_corpus(manifest_path: Path) -> LoadedTaskCorpus:
    manifest_path = manifest_path.resolve()
    payload: dict[str, Any] = yaml.safe_load(manifest_path.read_text()) or {}
    manifest = CorpusManifest.model_validate(payload)
    root = manifest_path.parent
    fixtures = {fixture.fixture_id: fixture for fixture in manifest.fixtures}
    known_rules = set(rule_names())
    loaded_tasks = []
    definitions = (*manifest.tasks, *_expand_task_families(manifest))
    task_ids = tuple(definition.task_id for definition in definitions)
    duplicates = sorted(
        {task_id for task_id in task_ids if task_ids.count(task_id) > 1}
    )
    if duplicates:
        raise ValueError(
            f"Expanded corpus contains duplicate task IDs: {', '.join(duplicates)}."
        )

    for definition in definitions:
        unknown_rules = sorted(set(definition.enabled_rules) - known_rules)
        if unknown_rules:
            raise ValueError(
                f"Task {definition.task_id} references unknown rewrite rules: "
                f"{', '.join(unknown_rules)}."
            )

        query_path = _resolve_corpus_path(
            root,
            definition.query_path,
            task_id=definition.task_id,
            field_name="query_path",
        )
        constraints_path = _resolve_corpus_path(
            root,
            definition.constraints_path,
            task_id=definition.task_id,
            field_name="constraints_path",
        )
        sql = query_path.read_text().strip()
        if not sql:
            raise ValueError(f"Task {definition.task_id} has an empty SQL query.")
        constraints = load_constraint_catalog(constraints_path)
        fixture = fixtures[definition.fixture_id]
        metadata = {
            "corpus_id": manifest.corpus_id,
            "corpus_version": manifest.corpus_version,
            "fixture_id": fixture.fixture_id,
            "tags": list(definition.tags),
        }
        if definition.family_id is not None:
            metadata["family_id"] = definition.family_id
        if definition.variant_id is not None:
            metadata["variant_id"] = definition.variant_id
        environment_task = EnvironmentTask(
            task_id=definition.task_id,
            sql=sql,
            constraints=constraints,
            dialect=manifest.dialect,
            max_steps=definition.max_steps,
            metadata=metadata,
        )
        fingerprint = content_hash(
            {
                "definition": definition.model_dump(mode="json"),
                "sql": sql,
                "constraints": constraints.model_dump(mode="json"),
                "fixture": fixture.model_dump(mode="json"),
                "dialect": manifest.dialect,
            }
        )
        loaded_tasks.append(
            LoadedCorpusTask(
                definition=definition,
                environment_task=environment_task,
                fixture=fixture,
                query_path=query_path,
                constraints_path=constraints_path,
                fingerprint=fingerprint,
            )
        )

    corpus_fingerprint = content_hash(
        {
            "manifest": manifest.model_dump(mode="json"),
            "tasks": [
                {
                    "task_id": task.definition.task_id,
                    "fingerprint": task.fingerprint,
                }
                for task in loaded_tasks
            ],
        }
    )
    return LoadedTaskCorpus(
        manifest=manifest,
        root=root,
        manifest_path=manifest_path,
        tasks=tuple(loaded_tasks),
        fingerprint=corpus_fingerprint,
    )


def _expand_task_families(
    manifest: CorpusManifest,
) -> tuple[CorpusTaskDefinition, ...]:
    definitions = []
    for family in manifest.task_families:
        for variant in family.variants:
            for fixture_id in family.fixture_ids:
                definitions.append(
                    CorpusTaskDefinition(
                        task_id=(
                            f"{family.family_id}-{variant.variant_id}-{fixture_id}"
                        ),
                        query_path=variant.query_path,
                        constraints_path=family.constraints_path,
                        fixture_id=fixture_id,
                        max_steps=family.max_steps,
                        enabled_rules=family.enabled_rules,
                        tags=tuple(
                            dict.fromkeys(
                                (
                                    *family.tags,
                                    *variant.tags,
                                    f"fixture:{fixture_id}",
                                    "generated",
                                )
                            )
                        ),
                        expected_verifiers=family.expected_verifiers,
                        family_id=family.family_id,
                        variant_id=variant.variant_id,
                    )
                )
    return tuple(definitions)


def _resolve_corpus_path(
    root: Path,
    relative_path: str,
    *,
    task_id: str,
    field_name: str,
) -> Path:
    requested = Path(relative_path)
    if requested.is_absolute():
        raise ValueError(f"Task {task_id} {field_name} must be relative.")

    resolved = (root / requested).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Task {task_id} {field_name} escapes the corpus directory.")
    if not resolved.is_file():
        raise ValueError(f"Task {task_id} {field_name} does not exist: {relative_path}.")
    return resolved
