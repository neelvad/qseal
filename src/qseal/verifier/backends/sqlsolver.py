import re
import shlex
import subprocess
import tempfile
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from qseal.constraints.model import ConstraintCatalog, ForeignKeyConstraint
from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.backends.external_contract import ExternalSolverRequest
from qseal.verifier.model import VerificationResult


class SqlSolverBackend:
    name = "sqlsolver"

    def __init__(
        self,
        solver_command: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.solver_command = solver_command
        self.timeout_seconds = timeout_seconds

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
        dialect: SqlDialect = DEFAULT_DIALECT,
    ) -> VerificationResult:
        if not self.solver_command:
            return VerificationResult(
                status=VerificationStatus.UNSUPPORTED,
                original_sql=original_sql.strip(),
                rewritten_sql=rewritten_sql.strip(),
                rule_name=self.name,
                reason="SQLSolver requires --solver-command.",
            )

        request = ExternalSolverRequest(
            original_sql=original_sql,
            rewritten_sql=rewritten_sql,
            constraints=constraints,
            dialect=dialect,
            solver_command=self.solver_command,
            timeout_seconds=self.timeout_seconds,
        )

        normalized = _unqualify_relations(original_sql, rewritten_sql, dialect)
        if normalized is None:
            return _unsupported(
                request,
                "Distinct qualified relations share an unqualified name, so the "
                "schema premises cannot be attached unambiguously.",
            )
        solver_sql1, solver_sql2 = normalized

        with tempfile.TemporaryDirectory(prefix="qseal-sqlsolver-") as temp_dir:
            temp_path = Path(temp_dir)
            sql1_path = temp_path / "sql1.sql"
            sql2_path = temp_path / "sql2.sql"
            schema_path = temp_path / "schema.sql"
            sql1_path.write_text(f"{_one_line_sql(solver_sql1)}\n")
            sql2_path.write_text(f"{_one_line_sql(solver_sql2)}\n")
            schema_path.write_text(
                _schema_sql(
                    request.constraints,
                    table_names=_referenced_tables(solver_sql1, solver_sql2, dialect),
                )
            )

            command = _command(
                self.solver_command,
                sql1_path=sql1_path,
                sql2_path=sql2_path,
                schema_path=schema_path,
            )
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            except FileNotFoundError as error:
                return _unsupported(request, f"SQLSolver command not found: {error.filename}.")
            except subprocess.TimeoutExpired:
                return VerificationResult(
                    status=VerificationStatus.UNKNOWN,
                    original_sql=request.normalized_original_sql(),
                    rewritten_sql=request.normalized_rewritten_sql(),
                    rule_name=self.name,
                    reason="SQLSolver timed out.",
                )

        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if completed.returncode != 0:
            return _unsupported(
                request,
                f"SQLSolver exited with code {completed.returncode}: {output.strip()}",
            )

        solver_result = _parse_sqlsolver_result(output)
        if solver_result is None:
            return _unsupported(request, f"Could not parse SQLSolver output: {output.strip()}")

        return VerificationResult(
            status=_status(solver_result),
            original_sql=request.normalized_original_sql(),
            rewritten_sql=request.normalized_rewritten_sql(),
            rule_name=self.name,
            verification_method="sqlsolver",
            safety_claim=(
                "SOLVER_PROVEN_EQUIVALENT"
                if solver_result == "EQ"
                else None
            ),
            reason=f"SQLSolver returned {solver_result}.",
        )


def _command(
    template: str,
    sql1_path: Path,
    sql2_path: Path,
    schema_path: Path,
) -> list[str]:
    substitutions = {
        "sql1": str(sql1_path),
        "sql2": str(sql2_path),
        "schema": str(schema_path),
    }
    if any(f"{{{name}}}" in template for name in substitutions):
        return shlex.split(template.format(**substitutions))

    return [
        *shlex.split(template),
        f"-sql1={sql1_path}",
        f"-sql2={sql2_path}",
        f"-schema={schema_path}",
        "-print",
    ]


