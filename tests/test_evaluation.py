import json
from pathlib import Path

from qseal.evaluation import (
    comparison_payload,
    discover_project_reports,
    load_project_report,
    render_comparison,
)


def _write_report(
    path: Path,
    *,
    models: int,
    results: int,
    proven: int,
    statuses: dict[str, int],
    reasons: dict[str, int],
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "artifact_type": "dbt_scan",
                "model_count": models,
                "results": [],
                "summary": {
                    "model_count": models,
                    "result_count": results,
                    "proven_finding_count": proven,
                    "status_counts": statuses,
                    "reason_counts": reasons,
                },
            }
        )
    )


def test_compares_real_project_reports(tmp_path: Path) -> None:
    raw = tmp_path / "run-a" / "project-a" / "raw-report.json"
    compiled = tmp_path / "run-b" / "project-b" / "compiled-report.json"
    _write_report(
        raw,
        models=5,
        results=2,
        proven=1,
        statuses={"PROVEN_EQUIVALENT": 1, "UNSUPPORTED": 1},
        reasons={"Jinja": 1},
    )
    _write_report(
        compiled,
        models=10,
        results=1,
        proven=0,
        statuses={"UNKNOWN": 1},
        reasons={"Missing uniqueness": 1},
    )

    paths = discover_project_reports([tmp_path])
    reports = tuple(load_project_report(path) for path in paths)
    payload = comparison_payload(reports)

    assert paths == (raw, compiled)
    assert payload["report_count"] == 2
    assert payload["totals"] == {
        "model_count": 15,
        "result_count": 3,
        "silent_model_count": 12,
        "proven_count": 1,
        "result_rate": 0.2,
        "proven_per_model": 1 / 15,
        "status_counts": {
            "PROVEN_EQUIVALENT": 1,
            "UNKNOWN": 1,
            "UNSUPPORTED": 1,
        },
        "reason_counts": {
            "Jinja": 1,
            "Missing uniqueness": 1,
        },
    }

    rendered = render_comparison(reports)
    assert "project-a" in rendered
    assert "project-b" in rendered
    assert "15 models, 3 results, 12 silent, 1 proven" in rendered
    assert "0.067 proven/model" in rendered


def test_rejects_non_dbt_scan_artifact(tmp_path: Path) -> None:
    report = tmp_path / "raw-report.json"
    report.write_text(json.dumps({"artifact_type": "verification"}))

    try:
        load_project_report(report)
    except ValueError as error:
        assert "Not a dbt_scan artifact" in str(error)
    else:
        raise AssertionError("Expected load_project_report to reject the artifact.")
