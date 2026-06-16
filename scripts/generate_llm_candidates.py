# Thin shim for `qseal llm generate`; kept for existing docs/automation.
# All logic lives in qseal.candidates.generation.
import argparse
import json
import sys
from pathlib import Path

from qseal.candidates.generation import generate_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_path", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--use-batches", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = generate_candidates(
        args.project_path,
        args.out,
        dialect=args.dialect,
        limit=args.limit,
        max_candidates=args.max_candidates,
        use_batches=args.use_batches,
        dry_run=args.dry_run,
        log=lambda message: print(message, file=sys.stderr),
    )
    print(json.dumps(summary), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
