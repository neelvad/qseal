import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.sqlsolver import _unqualify_relations
from snowprove.verifier.backends.verieql import collect_pair_schema
from snowprove.verifier.model import VerificationResult


class QedBackend:
    """Prover backed by the QED toolchain (Calcite parser + Rust prover).

    Both components run natively; configure via constructor arguments or the
    SNOWPROVE_QED_PARSER_JAR / SNOWPROVE_QED_PROVER / SNOWPROVE_QED_JAVA /
    SNOWPROVE_QED_SOLVER_BIN environment variables. The prover needs z3 and
    cvc5 executables reachable through PATH at runtime.
    """

    name = "qed"

    def __init__(
        self,
        parser_jar: str | Path | None = None,
        prover_path: str | Path | None = None,
        java_path: str | Path | None = None,
        solver_bin_dir: str | Path | None = None,
        timeout_seconds: int | None = 60,
    ) -> None:
        self.parser_jar = _option(parser_jar, "SNOWPROVE_QED_PARSER_JAR")
        self.prover_path = _option(prover_path, "SNOWPROVE_QED_PROVER")
        self.java_path = _option(java_path, "SNOWPROVE_QED_JAVA") or _default_java()
        self.solver_bin_dir = _option(solver_bin_dir, "SNOWPROVE_QED_SOLVER_BIN")
        self.timeout_seconds = timeout_seconds

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
        dialect: SqlDialect = DEFAULT_DIALECT,
    ) -> VerificationResult:
        if self.parser_jar is None or self.prover_path is None:
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.UNSUPPORTED,
                reason=(
                    "QED requires a parser jar and prover binary "
                    "(SNOWPROVE_QED_PARSER_JAR / SNOWPROVE_QED_PROVER)."
                ),
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

        try:
            trees = [sqlglot.parse_one(sql, read=dialect) for sql in (sql1, sql2)]
        except SqlglotError as error:
            return self._result(
                original_sql,
                rewritten_sql,
                VerificationStatus.UNSUPPORTED,
                reason=f"Could not parse SQL: {error}",
            )

        schema = collect_pair_schema(trees, constraints)
        if isinstance(schema, str):
            return self._result(
                original_sql, rewritten_sql, VerificationStatus.UNSUPPORTED, reason=schema
            )

        case_sql = _qed_case(schema, constraints, sql1, sql2, trees, dialect)
        status, reason = self._run_toolchain(case_sql)
        return self._result(original_sql, rewritten_sql, status, reason=reason)

    def _run_toolchain(self, case_sql: str) -> tuple[VerificationStatus, str]:
        with tempfile.TemporaryDirectory(prefix="snowprove-qed-") as temp_dir:
            temp_path = Path(temp_dir)
            case_path = temp_path / "pair.sql"
            case_path.write_text(case_sql)

            parse = self._run(
                [
                    str(self.java_path),
                    "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
                    "-jar",
                    str(self.parser_jar),
                    str(case_path),
                ],
            )
            if isinstance(parse, str):
                return VerificationStatus.UNKNOWN, parse
            json_path = temp_path / "pair.json"
            if not json_path.exists():
                detail = (parse.stderr or parse.stdout).strip()[-300:]
                return (
                    VerificationStatus.UNSUPPORTED,
                    f"QED parser rejected the pair: {detail}",
                )

            prove = self._run([str(self.prover_path), str(json_path)])
            if isinstance(prove, str):
                return VerificationStatus.UNKNOWN, prove

        output = f"{prove.stdout}\n{prove.stderr}"
        if "\tNotProvable(" in output:
            return VerificationStatus.UNKNOWN, "QED returned NotProvable."
        if "\tProvable(" in output:
            return VerificationStatus.PROVEN_EQUIVALENT, "QED returned Provable."
        detail = output.strip()[-300:]
        return VerificationStatus.UNSUPPORTED, f"Could not parse QED output: {detail}"

    def _run(self, command: list[str]) -> subprocess.CompletedProcess | str:
        env = {
            "PATH": ":".join(
                part
                for part in (
                    str(self.solver_bin_dir) if self.solver_bin_dir else None,
                    "/opt/homebrew/bin",
                    "/usr/local/bin",
                    "/usr/bin",
                    "/bin",
                )
                if part
            ),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        try:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
            )
        except FileNotFoundError as error:
            return f"QED command not found: {error.filename}."
        except subprocess.TimeoutExpired:
            return f"QED timed out after {self.timeout_seconds}s."

    def _result(
        self,
        original_sql: str,
        rewritten_sql: str,
        status: VerificationStatus,
        reason: str,
    ) -> VerificationResult:
        return VerificationResult(
            status=status,
            original_sql=original_sql.strip(),
            rewritten_sql=rewritten_sql.strip(),
            rule_name=self.name,
            verification_method="qed",
            safety_claim=(
                "SOLVER_PROVEN_EQUIVALENT"
                if status == VerificationStatus.PROVEN_EQUIVALENT
                else None
            ),
            reason=reason,
        )


