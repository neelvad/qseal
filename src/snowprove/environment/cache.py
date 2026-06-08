from __future__ import annotations

from typing import Any

from snowprove.benchmark.model import BenchmarkResult, QueryBenchmarkResult
from snowprove.cache import JsonFileCache, content_hash
from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.environment.core import PerformanceEvaluator
from snowprove.verifier.backends.base import VerifierBackend
from snowprove.verifier.model import VerificationResult


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
        self.hits = 0
        self.misses = 0

    def evaluate_query(self, sql: str) -> QueryBenchmarkResult:
        if not self.supports_query_benchmark:
            raise RuntimeError("Wrapped evaluator does not support query benchmarks.")
        evaluator_context = (
            self.evaluator.cache_context()
            if hasattr(self.evaluator, "cache_context")
            else {}
        )
        key = content_hash(
            {
                "kind": "query_benchmark",
                "namespace": self.namespace,
                "context": self.context,
                "evaluator": evaluator_context,
                "sql": sql.strip(),
            }
        )
        cached = self.cache.load("query_benchmark", key, QueryBenchmarkResult)
        if cached is not None:
            self.hits += 1
            return QueryBenchmarkResult.model_validate(cached)

        self.misses += 1
        result = self.evaluator.evaluate_query(sql)
        self.cache.store("query_benchmark", key, result)
        return result

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
