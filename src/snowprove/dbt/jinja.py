import re
from dataclasses import dataclass


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
