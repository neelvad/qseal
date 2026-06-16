# Thin shim for `qseal llm explain`; kept for existing docs/automation.
# All logic lives in qseal.candidates.explain. Requires SNOWFLAKE_* env.
import argparse
import json
import sys
from pathlib import Path

from qseal.candidates.explain import explain_proven


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_path", type=Path)
    parser.add_argument("bundles_dir", type=Path)
    parser.add_argument("--report-file", type=Path, required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    result = explain_proven(
        args.report_path,
        args.bundles_dir,
        dialect=args.dialect,
        only=set(args.only.split(",")) if args.only else None,
        report_file=args.report_file,
        log=lambda message: print(message, file=sys.stderr),
    )
    print(json.dumps({"pairs": result["pair_count"], **result["verdicts"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
