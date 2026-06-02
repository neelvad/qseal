from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from snowprove.constraints.dbt_loader import load_dbt_constraints
from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.dbt.project import discover_dbt_project
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.rewrites.registry import RewriteRule, first_applicable_suggestion, suggest_rewrites


class DbtModelScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    scanned_path: Path
    source_path: Path | None = None
    suggestions: tuple[RewriteSuggestion, ...] = Field(default_factory=tuple)

    def has_proven_findings(self) -> bool:
        return any(
            suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
            for suggestion in self.suggestions
        )

    def display_path(self) -> Path:
        return self.source_path or self.path

    def scanned_from_source(self) -> bool:
        return self.source_path is not None and self.source_path != self.scanned_path


class DbtScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_path: Path
    model_count: int
    results: tuple[DbtModelScanResult, ...] = Field(default_factory=tuple)

    def has_proven_findings(self) -> bool:
        return any(result.has_proven_findings() for result in self.results)


def scan_dbt_project(
    project_path: Path,
    rules: tuple[RewriteRule, ...],
    include_all: bool = False,
    compiled_path: Path | None = None,
) -> DbtScanResult:
    project = discover_dbt_project(project_path, compiled_path=compiled_path)
    constraints = _load_project_constraints(project.schema_yml_files)
    results = []

    for model_path in project.model_sql_files:
        suggestions = _scan_model(model_path, constraints, rules, include_all)
        if suggestions:
            results.append(
                DbtModelScanResult(
                    path=model_path,
                    scanned_path=model_path,
                    source_path=_source_path_for_model(project_path, compiled_path, model_path),
                    suggestions=tuple(suggestions),
                )
            )

    return DbtScanResult(
        project_path=project_path,
        model_count=len(project.model_sql_files),
        results=tuple(results),
    )


def _scan_model(
    model_path: Path,
    constraints: ConstraintCatalog,
    rules: tuple[RewriteRule, ...],
    include_all: bool,
) -> list[RewriteSuggestion]:
    sql = model_path.read_text()
    if "{{" in sql or "{%" in sql:
        return _visible_suggestions(
            [
                RewriteSuggestion(
                    rule_name="dbt_scan",
                    status=VerificationStatus.UNSUPPORTED,
                    original_sql=sql.strip(),
                    reason="Model contains dbt/Jinja syntax and must be compiled before scanning.",
                )
            ],
            include_all,
        )

    try:
        query = parse_select(sql)
    except UnsupportedSqlError as error:
        return _visible_suggestions(
            [
                RewriteSuggestion(
                    rule_name="dbt_scan",
                    status=VerificationStatus.UNSUPPORTED,
                    original_sql=sql.strip(),
                    reason=str(error),
                )
            ],
            include_all,
        )

    suggestions = suggest_rewrites(query, constraints, rules=rules)
    if include_all:
        return [
            suggestion
            for suggestion in suggestions
            if suggestion.status != VerificationStatus.NOT_APPLICABLE
        ]

    suggestion = first_applicable_suggestion(suggestions)
    if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT:
        return [suggestion]
    return []


def _visible_suggestions(
    suggestions: list[RewriteSuggestion],
    include_all: bool,
) -> list[RewriteSuggestion]:
    if include_all:
        return [
            suggestion
            for suggestion in suggestions
            if suggestion.status != VerificationStatus.NOT_APPLICABLE
        ]
    return [
        suggestion
        for suggestion in suggestions
        if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    ]


def _source_path_for_model(
    project_path: Path,
    compiled_path: Path | None,
    model_path: Path,
) -> Path | None:
    if compiled_path is None:
        return model_path

    try:
        relative = model_path.relative_to(compiled_path)
    except ValueError:
        return None

    source_path = project_path / "models" / relative
    return source_path if source_path.exists() else None


def _load_project_constraints(schema_paths: tuple[Path, ...]) -> ConstraintCatalog:
    catalogs = [load_dbt_constraints(path) for path in schema_paths]
    tables = {}
    for catalog in catalogs:
        for table_name, table in catalog.tables.items():
            existing = tables.get(table_name)
            tables[table_name] = _merge_table_constraints(existing, table)
    return ConstraintCatalog(tables=tables)


def _merge_table_constraints(
    left: TableConstraints | None,
    right: TableConstraints,
) -> TableConstraints:
    if left is None:
        return right
    return TableConstraints(
        columns={**left.columns, **right.columns},
        unique=[*left.unique, *right.unique],
    )
