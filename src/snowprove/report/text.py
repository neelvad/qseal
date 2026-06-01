from rich.text import Text

from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.verifier.model import VerificationResult


def render_suggestion_report(suggestion: RewriteSuggestion) -> Text:
    output = Text()
    style = _status_style(suggestion.status)

    output.append("Result: ", style="bold")
    output.append(f"{suggestion.status.value}\n", style=style)
    output.append("Rewrite: ", style="bold")
    output.append(f"{suggestion.rule_name}\n")

    if suggestion.assumptions:
        output.append("Assumptions:\n", style="bold")
        for assumption in suggestion.assumptions:
            output.append(f"  - {assumption}\n")

    if suggestion.reason:
        output.append("Reason: ", style="bold")
        output.append(f"{suggestion.reason}\n")

    if suggestion.rewritten_sql:
        output.append("Rewritten SQL:\n", style="bold")
        output.append(suggestion.rewritten_sql)
        output.append("\n")

    return output


def render_verification_report(result: VerificationResult) -> Text:
    output = Text()

    output.append("Result: ", style="bold")
    output.append(f"{result.status.value}\n", style=_status_style(result.status))

    if result.assumptions:
        output.append("Assumptions:\n", style="bold")
        for assumption in result.assumptions:
            output.append(f"  - {assumption}\n")

    if result.reason:
        output.append("Reason: ", style="bold")
        output.append(f"{result.reason}\n")

    if result.counterexample:
        output.append("Counterexample:\n", style="bold")
        output.append(f"{result.counterexample}\n")

    return output


def _status_style(status: VerificationStatus) -> str:
    if status == VerificationStatus.PROVEN_EQUIVALENT:
        return "green"
    if status == VerificationStatus.NOT_EQUIVALENT:
        return "red"
    return "yellow"
