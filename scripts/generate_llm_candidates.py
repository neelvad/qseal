# Generate LLM rewrite candidates for dbt models as snowprove candidate bundles.
#
# Offline batch producer per the plan in AGENTS.md: premise-targeted prompts,
# PROVEN-only acceptance happens downstream in scripts/verify_llm_candidates.py.
#
#   uv run python scripts/generate_llm_candidates.py PROJECT --out DIR --limit 5
#   uv run python scripts/generate_llm_candidates.py PROJECT --out DIR --use-batches
import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from snowprove.constraints.model import ConstraintCatalog
from snowprove.dbt.jinja import preprocess_dbt_sql
from snowprove.dbt.project import discover_dbt_project
from snowprove.dbt.scan import _load_project_constraints
from snowprove.parser.fragments import parse_select_fragments
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select

MODEL_ID = "claude-opus-4-8"
MAX_TOKENS = 16000

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "rationale": {"type": "string"},
                    "premises_used": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["sql", "rationale", "premises_used"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You generate rewrite candidates for Snowprove, a tool that formally verifies \
SQL rewrites before anyone sees them. Your candidates are untrusted proposals: \
every one is checked by an equivalence prover, so a wrong candidate is filtered \
out, but a missed opportunity is lost. Propose boldly, within the rules below.

## Trusted premises

You will be given integrity constraints derived from the project's dbt tests. \
These are TRUSTED facts the data warehouse itself does not know, which means \
the warehouse optimizer cannot exploit them - but you can. The most valuable \
candidates are rewrites that are only correct BECAUSE of these premises.

Premise vocabulary:
- "unique among non-NULL values": no two non-NULL rows share this value. \
NULL duplicates may exist unless the column is also never-NULL.
- "never NULL": the column has no NULL values.

## Hard requirements for every candidate

1. Bag-semantics equivalence: for every database satisfying the premises, the \
candidate returns exactly the same multiset of rows as the original.
2. Identical output columns: same names, same order, same aliases.
3. Same dialect as the original. Do not add comments.
4. Do not propose the original query verbatim or with cosmetic changes only \
(formatting, capitalization, alias shuffling). Identity candidates are discarded.
5. If no sound rewrite exists, return an empty candidates list. That is a good \
answer; forced candidates waste verification time.

## Worked examples of premise-enabled rewrites

1. DISTINCT removal. Premise: user_id is unique among non-NULL values AND never \
NULL, and the projection contains user_id.
   SELECT DISTINCT user_id, status FROM users
   -> SELECT user_id, status FROM users

2. Redundant IS NOT NULL removal. Premise: email is never NULL.
   SELECT id FROM users WHERE email IS NOT NULL AND status = 'active'
   -> SELECT id FROM users WHERE status = 'active'

3. Unused LEFT JOIN elimination. Premise: dim_users.user_id is unique among \
non-NULL values. The join cannot duplicate rows (unique key) or filter rows \
(LEFT), and nothing outside the ON clause references it.
   SELECT f.id, f.revenue FROM fact_orders f LEFT JOIN dim_users u ON f.user_id = u.user_id
   -> SELECT f.id, f.revenue FROM fact_orders f

4. JOIN + DISTINCT to EXISTS (semi-join). No premise needed.
   SELECT DISTINCT u.user_id FROM users u JOIN orders o ON u.user_id = o.user_id
   -> SELECT u.user_id FROM users u \
WHERE EXISTS (SELECT 1 FROM orders o WHERE u.user_id = o.user_id)

5. Predicate pushdown through a projection subquery. No premise needed.
   SELECT user_id FROM (SELECT user_id, revenue FROM orders) x WHERE x.user_id > 5
   -> SELECT user_id FROM (SELECT user_id, revenue FROM orders WHERE user_id > 5) x

These patterns also apply inside CTE bodies of larger queries. Novel rewrites \
beyond these patterns are welcome when you are confident they are equivalent \
under the premises - the prover handles general rewrites, not just these shapes.

## Candidate sizing

Include at least one minimal, self-contained candidate when any sound rewrite \
exists: change a single CTE body or a single clause and keep every other byte \
of the query identical. Verifiers discharge small, local rewrites far more \
often than whole-query restructurings, so a modest candidate that verifies \
beats an ambitious one that cannot be checked. Ambitious restructurings are \
still welcome as additional candidates after the minimal one.

## Pitfalls that get candidates rejected

- Removing DISTINCT using a unique key that is not also never-NULL (duplicate \
NULL rows survive a dbt unique test).
- Changing row multiplicity before an aggregate or window function.
- Dropping a join or filter that affects rows referenced elsewhere in the query.
- Reordering or renaming output columns.

Return up to {max_candidates} candidates ranked by expected value, best first.\
"""

USER_TEMPLATE = """\
Dialect: {dialect}

Trusted premises (from dbt tests):
{premises}

Original query:
```sql
{sql}
```\
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_path", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--use-batches", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts, no API calls.")
    args = parser.parse_args()

    project = discover_dbt_project(args.project_path)
    constraints = _load_project_constraints(project.schema_yml_files)
    targets = _select_targets(project.model_sql_files, constraints, args.dialect)
    if args.limit is not None:
        targets = targets[: args.limit]
    print(f"Models selected (parseable, with premises): {len(targets)}", file=sys.stderr)

    system_prompt = SYSTEM_PROMPT.replace("{max_candidates}", str(args.max_candidates))
    requests = []
    for target in targets:
        user_message = USER_TEMPLATE.format(
            dialect=args.dialect,
            premises="\n".join(f"- {premise}" for premise in target["premises"]),
            sql=target["sql"],
        )
        requests.append({**target, "user_message": user_message})

    if args.dry_run:
        for request in requests:
            print(f"=== {request['name']}\n{request['user_message']}\n")
        return 0

    if args.use_batches:
        responses = _run_batched(system_prompt, requests)
    else:
        responses = _run_direct(system_prompt, requests)

    prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    summary = {"models": len(requests), "bundles": 0, "candidates": 0, "errors": 0}
    for request in requests:
        response = responses.get(request["name"])
        if response is None or "error" in response:
            summary["errors"] += 1
            continue
        written = _write_bundle(
            args.out / request["name"],
            request,
            response,
            prompt_hash=prompt_hash,
            generated_at=generated_at,
        )
        summary["bundles"] += 1
        summary["candidates"] += written

    (args.out / "run-summary.json").parent.mkdir(parents=True, exist_ok=True)
    # Snapshot the constraint catalog so verification does not need the
    # project tree (e.g. inside containers that cannot mount it).
    (args.out / "constraints.json").write_text(constraints.model_dump_json(indent=2))
    (args.out / "run-summary.json").write_text(
        json.dumps(
            {
                "artifact_type": "llm_candidate_run",
                "schema_version": 1,
                "generator_model": MODEL_ID,
                "prompt_hash": prompt_hash,
                "generated_at": generated_at,
                "dialect": args.dialect,
                **summary,
            },
            indent=2,
        )
    )
    print(json.dumps(summary), file=sys.stderr)
    return 0


def _select_targets(model_paths, constraints: ConstraintCatalog, dialect: str) -> list[dict]:
    targets = []
    for model_path in sorted(model_paths):
        preprocessed = preprocess_dbt_sql(model_path.read_text())
        if preprocessed.unsupported_reason is not None:
            continue
        sql = preprocessed.sql.strip()
        if not _is_parseable(sql, dialect):
            continue
        premises = _premises_for(sql, constraints, dialect)
        if not premises:
            continue
        targets.append({"name": model_path.stem, "path": str(model_path), "sql": sql,
                        "premises": premises})
    return targets


def _is_parseable(sql: str, dialect: str) -> bool:
    try:
        parse_select(sql, dialect=dialect)
        return True
    except UnsupportedSqlError:
        pass
    try:
        fragments = parse_select_fragments(sql, dialect=dialect)
    except UnsupportedSqlError:
        return False
    return any(fragment.query is not None for fragment in fragments)


def _premises_for(sql: str, constraints: ConstraintCatalog, dialect: str) -> list[str]:
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError:
        return []
    cte_names = {cte.alias for cte in tree.find_all(exp.CTE)}
    table_names = {
        table.name for table in tree.find_all(exp.Table) if table.name not in cte_names
    }

    premises = []
    for table_name in sorted(table_names):
        table = constraints.table(table_name)
        if table is None:
            continue
        for key in table.unique:
            columns = ", ".join(key)
            premises.append(f"{table_name}.({columns}) is unique among non-NULL values")
        for column, constraint in table.columns.items():
            if constraint.nullable is False:
                premises.append(f"{table_name}.{column} is never NULL")
    return premises


def _request_params(system_prompt: str, request: dict) -> dict:
    return {
        "model": MODEL_ID,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": request["user_message"]}],
        "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }


def _parse_response_text(message) -> dict:
    text = next(block.text for block in message.content if block.type == "text")
    return json.loads(text)


def _run_direct(system_prompt: str, requests: list[dict]) -> dict[str, dict]:
    import anthropic

    client = anthropic.Anthropic()
    responses = {}
    for request in requests:
        try:
            message = client.messages.create(**_request_params(system_prompt, request))
            responses[request["name"]] = {
                "payload": _parse_response_text(message),
                "usage": message.usage.to_dict(),
            }
        except Exception as error:  # noqa: BLE001 - record and continue the run
            print(f"error on {request['name']}: {error}", file=sys.stderr)
            responses[request["name"]] = {"error": str(error)}
    return responses


def _run_batched(system_prompt: str, requests: list[dict]) -> dict[str, dict]:
    import anthropic

    client = anthropic.Anthropic()
    batch = client.messages.batches.create(
        requests=[
            {
                "custom_id": request["name"],
                "params": _request_params(system_prompt, request),
            }
            for request in requests
        ]
    )
    print(f"Batch {batch.id} submitted; polling...", file=sys.stderr)
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        time.sleep(30)

    responses = {}
    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            try:
                responses[result.custom_id] = {
                    "payload": _parse_response_text(result.result.message),
                    "usage": result.result.message.usage.to_dict(),
                }
            except (StopIteration, ValueError) as error:
                responses[result.custom_id] = {"error": f"unparseable response: {error}"}
        else:
            responses[result.custom_id] = {"error": result.result.type}
    return responses


def _write_bundle(
    bundle_dir: Path,
    request: dict,
    response: dict,
    prompt_hash: str,
    generated_at: str,
) -> int:
    candidates = response["payload"].get("candidates") or []
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "original.sql").write_text(f"{request['sql']}\n")

    entries = []
    for index, candidate in enumerate(candidates, start=1):
        sql = (candidate.get("sql") or "").strip()
        if not sql:
            continue
        filename = f"{index:03d}_llm.sql"
        (bundle_dir / filename).write_text(f"{sql}\n")
        entries.append(
            {
                "path": filename,
                "source": "llm",
                "description": candidate.get("rationale", ""),
                "premises_used": candidate.get("premises_used", []),
            }
        )

    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_type": "candidate_bundle",
                "source": "llm",
                "original_path": "original.sql",
                "model_path": request["path"],
                "generator": {
                    "model": MODEL_ID,
                    "prompt_hash": prompt_hash,
                    "generated_at": generated_at,
                    "usage": response.get("usage", {}),
                },
                "candidates": entries,
            },
            indent=2,
        )
    )
    return len(entries)


if __name__ == "__main__":
    sys.exit(main())
