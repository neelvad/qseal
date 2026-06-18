from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from qseal.rewrites.base import RewriteSuggestion, VerificationStatus
from qseal.rewrites.registry import DEFAULT_RULES, RewriteRule, suggest_rewrites
from qseal.rewrites.subtree import suggest_subtree_rewrites

ChainStatus = Literal["FIXED_POINT", "MAX_STEPS", "CYCLE", "UNSUPPORTED"]


class RewriteChainStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_index: int
    suggestion: RewriteSuggestion


class RewriteChainResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_sql: str
    final_sql: str
    status: ChainStatus
    reason: str | None = None
    steps: tuple[RewriteChainStep, ...] = Field(default_factory=tuple)

    @property
    def step_count(self) -> int:
        return len(self.steps)


def suggest_rewrite_chain(
    sql: str,
    constraints: ConstraintCatalog,
    *,
    rules: tuple[RewriteRule, ...] = DEFAULT_RULES,
    dialect: SqlDialect = DEFAULT_DIALECT,
    max_steps: int = 8,
) -> RewriteChainResult:
    """Repeatedly apply verified rewrites until no supported step remains."""
    current_sql = sql.strip()
    seen = {_canonical_sql(current_sql)}
    steps: list[RewriteChainStep] = []

    for step_index in range(1, max_steps + 1):
        next_step = _next_proven_step(
            current_sql,
            constraints,
            rules=rules,
            dialect=dialect,
        )
        if isinstance(next_step, str):
            status: ChainStatus = "UNSUPPORTED" if not steps else "FIXED_POINT"
            return RewriteChainResult(
                original_sql=sql.strip(),
                final_sql=current_sql,
                status=status,
                reason=(
                    next_step
                    if not steps
                    else f"No further verified rewrites apply: {next_step}"
                ),
                steps=tuple(steps),
            )
        if next_step is None:
            return RewriteChainResult(
                original_sql=sql.strip(),
                final_sql=current_sql,
                status="FIXED_POINT",
                reason="No further verified rewrites apply.",
                steps=tuple(steps),
            )

        rewritten_sql = next_step.rewritten_sql
        if rewritten_sql is None:
            return RewriteChainResult(
                original_sql=sql.strip(),
                final_sql=current_sql,
                status="FIXED_POINT",
                reason="Verified rewrite did not produce rewritten SQL.",
                steps=tuple(steps),
            )

        canonical = _canonical_sql(rewritten_sql)
        if canonical in seen:
            return RewriteChainResult(
                original_sql=sql.strip(),
                final_sql=current_sql,
                status="CYCLE",
                reason="Rewrite chain reached a previously seen SQL state.",
                steps=tuple(steps),
            )

        steps.append(RewriteChainStep(step_index=step_index, suggestion=next_step))
        seen.add(canonical)
        current_sql = rewritten_sql.strip()

    return RewriteChainResult(
        original_sql=sql.strip(),
        final_sql=current_sql,
        status="MAX_STEPS",
        reason=f"Stopped after {max_steps} verified rewrite steps.",
        steps=tuple(steps),
    )


def _next_proven_step(
    sql: str,
    constraints: ConstraintCatalog,
    *,
    rules: tuple[RewriteRule, ...],
    dialect: SqlDialect,
) -> RewriteSuggestion | str | None:
    parse_error = None
    try:
        query = parse_select(sql, dialect=dialect)
    except UnsupportedSqlError as error:
        parse_error = str(error)
    else:
        for suggestion in suggest_rewrites(query, constraints, rules=rules):
            if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT:
                return suggestion

    subtree = suggest_subtree_rewrites(
        sql,
        constraints,
        rules=rules,
        dialect=dialect,
    )
    if subtree:
        return subtree[0]
    return parse_error


def _canonical_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").split()).lower()
