import re
from dataclasses import dataclass

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment, SecurityError


@dataclass(frozen=True)
class DbtSqlPreprocessResult:
    sql: str
    changed: bool
    unsupported_reason: str | None = None


_REF_PATTERN = re.compile(
    r"\{\{\s*ref\(\s*(['\"])(?P<name>[A-Za-z_][A-Za-z0-9_]*)\1\s*\)\s*\}\}"
)
_SOURCE_PATTERN = re.compile(
    r"\{\{\s*source\(\s*(['\"])(?P<source>[A-Za-z_][A-Za-z0-9_]*)\1\s*,\s*"
    r"(['\"])(?P<table>[A-Za-z_][A-Za-z0-9_]*)\3\s*\)\s*\}\}"
)
_CONFIG_PATTERN = re.compile(r"\{\{\s*config\((?P<body>.*?)\)\s*\}\}", re.DOTALL)
_JINJA_EXPRESSION_PATTERN = re.compile(r"\{\{\s*(?P<body>.*?)\s*\}\}", re.DOTALL)


def preprocess_dbt_sql(sql: str) -> DbtSqlPreprocessResult:
    """Render static dbt relation helpers without evaluating arbitrary Jinja."""
    rendered = _render_dbt_jinja(sql)
    if rendered is not None:
        return DbtSqlPreprocessResult(sql=rendered, changed=rendered != sql)

    preprocessed = _REF_PATTERN.sub(lambda match: match.group("name"), sql)
    preprocessed = _SOURCE_PATTERN.sub(
        lambda match: f"{match.group('source')}.{match.group('table')}",
        preprocessed,
    )
    preprocessed = _CONFIG_PATTERN.sub("", preprocessed)

    if "{%" in preprocessed or "{#" in preprocessed:
        return DbtSqlPreprocessResult(
            sql=preprocessed,
            changed=preprocessed != sql,
            unsupported_reason=(
                "Model contains unsupported dbt/Jinja block syntax; compile before scanning."
            ),
        )

    expression = _JINJA_EXPRESSION_PATTERN.search(preprocessed)
    if expression is not None:
        return DbtSqlPreprocessResult(
            sql=preprocessed,
            changed=preprocessed != sql,
            unsupported_reason=(
                "Model contains unsupported dbt/Jinja expression "
                f"'{_expression_name(expression.group('body'))}'; compile before scanning."
            ),
        )

    return DbtSqlPreprocessResult(
        sql=preprocessed,
        changed=preprocessed != sql,
    )


def _expression_name(expression: str) -> str:
    match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_.]*)", expression)
    return match.group(1) if match is not None else "unknown"


def _render_dbt_jinja(sql: str) -> str | None:
    """Render dbt Jinja with first-run compile semantics for known builtins.

    `is_incremental()` renders False, matching a clean-target `dbt compile`.
    Anything outside the stubbed builtins (custom macros, `var` without a
    default, `this`, `target`, `adapter`) raises through StrictUndefined and
    returns None, so the caller falls back to static preprocessing and its
    unsupported-reason reporting.
    """
    if "{{" not in sql and "{%" not in sql and "{#" not in sql:
        return None

    environment = SandboxedEnvironment(undefined=StrictUndefined)
    environment.globals.update(
        {
            "ref": lambda *args: str(args[-1]),
            "source": lambda source, table: f"{source}.{table}",
            "config": lambda *args, **kwargs: "",
            "var": _strict_var,
            "is_incremental": lambda: False,
        }
    )
    try:
        return environment.from_string(sql).render()
    except (TemplateError, SecurityError, _UnknownVarError):
        return None


class _UnknownVarError(ValueError):
    pass


_VAR_DEFAULT_SENTINEL = object()


def _strict_var(name: str, default: object = _VAR_DEFAULT_SENTINEL) -> object:
    if default is _VAR_DEFAULT_SENTINEL:
        raise _UnknownVarError(f"dbt var without default: {name}")
    return default
