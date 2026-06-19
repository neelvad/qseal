from pathlib import Path

import click
from rich.console import Console

from qseal.cli.common import (
    _load_constraints,
    _verification_inputs,
)
from qseal.cli.types import (
    DialectChoice,
    OutputFormat,
    SchemaFormat,
)
from qseal.dialects import DEFAULT_DIALECT
from qseal.report.json import (
    render_verification_json,
)
from qseal.report.text import (
    render_verification_report,
)
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.backends.verieql import VeriEqlBackend

console = Console()

@click.command(name="refute", hidden=True)
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
    "--verieql-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to a local VeriEQL checkout with a .venv prepared by "
    "scripts/run_verieql_spike.sh.",
)
@click.option(
    "--bound",
    type=click.IntRange(min=1),
    default=2,
    show_default=True,
    help="Maximum rows per table in the counterexample search.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    default=120,
    show_default=True,
    help="Refuter timeout in seconds.",
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
    type=click.Choice(["none", "refuted"], case_sensitive=False),
    default="none",
    show_default=True,
    help="Exit nonzero when the pair is refuted.",
)
@click.option(
    "--dialect",
    type=DialectChoice,
    default=DEFAULT_DIALECT,
    show_default=True,
    help="SQL dialect used to parse the queries.",
)
def refute(
    original_path: Path,
    rewritten_path: Path,
    schema_path: Path,
    schema_format: str,
    verieql_dir: Path,
    bound: int,
    timeout_seconds: int,
    output_format: str,
    fail_on: str,
    dialect: str,
) -> None:
    """Search for a bounded counterexample with VeriEQL.

    A counterexample soundly refutes equivalence under the trusted
    constraints. Finding none up to the bound is evidence only and is
    reported as UNKNOWN, never as a proof.
    """
    try:
        constraints = _load_constraints(schema_path, schema_format)
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    result = VeriEqlBackend(
        verieql_dir=verieql_dir,
        bound=bound,
        timeout_seconds=timeout_seconds,
    ).refute(
        original_path.read_text(),
        rewritten_path.read_text(),
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

    if output_format == "json":
        click.echo(render_verification_json(result))
    else:
        console.print(render_verification_report(result))

    if fail_on == "refuted" and result.status == VerificationStatus.NOT_EQUIVALENT:
        raise click.exceptions.Exit(1)
