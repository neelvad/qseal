from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from difflib import unified_diff
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from qseal.candidates.benchmarking import benchmark_pair
from qseal.constraints.model import ConstraintCatalog
from qseal.report.guards import required_guarding_tests_for_assumptions
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
    review_section: str
    required_tests: tuple[str, ...] = Field(default_factory=tuple)
    review_diff: str | None = None


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
                review_section=_review_section(verification, benchmark),
                required_tests=required_guarding_tests_for_assumptions(
                    verification.assumptions
                ),
                review_diff=_review_diff(
                    original_path,
                    original_sql,
                    candidate_sql,
                )
                if proven
                else None,
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


def _review_section(
    verification: VerificationResult,
    benchmark: dict[str, Any] | None,
) -> str:
    recommendation = _recommendation(verification, benchmark)
    if recommendation == "consider_applying":
        return "safe_worth_considering"
    if recommendation in {"safe_but_no_clear_speedup", "safe_but_slower"}:
        return "safe_no_clear_speedup"
    if recommendation == "do_not_apply_unproven":
        return "rejected_unproven"
    return "needs_review"


def _review_diff(path: Path, original_sql: str, candidate_sql: str) -> str:
    return "".join(
        unified_diff(
            _lines(original_sql),
            _lines(candidate_sql),
            fromfile=str(path),
            tofile=str(path),
        )
    )


def _lines(sql: str) -> list[str]:
    return [f"{line}\n" for line in sql.strip().splitlines()]
