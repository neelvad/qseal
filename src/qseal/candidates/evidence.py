from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from qseal.candidates.benchmarking import benchmark_pair
from qseal.constraints.model import ConstraintCatalog
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.model import VerificationResult


class CandidateEvidenceRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_path: str
    candidate_metadata: dict[str, Any] = Field(default_factory=dict)
    verification: VerificationResult
    proven: bool
    benchmarked: bool
    benchmark_skip_reason: str | None = None
    benchmark: dict[str, Any] | None = None
    recommendation: str


class CandidateEvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    artifact_type: str = "candidate_evidence"
    dialect: str
    benchmark_engine: str = "duckdb"
    benchmark_data: str = "synthetic"
    original_path: str
    schema_path: str
    schema_format: str
    rows: int
    warmups: int
    repetitions: int
    benchmark_timeout_seconds: float
    candidate_count: int
    proven_count: int
    benchmarked_count: int
    verification_counts: dict[str, int]
    benchmark_outcomes: dict[str, int]
    results: tuple[CandidateEvidenceRow, ...]


def build_candidate_evidence(
    original_path: Path,
    candidate_paths: Sequence[Path],
    verifications: Sequence[VerificationResult],
    constraints: ConstraintCatalog,
    *,
    schema_path: Path,
    schema_format: str,
    dialect: str,
    rows: int,
    warmups: int,
    repetitions: int,
    benchmark_timeout_seconds: float,
    candidate_metadata: Mapping[str, dict[str, Any]] | None = None,
) -> CandidateEvidenceReport:
    if len(candidate_paths) != len(verifications):
        raise ValueError("candidate_paths and verifications must have the same length.")
    if rows < 1:
        raise ValueError("rows must be one or greater.")
    if warmups < 0:
        raise ValueError("warmups must be zero or greater.")
    if repetitions < 1:
        raise ValueError("repetitions must be one or greater.")
    if benchmark_timeout_seconds <= 0:
        raise ValueError("benchmark_timeout_seconds must be greater than zero.")

    metadata = candidate_metadata or {}
    original_sql = original_path.read_text()
    result_rows = []
    for candidate_path, verification in zip(candidate_paths, verifications, strict=True):
        candidate_sql = candidate_path.read_text()
        proven = verification.status == VerificationStatus.PROVEN_EQUIVALENT
        benchmark = None
        skip_reason = None
        if proven:
            benchmark = benchmark_pair(
                original_sql,
                candidate_sql,
                constraints,
                dialect=dialect,
                scale=rows,
                warmups=warmups,
                repetitions=repetitions,
                timeout=benchmark_timeout_seconds,
            )
        else:
            skip_reason = f"verification status {verification.status.value}"
        result_rows.append(
            CandidateEvidenceRow(
                candidate_path=str(candidate_path),
                candidate_metadata=dict(metadata.get(str(candidate_path), {})),
                verification=verification,
                proven=proven,
                benchmarked=benchmark is not None,
                benchmark_skip_reason=skip_reason,
                benchmark=benchmark,
                recommendation=_recommendation(verification, benchmark),
            )
        )

    verification_counts = Counter(row.verification.status.value for row in result_rows)
    benchmark_outcomes = Counter(
        row.benchmark.get("outcome", "unknown")
        for row in result_rows
        if row.benchmark is not None
    )
    return CandidateEvidenceReport(
        dialect=dialect,
        original_path=str(original_path),
        schema_path=str(schema_path),
        schema_format=schema_format,
        rows=rows,
        warmups=warmups,
        repetitions=repetitions,
        benchmark_timeout_seconds=benchmark_timeout_seconds,
        candidate_count=len(result_rows),
        proven_count=sum(row.proven for row in result_rows),
        benchmarked_count=sum(row.benchmarked for row in result_rows),
        verification_counts=dict(sorted(verification_counts.items())),
        benchmark_outcomes=dict(sorted(benchmark_outcomes.items())),
        results=tuple(result_rows),
    )


def _recommendation(
    verification: VerificationResult,
    benchmark: dict[str, Any] | None,
) -> str:
    if verification.status != VerificationStatus.PROVEN_EQUIVALENT:
        return "do_not_apply_unproven"
    if benchmark is None:
        return "safe_but_not_benchmarked"
    outcome = benchmark.get("outcome")
    if outcome == "faster":
        return "consider_applying"
    if outcome == "neutral":
        return "safe_but_no_clear_speedup"
    if outcome == "slower":
        return "safe_but_slower"
    if outcome == "suspect":
        return "recheck_benchmark_premises"
    return "safe_but_benchmark_failed"
