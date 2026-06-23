"""Stage-1 parse-coverage probe for BIRD-style SQL against the qseal subset.

Measures how much of a BIRD dev corpus the qseal parser can handle, and
classifies the drop-outs so the next investment is visible. This is the
go/no-go probe for the NL2SQL eval-tool framing: parser coverage is the
ceiling, so we measure it first.

Usage:
    python scripts/probe_bird_coverage.py --gold JSON --predictions JSON [--dialect sqlite]

    --gold           JSON file: either a list of SQL strings, or BIRD dev.json
                     (list of {query, db_id, ...}).
    --predictions    Optional. BIRD predict_dev.json: a dict {id: "SQL\\t----- bird -----\\tdb_id"}
                     or a list of SQL strings.
    --dialect        qseal dialect to parse as (default sqlite).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select

_BIRD_SEP = "\t----- bird -----\t"


def _extract_sql(value: object) -> str | None:
    if isinstance(value, str):
        if _BIRD_SEP in value:
            return value.split(_BIRD_SEP, 1)[0]
        return value
    if isinstance(value, dict):
        for key in ("query", "sql", "predicted", "gold"):
            if key in value and isinstance(value[key], str):
                return value[key]
    return None


def _load_corpus(path: Path) -> list[str]:
    raw = json.loads(path.read_text())
    items: list[object]
    if isinstance(raw, dict):
        items = list(raw.values())
    elif isinstance(raw, list):
        items = raw
    else:
        raise SystemExit(f"unexpected JSON shape in {path}")
    sqls = []
    for value in items:
        sql = _extract_sql(value)
        if sql:
            sqls.append(sql)
    return sqls


def _classify_blocker(message: str) -> str:
    m = message.lower()
    if "recursive" in m:
        return "recursive_cte"
    if "order by" in m:
        return "order_by_unsupported"
    if "limit" in m:
        return "limit_unsupported"
    if "having" in m:
        return "having_unsupported"
    if "direct columns, stars, and simple aliased scalar" in m:
        return "projection_unsupported"
    if "where comparisons must compare a column to a literal" in m:
        return "where_col_to_col"
    if "where in predicates must include at least one literal" in m:
        return "where_in_subquery"
    if "only anded column/literal comparisons, in predicates" in m:
        return "where_complex"
    if "only inner join and left join" in m or "right join" in m:
        return "join_kind"
    if "join conditions" in m or "direct table join targets" in m:
        return "join_cond_or_target"
    if "only select statements" in m:
        return "non_select"
    if "must include a from table" in m or "from table" in m:
        return "no_from"
    if "qualify" in m:
        return "qualify_clause"
    if "cte" in m or "with" in m:
        return "cte_shape"
    if "subquer" in m:
        return "subquery_shape"
    if "distinct" in m:
        return "distinct_shape"
    if "window" in m:
        return "window_func"
    if "could not parse" in m:
        return "sqlglot_parse_error"
    return "other"


def _probe(corpus: list[str], dialect: str, label: str) -> dict:
    reached = Counter()
    blockers = Counter()
    blocker_examples: dict[str, tuple[str, str]] = {}
    sample_fails: list[str] = []
    for sql in corpus:
        try:
            parse_select(sql, dialect=dialect)
            reached["parse_ok"] += 1
        except UnsupportedSqlError as exc:
            reached["parse_fail"] += 1
            key = _classify_blocker(str(exc))
            blockers[key] += 1
            if key not in blocker_examples:
                blocker_examples[key] = (str(exc)[:160], sql[:160])
            if len(sample_fails) < 5:
                sample_fails.append(sql[:160])
        except Exception:  # sqlglot ParseError and anything else
            reached["sqlglot_error"] += 1
            blockers["sqlglot_error"] += 1
            if "sqlglot_error" not in blocker_examples:
                blocker_examples["sqlglot_error"] = ("sqlglot parse error", sql[:160])

    total = len(corpus)
    ok = reached["parse_ok"]
    print(f"\n=== {label} (n={total}, dialect={dialect}) ===")
    print(f"parse_ok         : {ok:5d}  ({ok / total:.1%})" if total else "n=0")
    print(f"parse_fail       : {reached['parse_fail']:5d}")
    print(f"sqlglot_error    : {reached['sqlglot_error']:5d}")
    print("\ntop blockers:")
    for key, count in blockers.most_common():
        print(f"  {count:5d}  {key}")
    print("\nblocker examples (message | sql):")
    for key, (msg, sql) in sorted(blocker_examples.items()):
        print(f"  [{key}] {msg!r} | {sql!r}")
    return {
        "label": label,
        "total": total,
        "parse_ok": ok,
        "parse_fail": reached["parse_fail"],
        "sqlglot_error": reached["sqlglot_error"],
        "blockers": dict(blockers.most_common()),
        "parse_ok_pct": (ok / total) if total else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, default=None)
    ap.add_argument("--dialect", default="sqlite")
    ap.add_argument("--report-file", type=Path, default=None)
    args = ap.parse_args()

    results = []
    gold = _load_corpus(args.gold)
    results.append(_probe(gold, args.dialect, "BIRD dev gold"))

    if args.predictions:
        preds = _load_corpus(args.predictions)
        results.append(_probe(preds, args.dialect, "BIRD dev predictions"))

    if args.report_file:
        args.report_file.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.report_file}")


if __name__ == "__main__":
    main()