def _unqualify_relations(
    original_sql: str,
    rewritten_sql: str,
    dialect: SqlDialect,
) -> tuple[str, str] | None:
    """Rewrite qualified relation names to the unqualified names the schema uses.

    QuerySeal constraints are keyed by unqualified model names, and the
    generated solver schema declares tables under those names. Renaming is a
    bijection only while distinct qualified relations keep distinct leaf
    names; otherwise the caller must give up instead of merging relations.
    """
    try:
        trees = [
            sqlglot.parse_one(sql, read=dialect)
            for sql in (original_sql, rewritten_sql)
        ]
    except SqlglotError:
        return original_sql, rewritten_sql

    leaf_owners: dict[str, tuple[str, str, str]] = {}
    for tree in trees:
        for table in tree.find_all(exp.Table):
            key = (table.catalog, table.db, table.name)
            owner = leaf_owners.setdefault(table.name, key)
            if owner != key:
                return None

    for tree in trees:
        for table in tree.find_all(exp.Table):
            table.set("catalog", None)
            table.set("db", None)
            identifier = table.this
            if isinstance(identifier, exp.Identifier) and _is_simple_identifier(
                identifier.this
            ):
                identifier.set("quoted", False)

    return tuple(tree.sql(dialect=dialect) for tree in trees)


def _is_simple_identifier(name: str) -> bool:
    return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is not None


def _one_line_sql(sql: str) -> str:
    stripped_comments = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", stripped_comments).strip().removesuffix(";")


def _referenced_tables(sql1: str, sql2: str, dialect: SqlDialect) -> set[str] | None:
    """Names of relations the pair references, or None when parsing fails."""
    names: set[str] = set()
    for sql in (sql1, sql2):
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
        except SqlglotError:
            return None
        names.update(table.name for table in tree.find_all(exp.Table))
    return names


def _schema_sql(
    constraints: ConstraintCatalog,
    table_names: set[str] | None = None,
) -> str:
    """DDL for catalog tables, restricted to referenced relations when known.

    Project-wide catalogs can hold thousands of tables; emitting them all
    makes the solver parse a huge schema for every pair.
    """
    extra_columns: dict[str, set[str]] = {}
    foreign_keys_by_table: dict[str, list[ForeignKeyConstraint]] = {}
    for table_name, table in constraints.tables.items():
        if table_names is not None and table_name not in table_names:
            continue
        for foreign_key in table.foreign_keys:
            if table_names is not None and foreign_key.ref_table not in table_names:
                continue
            extra_columns.setdefault(table_name, set()).update(foreign_key.columns)
            extra_columns.setdefault(foreign_key.ref_table, set()).update(
                foreign_key.ref_columns
            )
            foreign_keys_by_table.setdefault(table_name, []).append(foreign_key)

    statements = []
    for table_name, table in constraints.tables.items():
        if table_names is not None and table_name not in table_names:
            continue
        columns = set(table.columns) | extra_columns.get(table_name, set())
        for unique_key in table.unique:
            columns.update(unique_key)
        if not columns:
            columns.add("qseal_id")

        column_defs = []
        for column in sorted(columns):
            # PRIMARY KEY implies NOT NULL, so it only encodes a trusted unique
            # key faithfully when the column is also trusted non-null. Unique
            # keys on nullable columns are omitted rather than overstated.
            if (column,) in table.unique and table.is_non_null(column):
                suffix = " PRIMARY KEY"
            elif table.is_non_null(column):
                suffix = " NOT NULL"
            else:
                suffix = ""
            column_defs.append(f"{column} INT{suffix}")
        for foreign_key in foreign_keys_by_table.get(table_name, []):
            column_defs.append(
                "FOREIGN KEY "
                f"({', '.join(foreign_key.columns)}) "
                f"REFERENCES {foreign_key.ref_table} "
                f"({', '.join(foreign_key.ref_columns)})"
            )
        statements.append(f"CREATE TABLE {table_name} ( {', '.join(column_defs)} );")
    return "\n".join(statements) + "\n"


def _parse_sqlsolver_result(output: str) -> str | None:
    matches = re.findall(r"\b(EQ|NEQ|UNKNOWN|TIMEOUT)\b", output)
    return matches[-1] if matches else None


def _status(result: str) -> VerificationStatus:
    if result == "EQ":
        return VerificationStatus.PROVEN_EQUIVALENT
    if result == "NEQ":
        return VerificationStatus.NOT_EQUIVALENT
    return VerificationStatus.UNKNOWN


def _unsupported(request: ExternalSolverRequest, reason: str) -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.UNSUPPORTED,
        original_sql=request.normalized_original_sql(),
        rewritten_sql=request.normalized_rewritten_sql(),
        rule_name=SqlSolverBackend.name,
        reason=reason,
    )
