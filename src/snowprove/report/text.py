from rich.text import Text

from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus


def render_suggestion_report(suggestion: RewriteSuggestion) -> Text:
    output = Text()
    style = "green" if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT else "yellow"

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
