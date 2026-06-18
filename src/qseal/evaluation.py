from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProjectReportSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    project: str
    scan_kind: str
    report_path: Path
    model_count: int
    result_count: int
    proven_count: int
    status_counts: dict[str, int]
    reason_counts: dict[str, int]

    @property
    def silent_model_count(self) -> int:
        return max(self.model_count - self.result_count, 0)

    @property
    def result_rate(self) -> float:
        return _rate(self.result_count, self.model_count)

    @property
    def proven_per_model(self) -> float:
        return _rate(self.proven_count, self.model_count)


def discover_project_reports(paths: list[Path]) -> tuple[Path, ...]:
    reports = set()
    for path in paths:
        if path.is_file():
            reports.add(path)
            continue
        reports.update(path.rglob("raw-report.json"))
        reports.update(path.rglob("compiled-report.json"))
    return tuple(sorted(reports))


def load_project_report(path: Path) -> ProjectReportSummary:
    payload: dict[str, Any] = json.loads(path.read_text())
    if payload.get("artifact_type") != "dbt_scan":
        raise ValueError(f"Not a dbt_scan artifact: {path}")

    summary = payload.get("summary") or {}
    return ProjectReportSummary(
        project=path.parent.name,
        scan_kind=_scan_kind(path),
        report_path=path,
        model_count=int(summary.get("model_count", payload.get("model_count", 0))),
        result_count=int(summary.get("result_count", len(payload.get("results") or []))),
        proven_count=int(summary.get("proven_finding_count", 0)),
        status_counts={
            str(status): int(count)
            for status, count in (summary.get("status_counts") or {}).items()
        },
        reason_counts={
            str(reason): int(count)
            for reason, count in (summary.get("reason_counts") or {}).items()
        },
    )


def comparison_payload(reports: tuple[ProjectReportSummary, ...]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for report in reports:
        statuses.update(report.status_counts)
        reasons.update(report.reason_counts)

    return {
        "artifact_type": "real_project_comparison",
        "schema_version": 1,
        "report_count": len(reports),
        "reports": [
            {
                "project": report.project,
                "scan_kind": report.scan_kind,
                "report_path": str(report.report_path),
                "model_count": report.model_count,
                "result_count": report.result_count,
                "silent_model_count": report.silent_model_count,
                "proven_count": report.proven_count,
                "result_rate": report.result_rate,
                "proven_per_model": report.proven_per_model,
                "status_counts": report.status_counts,
                "reason_counts": report.reason_counts,
            }
            for report in reports
        ],
        "totals": {
            "model_count": sum(report.model_count for report in reports),
            "result_count": sum(report.result_count for report in reports),
            "silent_model_count": sum(report.silent_model_count for report in reports),
            "proven_count": sum(report.proven_count for report in reports),
            "result_rate": _rate(
                sum(report.result_count for report in reports),
                sum(report.model_count for report in reports),
            ),
            "proven_per_model": _rate(
                sum(report.proven_count for report in reports),
                sum(report.model_count for report in reports),
            ),
            "status_counts": dict(sorted(statuses.items())),
            "reason_counts": dict(
                sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
            ),
        },
    }


def render_comparison(reports: tuple[ProjectReportSummary, ...]) -> str:
    header = (
        f"{'PROJECT':<34} {'SCAN':<8} {'MODELS':>6} {'RESULTS':>7} "
        f"{'SILENT':>6} {'PROVEN':>6} {'HIT/M':>7} {'UNKNOWN':>7} "
        f"{'UNSUPPORTED':>11}"
    )
    lines = [header, "-" * len(header)]
    for report in reports:
        lines.append(
            f"{report.project:<34} {report.scan_kind:<8} "
            f"{report.model_count:>6} {report.result_count:>7} "
            f"{report.silent_model_count:>6} {report.proven_count:>6} "
            f"{report.proven_per_model:>7.3f} "
            f"{report.status_counts.get('UNKNOWN', 0):>7} "
            f"{report.status_counts.get('UNSUPPORTED', 0):>11}"
        )

    payload = comparison_payload(reports)
    totals = payload["totals"]
    lines.extend(
        [
            "",
            (
                f"Totals: {totals['model_count']} models, "
                f"{totals['result_count']} results, "
                f"{totals['silent_model_count']} silent, "
                f"{totals['proven_count']} proven, "
                f"{totals['proven_per_model']:.3f} proven/model"
            ),
            "Top reasons:",
        ]
    )
    reason_counts = totals["reason_counts"]
    if reason_counts:
        lines.extend(f"  {count}x {reason}" for reason, count in reason_counts.items())
    else:
        lines.append("  none")
    return "\n".join(lines)


def _scan_kind(path: Path) -> str:
    if path.name == "compiled-report.json":
        return "compiled"
    if path.name == "raw-report.json":
        return "raw"
    return "unknown"


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
