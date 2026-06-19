from pathlib import Path

import click
from rich.console import Console

from qseal.cli.common import (
    _load_constraints,
    _print_verification,
    _verification_inputs,
)
from qseal.cli.types import (
    CheckFailOn,
    DialectChoice,
    OutputFormat,
    SchemaFormat,
    VerifierChoice,
)
from qseal.dialects import DEFAULT_DIALECT
from qseal.verifier.backends import get_verifier_backend

console = Console()

@click.command(name="check")
@click.argument("original_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("rewritten_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--schema",
    "schema_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML file containing trusted schema constraints.",
)
@click.option(
    "--schema-format",
    type=SchemaFormat,
    default="auto",
    show_default=True,
    help="Schema constraint format.",
)
@click.option(
    "--format",
    "output_format",
    type=OutputFormat,
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--fail-on",
    type=CheckFailOn,
    default="none",
    show_default=True,
    help="Exit nonzero when the verification does not satisfy the selected policy.",
)
@click.option(
    "--verifier",
    type=VerifierChoice,
    default="builtin",
    show_default=True,
    help="Verifier backend.",
)
@click.option(
    "--solver-command",
    help="External verifier command to use with --verifier external.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    help="External verifier timeout in seconds.",
)
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used for verification.",
)
def check(
    original_path: Path,
    rewritten_path: Path,
    schema_path: Path,
    schema_format: str,
    output_format: str,
    fail_on: str,
    verifier: str,
    solver_command: str | None,
    timeout_seconds: int | None,
    dialect: str,
) -> None:
    """Check whether two supported SQL queries are equivalent."""
    original_sql = original_path.read_text()
    rewritten_sql = rewritten_path.read_text()

    try:
        constraints = _load_constraints(schema_path, schema_format)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    result = get_verifier_backend(
        verifier,
        solver_command=solver_command,
        timeout_seconds=timeout_seconds,
    ).verify(
        original_sql,
        rewritten_sql,
        constraints,
        dialect=dialect,
    )
    result = result.model_copy(
        update={
            "inputs": _verification_inputs(
                original_path,
                rewritten_path,
                schema_path,
                schema_format,
                dialect,
            )
        }
    )
    _print_verification(result, output_format, fail_on)
