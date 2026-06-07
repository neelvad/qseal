from __future__ import annotations

import json
import platform
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import duckdb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from snowprove.cache import JsonFileCache
from snowprove.corpus.model import LoadedCorpusTask, LoadedTaskCorpus
from snowprove.environment import (
    CachedPerformanceEvaluator,
    CachedVerifier,
    DuckDbPerformanceEvaluator,
    RewriteEnvironment,
)
from snowprove.environment.core import PerformanceEvaluator
from snowprove.fixtures import DuckDbFixtureManifest, create_duckdb_fixture
from snowprove.rewrites.registry import select_rules
from snowprove.search import (
    SearchResult,
    beam_search,
    exhaustive_search,
    fixed_order_search,
    greedy_search,
    random_search,
)
from snowprove.verifier.backends import BuiltinVerifierBackend
from snowprove.verifier.backends.base import VerifierBackend

SearchStrategy = Literal["fixed_order", "random", "greedy", "beam", "exhaustive"]
VerifierFactory = Callable[[LoadedCorpusTask], VerifierBackend]


class PerformanceEvaluatorFactory(Protocol):
    def __call__(
        self,
        task: LoadedCorpusTask,
        database_path: Path,
        fixture_manifest: DuckDbFixtureManifest,
    ) -> PerformanceEvaluator:
        pass


class CorpusRunConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategies: tuple[SearchStrategy, ...] = (
        "fixed_order",
        "random",
        "greedy",
        "beam",
        "exhaustive",
    )
    task_ids: tuple[str, ...] = Field(default_factory=tuple)
    random_seed: int = 42
    beam_width: int = Field(default=4, ge=1)
    max_nodes: int = Field(default=100, ge=1)
    warmups: int = Field(default=1, ge=0)
    repetitions: int = Field(default=3, ge=1)
    timeout_seconds: float = Field(default=30.0, gt=0)
    threads: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_unique_values(self) -> CorpusRunConfig:
        _require_unique("strategies", self.strategies)
        _require_unique("task IDs", self.task_ids)
        return self


class OracleCallMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    requests: int
    cache_hits: int
    cache_misses: int


class StrategyRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: SearchStrategy
    status: Literal["COMPLETED", "ERROR"]
    elapsed_seconds: float
    verification_calls: OracleCallMetrics
    benchmark_calls: OracleCallMetrics
    search_result: SearchResult | None = None
    error: str | None = None


class CorpusTaskRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    task_fingerprint: str
    fixture_id: str
    enabled_rules: tuple[str, ...]
    tags: tuple[str, ...]
    results: tuple[StrategyRunResult, ...]


class CorpusRunEnvironment(BaseModel):
    model_config = ConfigDict(frozen=True)

    python_version: str
    duckdb_version: str
    platform: str


class StrategyRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: SearchStrategy
    run_count: int
    completed_count: int
    error_count: int
    mean_cumulative_reward: float | None
    total_explored_nodes: int
    verification_cache_misses: int
    benchmark_cache_misses: int
    total_elapsed_seconds: float


class CorpusRunReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["corpus_search_run"] = "corpus_search_run"
    generated_at: datetime
    corpus_id: str
    corpus_version: str
    corpus_fingerprint: str
    config: CorpusRunConfig
    environment: CorpusRunEnvironment
    tasks: tuple[CorpusTaskRun, ...]
    strategy_summaries: tuple[StrategyRunSummary, ...]


