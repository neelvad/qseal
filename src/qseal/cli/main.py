import click

from qseal.cli.benchmark import benchmark
from qseal.cli.benchmark_suite import benchmark_suite_group
from qseal.cli.candidates import candidates_group
from qseal.cli.check import check
from qseal.cli.corpus import corpus_group
from qseal.cli.dbt import dbt_group
from qseal.cli.fixtures import fixtures_group
from qseal.cli.llm import llm_group
from qseal.cli.policy import policy_group
from qseal.cli.refute import refute
from qseal.cli.suggest import suggest


@click.group()
def main() -> None:
    """Verified-safe SQL rewrites for a constrained SQL subset."""


main.add_command(dbt_group)
main.add_command(candidates_group)
main.add_command(fixtures_group)
main.add_command(benchmark_suite_group)
main.add_command(corpus_group)
main.add_command(policy_group)
main.add_command(llm_group)
main.add_command(benchmark)
main.add_command(suggest)
main.add_command(check)
main.add_command(refute)
