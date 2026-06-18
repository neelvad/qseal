import json
import subprocess
import tempfile
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.backends.sqlsolver import _unqualify_relations
from qseal.verifier.model import VerificationResult

DRIVER_PATH = Path(__file__).resolve().parents[4] / "scripts" / "verieql_driver.py"


class VeriEqlBackend:
    """Bounded refuter backed by an external VeriEQL checkout.

    A counterexample is a sound refutation. The absence of one up to the
    bound is only evidence and never maps to PROVEN_EQUIVALENT.
    """

    name = "verieql"

    def __init__(
        self,
        verieql_dir: str | Path | None = None,
        python_path: str | Path | None = None,
        bound: int = 2,
        timeout_seconds: int | None = 120,
    ) -> None:
        self.verieql_dir = Path(verieql_dir) if verieql_dir else None
        self.python_path = Path(python_path) if python_path else None
        self.bound = bound
        self.timeout_seconds = timeout_seconds

    def refute(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
        dialect: SqlDialect = DEFAULT_DIALECT,
    ) -> VerificationResult:
        if self.verieql_dir is None:
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.UNSUPPORTED,
                reason="VeriEQL refutation requires --verieql-dir.",
            )

        normalized = _unqualify_relations(original_sql, rewritten_sql, dialect)
        if normalized is None:
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.UNSUPPORTED,
                reason=(
                    "Distinct qualified relations share an unqualified name, so the "
                    "schema premises cannot be attached unambiguously."
                ),
            )
        sql1, sql2 = normalized

        request = _build_request(sql1, sql2, constraints, dialect, self.bound)
        if isinstance(request, str):
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.UNSUPPORTED,
                reason=request,
            )

        verdict = self._run_driver(request)
        if isinstance(verdict, str):
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.UNSUPPORTED,
                reason=verdict,
            )

        if verdict["result"] == "refuted":
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.NOT_EQUIVALENT,
                reason=(
                    f"VeriEQL found a counterexample database within bound "
                    f"{verdict['bound']}."
                ),
                counterexample=verdict.get("counterexample"),
            )
        if verdict["result"] == "bounded_ok":
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.UNKNOWN,
                reason=(
                    f"VeriEQL found no counterexample up to bound {verdict['bound']}; "
                    "bounded evidence is not a proof of equivalence."
                ),
            )
        return self._result(
            original_sql,
            rewritten_sql,
            VerificationStatus.UNSUPPORTED,
            reason=f"VeriEQL could not check this pair: {verdict.get('reason')}",
        )

    def _run_driver(self, request: dict) -> dict | str:
        python_path = self.python_path or (self.verieql_dir / ".venv" / "bin" / "python")
        if not Path(python_path).exists():
            return f"VeriEQL python interpreter not found: {python_path}"

        with tempfile.TemporaryDirectory(prefix="qseal-verieql-") as temp_dir:
            request_path = Path(temp_dir) / "request.json"
            request_path.write_text(json.dumps(request))
            try:
                completed = subprocess.run(
                    [str(python_path), str(DRIVER_PATH), str(request_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=self.verieql_dir,
                    env={"PYTHONPATH": str(self.verieql_dir), "PATH": "/usr/bin:/bin"},
                )
            except subprocess.TimeoutExpired:
                return f"VeriEQL timed out after {self.timeout_seconds}s."

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-300:]
            return f"VeriEQL driver failed: {detail}"
        try:
            return json.loads(completed.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return f"Could not parse VeriEQL driver output: {completed.stdout[:200]}"

    def _result(
        self,
        original_sql: str,
        rewritten_sql: str,
        status: VerificationStatus,
        reason: str,
        counterexample: str | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            status=status,
            original_sql=original_sql.strip(),
            rewritten_sql=rewritten_sql.strip(),
            rule_name=self.name,
            verification_method="verieql",
            reason=reason,
            counterexample=counterexample,
        )


def _build_request(
    sql1: str,
    sql2: str,
    constraints: ConstraintCatalog,
    dialect: SqlDialect,
    bound: int,
) -> dict | str:
    """Build the driver request, or return an abstention reason string."""
    try:
        trees = [sqlglot.parse_one(sql, read=dialect) for sql in (sql1, sql2)]
    except SqlglotError as error:
        return f"Could not parse SQL: {error}"

    for tree in trees:
        if tree.find(exp.Qualify) is not None:
            # VeriEQL silently ignores QUALIFY, which would corrupt verdicts.
            return "VeriEQL does not model QUALIFY."

    schema = collect_pair_schema(trees, constraints)
    if isinstance(schema, str):
        return schema

    request_constraints, abstention = _build_constraints(schema, constraints)
    if abstention is not None:
        return abstention

    # VeriEQL uppercases relation names internally, so schema keys and
    # constraint attribute references must be uppercased to match.
    return {
        "sql1": sql1,
        "sql2": sql2,
        "schema": {
            table.upper(): {
                column.upper(): "INT" for column in sorted(columns) or ["qseal_id"]
            }
            for table, columns in schema.items()
        },
        "constraints": request_constraints,
        "bound": bound,
    }


def collect_pair_schema(
    trees: list[exp.Expression],
    constraints: ConstraintCatalog,
) -> dict[str, set[str]] | str:
    """Table -> columns for a query pair, or an abstention reason string."""
    schema: dict[str, set[str]] = {}
    for tree in trees:
        outcome = _collect_schema(tree, schema, constraints)
        if outcome is not None:
            return outcome
    if not schema:
        return "No base tables found to declare a schema for."
    return schema


def _collect_schema(
    tree: exp.Expression,
    schema: dict[str, set[str]],
    constraints: ConstraintCatalog,
) -> str | None:
    """Attribute every column reference to a base table, or return a reason."""
    for scope in traverse_scope(tree):
        for table in scope.tables:
            if scope.sources.get(table.alias_or_name) is table and not _is_cte_reference(
                scope, table
            ):
                schema.setdefault(table.name, set())
        for column in scope.columns:
            outcome = _attribute_column(column, scope, schema, constraints)
            if outcome is not None:
                return outcome
    return None


def _is_cte_reference(scope: Scope, table: exp.Table) -> bool:
    cte_scope = scope.cte_sources.get(table.name) if hasattr(scope, "cte_sources") else None
    return cte_scope is not None


def _attribute_column(
    column: exp.Column,
    scope: Scope,
    schema: dict[str, set[str]],
    constraints: ConstraintCatalog,
) -> str | None:
    if column.table:
        selected = _selected_sources(scope)
        source = selected.get(column.table, scope.sources.get(column.table))
        if source is None:
            return f"Could not resolve relation {column.table!r} for column {column.name!r}."
    else:
        sources = list(_selected_sources(scope).values())
        if len(sources) == 1:
            source = sources[0]
        else:
            candidates = [
                item for item in sources if _may_define(item, column.name, constraints)
            ]
            if len(candidates) != 1:
                # A second pass: a valid production query has exactly one owner
                # for an unqualified column, so if exactly one source's base
                # table *declares* it in the trusted catalog, that source owns
                # it. Star pass-through CTEs resolve to their base tables.
                declared = [
                    item
                    for item in candidates
                    if _definitely_defines(item, column.name, constraints)
                ]
                if len(declared) == 1:
                    candidates = declared
                else:
                    return (
                        f"Unqualified column {column.name!r} is ambiguous across "
                        f"{len(scope.sources)} relations."
                    )
            source = candidates[0]

    return _attribute_to_source(column.name, source, schema)


def _selected_sources(scope: Scope) -> dict[str, exp.Table | Scope]:
    """Relation sources actually selected by this scope.

    sqlglot keeps previously defined CTEs in ``scope.sources`` so later CTE
    bodies can resolve them if referenced. For unqualified column ownership,
    those dormant CTEs must not compete with the tables the current SELECT
    actually reads from.
    """
    return {
        name: source
        for name, (_, source) in scope.selected_sources.items()
    }


def _may_define(
    source: exp.Table | Scope,
    column_name: str,
    constraints: ConstraintCatalog,
) -> bool:
    base = _base_table(source)
    if base is not None:
        # A base table with a declared column list cannot define columns
        # outside it; tables unknown to the catalog could define anything.
        table = constraints.table(base.name)
        if table is not None and table.columns:
            return column_name in table.columns
        return True
    if isinstance(source, exp.Table):
        return True
    body = source.expression
    if not isinstance(body, exp.Select):
        return True
    if any(isinstance(projection, exp.Star) for projection in body.expressions):
        return True
    return column_name in body.named_selects


def _base_table(source: exp.Table | Scope) -> exp.Table | None:
    """Resolve a source to its base table, following star pass-through CTEs."""
    seen = 0
    while isinstance(source, Scope):
        body = source.expression
        if not _is_star_passthrough_body(body):
            return None
        inner = body.args["from_"].this
        next_source = source.sources.get(inner.alias_or_name)
        if next_source is None:
            return inner if isinstance(inner, exp.Table) else None
        source = next_source
        seen += 1
        if seen > 16:
            return None
    return source if isinstance(source, exp.Table) else None


def _definitely_defines(
    source: exp.Table | Scope,
    column_name: str,
    constraints: ConstraintCatalog,
) -> bool:
    """True when the source is positively known to define the column.

    A CTE or derived table with explicit projections defines exactly those
    names. A base table (directly or behind star pass-throughs) defines a
    column when the trusted catalog declares it.
    """
    if isinstance(source, Scope):
        body = source.expression
        if isinstance(body, exp.Select) and not any(
            isinstance(projection, exp.Star) for projection in body.expressions
        ):
            return column_name in body.named_selects
    base = _base_table(source)
    if base is None:
        return False
    table = constraints.table(base.name)
    return table is not None and column_name in table.columns


def _attribute_to_source(
    column_name: str,
    source: exp.Table | Scope,
    schema: dict[str, set[str]],
) -> str | None:
    seen = 0
    while isinstance(source, Scope):
        # A column that flows through a CTE or derived table only needs a base
        # schema entry when the body is a star pass-through; otherwise the
        # body's own projections define it and are attributed in their scope.
        body = source.expression
        if not _is_star_passthrough_body(body):
            return None
        inner = body.args["from_"].this
        next_source = source.sources.get(inner.alias_or_name)
        if next_source is None:
            return f"Could not resolve pass-through source for column {column_name!r}."
        source = next_source
        seen += 1
        if seen > 16:
            return "Pass-through resolution exceeded depth limit."

    if isinstance(source, exp.Table):
        schema.setdefault(source.name, set()).add(column_name)
        return None
    return f"Unsupported relation source for column {column_name!r}."


def _is_star_passthrough_body(body: exp.Expression) -> bool:
    if not isinstance(body, exp.Select):
        return False
    if len(body.expressions) != 1 or not isinstance(body.expressions[0], exp.Star):
        return False
    for arg in ("joins", "where", "group", "having", "qualify", "distinct", "order", "limit"):
        if body.args.get(arg):
            return False
    from_expr = body.args.get("from_")
    return from_expr is not None and isinstance(from_expr.this, exp.Table)


def _build_constraints(
    schema: dict[str, set[str]],
    constraints: ConstraintCatalog,
) -> tuple[list[dict], str | None]:
    request_constraints: list[dict] = []
    for table_name in sorted(schema):
        table = constraints.table(table_name)
        if table is None:
            continue
        for foreign_key in table.foreign_keys:
            if foreign_key.ref_table in schema:
                return [], (
                    "Trusted foreign key "
                    f"{table_name}.{foreign_key.columns} -> "
                    f"{foreign_key.ref_table}.{foreign_key.ref_columns} "
                    "cannot be encoded by the VeriEQL refuter yet."
                )

        primary_columns: set[str] = set()
        for key in table.unique:
            if not all(table.is_non_null(column) for column in key):
                # A NULL-exempt unique key is not expressible; dropping a
                # trusted premise could produce false refutations.
                return [], (
                    f"Trusted unique key {key} on {table_name} is not non-null, "
                    "which VeriEQL cannot encode faithfully."
                )
            schema[table_name].update(key)
            request_constraints.append(
                {
                    "primary": [
                        {"value": f"{table_name}__{column}".upper()} for column in key
                    ]
                }
            )
            primary_columns.update(key)

        for column, constraint in table.columns.items():
            if constraint.nullable is False and column not in primary_columns:
                schema[table_name].add(column)
                request_constraints.append(
                    {"not_null": {"value": f"{table_name}__{column}".upper()}}
                )

    return request_constraints, None
