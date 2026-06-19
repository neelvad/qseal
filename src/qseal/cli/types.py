import click

from qseal.dialects import SUPPORTED_DIALECTS
from qseal.rewrites.registry import rule_names

OutputFormat = click.Choice(["text", "json"], case_sensitive=False)
ScanFormat = click.Choice(["text", "json", "markdown"], case_sensitive=False)
SchemaFormat = click.Choice(["auto", "qseal", "dbt"], case_sensitive=False)
RuleChoice = click.Choice(rule_names(), case_sensitive=False)
FailOn = click.Choice(["none", "findings"], case_sensitive=False)
CheckFailOn = click.Choice(["none", "unproven"], case_sensitive=False)
VerifierChoice = click.Choice(["builtin", "external", "sqlsolver", "qed"], case_sensitive=False)
DialectChoice = click.Choice(SUPPORTED_DIALECTS, case_sensitive=False)
SearchStrategyChoice = click.Choice(
    [
        "fixed_order",
        "random",
        "greedy",
        "beam",
        "exhaustive",
        "policy_baseline",
        "policy_baseline_abstain",
    ],
    case_sensitive=False,
)
RewardModelChoice = click.Choice(["transition", "state"], case_sensitive=False)
PolicyLabelGroupChoice = click.Choice(
    [
        "action_set",
        "rule_pair",
        "preferred_rule",
        "alternative_rule",
        "table",
        "fixture",
        "target",
        "target_pair",
    ],
    case_sensitive=False,
)