def run_task_corpus(
    corpus: LoadedTaskCorpus,
    output_dir: Path,
    *,
    config: CorpusRunConfig | None = None,
    verifier_factory: VerifierFactory | None = None,
    performance_evaluator_factory: PerformanceEvaluatorFactory | None = None,
    report_path: Path | None = None,
) -> CorpusRunReport:
    config = config or CorpusRunConfig()
    verifier_factory = verifier_factory or _builtin_verifier
    performance_evaluator_factory = (
        performance_evaluator_factory or _duckdb_evaluator(config)
    )
    selected_tasks = _select_tasks(corpus, config.task_ids)
    selected_fixture_ids = {task.fixture.fixture_id for task in selected_tasks}
    fixture_manifests = _ensure_fixtures(
        corpus,
        output_dir / "fixtures",
        selected_fixture_ids,
    )
    cache = JsonFileCache(output_dir / "cache")
    task_runs = []

    for task in selected_tasks:
        database_path = output_dir / "fixtures" / f"{task.fixture.fixture_id}.duckdb"
        fixture_manifest = fixture_manifests[task.fixture.fixture_id]
        strategy_results = tuple(
            _run_strategy(
                corpus,
                task,
                strategy,
                config,
                cache,
                database_path,
                fixture_manifest,
                verifier_factory,
                performance_evaluator_factory,
            )
            for strategy in config.strategies
        )
        task_runs.append(
            CorpusTaskRun(
                task_id=task.definition.task_id,
                task_fingerprint=task.fingerprint,
                fixture_id=task.fixture.fixture_id,
                enabled_rules=task.definition.enabled_rules,
                tags=task.definition.tags,
                results=strategy_results,
            )
        )

    report = CorpusRunReport(
        generated_at=datetime.now(UTC),
        corpus_id=corpus.manifest.corpus_id,
        corpus_version=corpus.manifest.corpus_version,
        corpus_fingerprint=corpus.fingerprint,
        config=config,
        environment=CorpusRunEnvironment(
            python_version=platform.python_version(),
            duckdb_version=duckdb.__version__,
            platform=platform.platform(),
        ),
        tasks=tuple(task_runs),
        strategy_summaries=_summarize_strategies(
            tuple(task_runs),
            config.strategies,
        ),
    )
    if report_path is not None:
        _write_report(report, report_path)
    return report


def _run_strategy(
    corpus: LoadedTaskCorpus,
    task: LoadedCorpusTask,
    strategy: SearchStrategy,
    config: CorpusRunConfig,
    cache: JsonFileCache,
    database_path: Path,
    fixture_manifest: DuckDbFixtureManifest,
    verifier_factory: VerifierFactory,
    performance_evaluator_factory: PerformanceEvaluatorFactory,
) -> StrategyRunResult:
    namespace = (
        f"corpus:{corpus.fingerprint}:task:{task.fingerprint}:strategy:{strategy}"
    )
    context = {
        "corpus_fingerprint": corpus.fingerprint,
        "task_fingerprint": task.fingerprint,
        "fixture_id": task.fixture.fixture_id,
        "fixture_tables": {
            name: summary.fingerprint
            for name, summary in fixture_manifest.tables.items()
        },
    }
    verifier = CachedVerifier(
        verifier_factory(task),
        cache,
        namespace=namespace,
        context=context,
    )
    evaluator = CachedPerformanceEvaluator(
        performance_evaluator_factory(task, database_path, fixture_manifest),
        cache,
        namespace=namespace,
        context=context,
    )
    rules = select_rules(task.definition.enabled_rules)

    def environment_factory() -> RewriteEnvironment:
        return RewriteEnvironment(
            verifier=verifier,
            performance_evaluator=evaluator,
            rules=rules,
        )

    started = time.perf_counter()
    try:
        result = _search(
            strategy,
            task,
            environment_factory,
            config,
        )
    except Exception as error:
        return StrategyRunResult(
            strategy=strategy,
            status="ERROR",
            elapsed_seconds=time.perf_counter() - started,
            verification_calls=_metrics(verifier.hits, verifier.misses),
            benchmark_calls=_metrics(evaluator.hits, evaluator.misses),
            error=f"{type(error).__name__}: {error}",
        )

    return StrategyRunResult(
        strategy=strategy,
        status="COMPLETED",
        elapsed_seconds=time.perf_counter() - started,
        verification_calls=_metrics(verifier.hits, verifier.misses),
        benchmark_calls=_metrics(evaluator.hits, evaluator.misses),
        search_result=result,
    )


def _search(
    strategy: SearchStrategy,
    task: LoadedCorpusTask,
    environment_factory: Callable[[], RewriteEnvironment],
    config: CorpusRunConfig,
) -> SearchResult:
    if strategy == "fixed_order":
        return fixed_order_search(task.environment_task, environment_factory)
    if strategy == "random":
        return random_search(
            task.environment_task,
            environment_factory,
            seed=config.random_seed,
        )
    if strategy == "greedy":
        return greedy_search(task.environment_task, environment_factory)
    if strategy == "beam":
        return beam_search(
            task.environment_task,
            environment_factory,
            beam_width=config.beam_width,
        )
    return exhaustive_search(
        task.environment_task,
        environment_factory,
        max_nodes=config.max_nodes,
    )


