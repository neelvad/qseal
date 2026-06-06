#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from snowprove.evaluation import (
    comparison_payload,
    discover_project_reports,
    load_project_report,
    render_comparison,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Snowprove dbt scan reports across real projects."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Report JSON files or directories containing raw/compiled reports.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--scan-kind", choices=("all", "raw", "compiled"), default="all")
    args = parser.parse_args()

    report_paths = discover_project_reports(args.paths)
    if not report_paths:
        parser.error("no raw-report.json or compiled-report.json files found")

    discovered_reports = tuple(load_project_report(path) for path in report_paths)
    reports = tuple(
        report
        for report in discovered_reports
        if args.scan_kind == "all" or report.scan_kind == args.scan_kind
    )
    if not reports:
        parser.error(f"no {args.scan_kind} reports found")
    if args.format == "json":
        print(json.dumps(comparison_payload(reports), indent=2, sort_keys=True))
    else:
        print(render_comparison(reports))


if __name__ == "__main__":
    main()
