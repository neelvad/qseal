import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.external_contract import ExternalSolverRequest
from snowprove.verifier.model import VerificationResult


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

        with tempfile.TemporaryDirectory(prefix="snowprove-sqlsolver-") as temp_dir:
            temp_path = Path(temp_dir)
            sql1_path = temp_path / "sql1.sql"
            sql2_path = temp_path / "sql2.sql"
            schema_path = temp_path / "schema.sql"
            sql1_path.write_text(f"{_one_line_sql(request.original_sql)}\n")
            sql2_path.write_text(f"{_one_line_sql(request.rewritten_sql)}\n")
            schema_path.write_text(_schema_sql(request.constraints))

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


def _one_line_sql(sql: str) -> str:
    stripped_comments = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", stripped_comments).strip().removesuffix(";")


def _schema_sql(constraints: ConstraintCatalog) -> str:
    statements = []
    for table_name, table in constraints.tables.items():
        columns = set(table.columns)
        for unique_key in table.unique:
            columns.update(unique_key)
        if not columns:
            columns.add("snowprove_id")

        column_defs = []
        for column in sorted(columns):
            suffix = " PRIMARY KEY" if (column,) in table.unique else ""
            column_defs.append(f"{column} INT{suffix}")
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
