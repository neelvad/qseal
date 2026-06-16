# Thin shim for `qseal llm benchmark`; kept for the Modal benchmark app.
# All logic lives in qseal.candidates.benchmarking.
import argparse
import json
import sys
from pathlib import Path

from qseal.candidates.benchmarking import benchmark_proven


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_path", type=Path)
    parser.add_argument("bundles_dir", type=Path)
    parser.add_argument("--report-file", type=Path, required=True)
    parser.add_argument("--rows", default="100000,1000000")
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    result = benchmark_proven(
        args.report_path,
        args.bundles_dir,
        rows=[int(float(scale)) for scale in args.rows.split(",")],
        dialect=args.dialect,
        warmups=args.warmups,
        repetitions=args.repetitions,
        timeout=args.timeout,
        only=set(args.only.split(",")) if args.only else None,
        report_file=args.report_file,
        log=lambda message: print(message, file=sys.stderr),
    )
    print(json.dumps({"measurements": result["measurement_count"], **result["outcomes"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
