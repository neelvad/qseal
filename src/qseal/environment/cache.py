from __future__ import annotations

from typing import Any

from qseal.benchmark.model import (
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
    QueryBenchmarkResult,
)
from qseal.cache import JsonFileCache, content_hash
from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.environment.core import PerformanceEvaluator
from qseal.verifier.backends.base import VerifierBackend
from qseal.verifier.model import VerificationResult


class CachedVerifier:
    def __init__(
        self,
        verifier: VerifierBackend,
        cache: JsonFileCache,
        *,
        namespace: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.verifier = verifier
        self.cache = cache
        self.namespace = namespace
        self.context = context or {}
        self.name = f"cached:{verifier.name}"
        self.hits = 0
        self.misses = 0

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
        dialect: SqlDialect = DEFAULT_DIALECT,
    ) -> VerificationResult:
        key = content_hash(
            {
                "kind": "verification",
                "namespace": self.namespace,
                "backend": self.verifier.name,
                "context": self.context,
                "dialect": dialect,
                "original_sql": original_sql.strip(),
                "rewritten_sql": rewritten_sql.strip(),
                "constraints": constraints.model_dump(mode="json"),
            }
        )
        cached = self.cache.load("verification", key, VerificationResult)
        if cached is not None:
            self.hits += 1
            return VerificationResult.model_validate(cached)

        self.misses += 1
        result = self.verifier.verify(
            original_sql,
            rewritten_sql,
            constraints,
            dialect=dialect,
        )
        self.cache.store("verification", key, result)
        return result