# Functions Calcite's MySQL frontend understands; anything else is declared
# as an uninterpreted scalar function, which is sound for proving: queries
# equivalent under arbitrary function semantics are equivalent under the
# real semantics.
_KNOWN_FUNCTIONS = {
    "abs", "avg", "cast", "ceil", "ceiling", "char_length", "coalesce",
    "concat", "count", "floor", "greatest", "least", "lower", "max", "min",
    "mod", "nullif", "power", "replace", "round", "substring", "sum",
    "trim", "upper",
}


def _qed_case(
    schema: dict[str, set[str]],
    constraints: ConstraintCatalog,
    sql1: str,
    sql2: str,
    trees: list[exp.Expression],
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> str:
    """One QED input file: MySQL-valid DDL plus the two SELECT statements.

    QED treats UNIQUE as strict uniqueness including NULLs, so a trusted
    unique key is emitted only when its columns are also trusted non-null;
    weaker premises are omitted, which is sound for a prover. Columns
    compared against string literals anywhere in the pair are typed varchar
    so Calcite's validator accepts the comparisons; unknown functions are
    declared as uninterpreted scalars.
    """
    varchar_columns = _string_typed_columns(trees)
    statements = []
    for table_name in sorted(schema):
        columns = {column.lower() for column in schema[table_name]}
        table = constraints.table(table_name.lower())
        non_null: set[str] = set()
        unique_keys: list[tuple[str, ...]] = []
        if table is not None:
            non_null = {
                column
                for column, constraint in table.columns.items()
                if constraint.nullable is False
            }
            unique_keys = [
                key
                for key in table.unique
                if all(column in non_null for column in key)
            ]
            for key in unique_keys:
                columns.update(key)
            columns.update(non_null & set(table.columns))

        lines = []
        for column in sorted(columns) or ["snowprove_id"]:
            column_type = "varchar" if column in varchar_columns else "integer"
            suffix = " not null" if column in non_null else ""
            lines.append(f"  {column} {column_type}{suffix}")
        lines.extend(f"  unique ({', '.join(key)})" for key in unique_keys)
        statements.append(
            f"create table {table_name.lower()} (\n" + ",\n".join(lines) + "\n);"
        )

    declarations = _function_declarations(trees, dialect)
    queries = "\n\n".join(f"{sql.rstrip().rstrip(';')};" for sql in (sql1, sql2))
    parts = ["\n".join(statements)]
    if declarations:
        parts.append("\n".join(declarations))
    parts.append(queries)
    return "\n\n".join(parts) + "\n"


def _string_typed_columns(trees: list[exp.Expression]) -> set[str]:
    """Column names compared against string literals anywhere in the pair."""
    names: set[str] = set()
    comparison_types = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like)
    for tree in trees:
        for node in tree.walk():
            if isinstance(node, comparison_types):
                sides = (node.this, node.expression)
            elif isinstance(node, exp.In):
                sides = (node.this, *node.expressions)
            else:
                continue
            has_string = any(
                isinstance(side, exp.Literal) and side.is_string for side in sides
            )
            if has_string:
                names.update(
                    side.name.lower() for side in sides if isinstance(side, exp.Column)
                )
    return names


def _function_declarations(
    trees: list[exp.Expression],
    dialect: SqlDialect,
) -> list[str]:
    """Uninterpreted-scalar declarations for functions Calcite will not know.

    Names come from the rendered surface form (the SQL actually sent to the
    parser), not sqlglot's canonical node names, which can differ.
    """
    arities: dict[str, int] = {}
    for tree in trees:
        for node in tree.walk():
            if not isinstance(node, exp.Func) or isinstance(
                node, exp.AggFunc | exp.Window | exp.Cast | exp.Case
            ):
                continue
            rendered = node.sql(dialect=dialect)
            match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\(", rendered)
            if match is None:
                continue
            name = match.group(1).lower()
            if name in _KNOWN_FUNCTIONS:
                continue
            arity = _rendered_arity(rendered)
            if arity is None:
                continue
            arities.setdefault(name, arity)
    return [
        f"declare scalar function {name}"
        f"({', '.join(['integer'] * arity)}) returns integer;"
        for name, arity in sorted(arities.items())
    ]


def _rendered_arity(rendered: str) -> int | None:
    """Argument count of a rendered call, counting top-level commas only."""
    if not rendered.endswith(")"):
        return None
    inner = rendered[rendered.index("(") + 1 : -1]
    if not inner.strip():
        return 0
    depth = 0
    in_string = False
    count = 1
    for char in inner:
        if in_string:
            in_string = char != "'"
        elif char == "'":
            in_string = True
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            count += 1
    return count


def _option(value: str | Path | None, env_name: str) -> Path | None:
    if value is not None:
        return Path(value)
    env_value = os.environ.get(env_name)
    return Path(env_value) if env_value else None


def _default_java() -> Path:
    homebrew_java = Path("/opt/homebrew/opt/openjdk/bin/java")
    if homebrew_java.exists():
        return homebrew_java
    return Path(shutil.which("java") or "java")