def _ensure_fixtures(
    corpus: LoadedTaskCorpus,
    output_dir: Path,
    fixture_ids: set[str],
) -> dict[str, DuckDbFixtureManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests = {}
    for fixture in corpus.manifest.fixtures:
        if fixture.fixture_id not in fixture_ids:
            continue
        database_path = output_dir / f"{fixture.fixture_id}.duckdb"
        manifest_path = output_dir / f"{fixture.fixture_id}.manifest.json"
        if database_path.is_file() and manifest_path.is_file():
            manifest = DuckDbFixtureManifest.model_validate_json(
                manifest_path.read_text()
            )
            if manifest.spec != fixture.spec:
                raise ValueError(
                    f"Existing fixture spec does not match corpus: {fixture.fixture_id}."
                )
        elif database_path.exists() or manifest_path.exists():
            raise ValueError(
                f"Incomplete fixture outputs for {fixture.fixture_id}; "
                "remove both files and rerun."
            )
        else:
            manifest = create_duckdb_fixture(
                database_path,
                spec=fixture.spec,
                manifest_path=manifest_path,
            )
        manifests[fixture.fixture_id] = manifest
    return manifests


def _select_tasks(
    corpus: LoadedTaskCorpus,
    task_ids: tuple[str, ...],
) -> tuple[LoadedCorpusTask, ...]:
    if not task_ids:
        return corpus.tasks
    unknown = sorted(set(task_ids) - {task.definition.task_id for task in corpus.tasks})
    if unknown:
        raise ValueError(f"Unknown corpus tasks: {', '.join(unknown)}.")
    requested = set(task_ids)
    return tuple(
        task for task in corpus.tasks if task.definition.task_id in requested
    )


def _duckdb_evaluator(config: CorpusRunConfig) -> PerformanceEvaluatorFactory:
    def create(
        task: LoadedCorpusTask,
        database_path: Path,
        fixture_manifest: DuckDbFixtureManifest,
    ) -> PerformanceEvaluator:
        del task
        fixture_fingerprint = "|".join(
            f"{name}:{summary.fingerprint}"
            for name, summary in sorted(fixture_manifest.tables.items())
        )
        return DuckDbPerformanceEvaluator(
            database_path=database_path,
            warmups=config.warmups,
            repetitions=config.repetitions,
            timeout_seconds=config.timeout_seconds,
            threads=config.threads,
            fixture_fingerprint=fixture_fingerprint,
        )

    return create


def _builtin_verifier(task: LoadedCorpusTask) -> VerifierBackend:
    del task
    return BuiltinVerifierBackend()


def _metrics(hits: int, misses: int) -> OracleCallMetrics:
    return OracleCallMetrics(
        requests=hits + misses,
        cache_hits=hits,
        cache_misses=misses,
    )


def _write_report(report: CorpusRunReport, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"{json.dumps(report.model_dump(mode='json'), indent=2, sort_keys=True)}\n"
    )


def _summarize_strategies(
    tasks: tuple[CorpusTaskRun, ...],
    strategies: tuple[SearchStrategy, ...],
) -> tuple[StrategyRunSummary, ...]:
    summaries = []
    for strategy in strategies:
        runs = [
            result
            for task in tasks
            for result in task.results
            if result.strategy == strategy
        ]
        completed = [
            result
            for result in runs
            if result.status == "COMPLETED" and result.search_result is not None
        ]
        rewards = [
            result.search_result.cumulative_reward
            for result in completed
            if result.search_result is not None
        ]
        summaries.append(
            StrategyRunSummary(
                strategy=strategy,
                run_count=len(runs),
                completed_count=len(completed),
                error_count=len(runs) - len(completed),
                mean_cumulative_reward=(
                    sum(rewards) / len(rewards) if rewards else None
                ),
                total_explored_nodes=sum(
                    result.search_result.explored_nodes
                    for result in completed
                    if result.search_result is not None
                ),
                verification_cache_misses=sum(
                    result.verification_calls.cache_misses for result in runs
                ),
                benchmark_cache_misses=sum(
                    result.benchmark_calls.cache_misses for result in runs
                ),
                total_elapsed_seconds=sum(result.elapsed_seconds for result in runs),
            )
        )
    return tuple(summaries)


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"Duplicate {label}: {', '.join(duplicates)}.")