class CachedPerformanceEvaluator:
    def __init__(
        self,
        evaluator: PerformanceEvaluator,
        cache: JsonFileCache,
        *,
        namespace: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.evaluator = evaluator
        self.cache = cache
        self.namespace = namespace
        self.context = context or {}
        self.supports_query_benchmark = getattr(
            evaluator,
            "supports_query_benchmark",
            False,
        )
        self.supports_interleaved_query_benchmark = getattr(
            evaluator,
            "supports_interleaved_query_benchmark",
            False,
        )
        self.hits = 0
        self.misses = 0

    def evaluate_query(self, sql: str) -> QueryBenchmarkResult:
        if not self.supports_query_benchmark:
            raise RuntimeError("Wrapped evaluator does not support query benchmarks.")
        key = self._query_key(sql)
        cached = self.cache.load("query_benchmark", key, QueryBenchmarkResult)
        if cached is not None:
            self.hits += 1
            return QueryBenchmarkResult.model_validate(cached)

        self.misses += 1
        result = self.evaluator.evaluate_query(sql)
        self.cache.store("query_benchmark", key, result)
        return result

    def evaluate_query_pair(
        self,
        original_sql: str,
        rewritten_sql: str,
    ) -> tuple[QueryBenchmarkResult, QueryBenchmarkResult]:
        if not self.supports_interleaved_query_benchmark:
            return (
                self.evaluate_query(original_sql),
                self.evaluate_query(rewritten_sql),
            )

        original_key = self._query_key(original_sql)
        rewritten_key = self._query_key(rewritten_sql)
        if original_key == rewritten_key:
            result = self.evaluate_query(original_sql)
            return result, result

        original = self.cache.load(
            "query_benchmark",
            original_key,
            QueryBenchmarkResult,
        )
        rewritten = self.cache.load(
            "query_benchmark",
            rewritten_key,
            QueryBenchmarkResult,
        )
        original_was_cached = original is not None
        rewritten_was_cached = rewritten is not None
        self.hits += int(original_was_cached) + int(rewritten_was_cached)
        self.misses += int(not original_was_cached) + int(not rewritten_was_cached)
        if original is not None and rewritten is not None:
            return (
                QueryBenchmarkResult.model_validate(original),
                QueryBenchmarkResult.model_validate(rewritten),
            )

        measured_original, measured_rewritten = self.evaluator.evaluate_query_pair(
            original_sql,
            rewritten_sql,
        )
        if original is not None:
            original = QueryBenchmarkResult.model_validate(original)
            rewritten = _normalize_query_result(
                measured_rewritten,
                measured_anchor=measured_original,
                cached_anchor=original,
            )
        elif rewritten is not None:
            rewritten = QueryBenchmarkResult.model_validate(rewritten)
            original = _normalize_query_result(
                measured_original,
                measured_anchor=measured_rewritten,
                cached_anchor=rewritten,
            )
        else:
            original = measured_original
            rewritten = measured_rewritten

        if not original_was_cached:
            self.cache.store("query_benchmark", original_key, original)
        if not rewritten_was_cached:
            self.cache.store("query_benchmark", rewritten_key, rewritten)
        return original, rewritten

    def evaluate(self, original_sql: str, rewritten_sql: str) -> BenchmarkResult:
        evaluator_context = (
            self.evaluator.cache_context()
            if hasattr(self.evaluator, "cache_context")
            else {}
        )
        key = content_hash(
            {
                "kind": "benchmark",
                "namespace": self.namespace,
                "context": self.context,
                "evaluator": evaluator_context,
                "original_sql": original_sql.strip(),
                "rewritten_sql": rewritten_sql.strip(),
            }
        )
        cached = self.cache.load("benchmark", key, BenchmarkResult)
        if cached is not None:
            self.hits += 1
            return BenchmarkResult.model_validate(cached)

        self.misses += 1
        result = self.evaluator.evaluate(original_sql, rewritten_sql)
        self.cache.store("benchmark", key, result)
        return result

    def _query_key(self, sql: str) -> str:
        evaluator_context = (
            self.evaluator.cache_context()
            if hasattr(self.evaluator, "cache_context")
            else {}
        )
        return content_hash(
            {
                "kind": "query_benchmark",
                "namespace": self.namespace,
                "context": self.context,
                "evaluator": evaluator_context,
                "measurement_strategy": (
                    "interleaved-anchored-v1"
                    if self.supports_interleaved_query_benchmark
                    else "independent-v1"
                ),
                "sql": sql.strip(),
            }
        )


def _normalize_query_result(
    result: QueryBenchmarkResult,
    *,
    measured_anchor: QueryBenchmarkResult,
    cached_anchor: QueryBenchmarkResult,
) -> QueryBenchmarkResult:
    measured_median = measured_anchor.query.median_ms
    cached_median = cached_anchor.query.median_ms
    if (
        result.status != BenchmarkStatus.COMPLETED
        or measured_anchor.status != BenchmarkStatus.COMPLETED
        or cached_anchor.status != BenchmarkStatus.COMPLETED
        or measured_median is None
        or measured_median <= 0
        or cached_median is None
        or cached_median <= 0
    ):
        return result

    factor = cached_median / measured_median
    query = result.query
    timing_confident = (
        result.timing_confident
        and measured_anchor.timing_confident
        and cached_anchor.timing_confident
    )
    confidence_reason = (
        result.confidence_reason
        or measured_anchor.confidence_reason
        or cached_anchor.confidence_reason
    )
    normalized_query = QueryBenchmark(
        status=query.status,
        sql=query.sql,
        timings_ms=tuple(value * factor for value in query.timings_ms),
        batch_timings_ms=tuple(value * factor for value in query.batch_timings_ms),
        executions_per_sample=query.executions_per_sample,
        median_ms=_scale(query.median_ms, factor),
        median_absolute_deviation_ms=_scale(
            query.median_absolute_deviation_ms,
            factor,
        ),
        min_ms=_scale(query.min_ms, factor),
        max_ms=_scale(query.max_ms, factor),
        row_count=query.row_count,
        explain=query.explain,
        error=query.error,
    )
    return result.model_copy(
        update={
            "query": normalized_query,
            "timing_confident": timing_confident,
            "confidence_reason": confidence_reason,
            "inputs": {
                **result.inputs,
                "measurement_mode": "interleaved_anchored",
                "anchor_sql": cached_anchor.query.sql,
                "normalization_factor": repr(factor),
            },
        }
    )


def _scale(value: float | None, factor: float) -> float | None:
    return value * factor if value is not None else None
