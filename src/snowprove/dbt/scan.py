from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from snowprove.constraints.dbt_loader import load_dbt_constraints
from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.dbt.jinja import preprocess_dbt_sql
from snowprove.dbt.project import discover_dbt_project
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.rewrites.base import RewriteSuggestion, VerificationStatus
from snowprove.rewrites.registry import RewriteRule, first_applicable_suggestion, suggest_rewrites
from snowprove.rewrites.subtree import suggest_subtree_rewrites


class DbtModelScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    scanned_path: Path
    source_path: Path | None = None
    source_sql_preprocessed: bool = False
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

    def apply_ready(self) -> bool:
        return (
            self.has_proven_findings()
            and self.source_path == self.scanned_path
            and not self.source_sql_preprocessed
        )

    def apply_blocker(self) -> str | None:
        if self.apply_ready():
            return None
        if not self.has_proven_findings():
            return "No proven rewrite finding."
        if self.source_sql_preprocessed:
            return (
                "Source SQL was normalized before verification; "
                "source file was not verified directly."
            )
        if self.source_path is None:
            return "No matching source model file."
        if self.source_path != self.scanned_path:
            return "Scanned compiled SQL; source file was not verified directly."
        return None


class DbtScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_path: Path
    dialect: SqlDialect = DEFAULT_DIALECT
    model_count: int
    results: tuple[DbtModelScanResult, ...] = Field(default_factory=tuple)

    def has_proven_findings(self) -> bool:
        return any(result.has_proven_findings() for result in self.results)

    def proven_finding_count(self) -> int:
        return sum(
            1
            for result in self.results
            for suggestion in result.suggestions
            if suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
        )

    def status_counts(self) -> dict[str, int]:
        counts = {}
        for result in self.results:
            for suggestion in result.suggestions:
                counts[suggestion.status.value] = counts.get(suggestion.status.value, 0) + 1
        return counts

    def rule_counts(self) -> dict[str, int]:
        counts = {}
        for result in self.results:
            for suggestion in result.suggestions:
                counts[suggestion.rule_name] = counts.get(suggestion.rule_name, 0) + 1
        return counts

    def reason_counts(self) -> dict[str, int]:
        counts = {}
        for result in self.results:
            for suggestion in result.suggestions:
                if suggestion.reason:
                    counts[suggestion.reason] = counts.get(suggestion.reason, 0) + 1
        return counts

    def summary(self) -> dict[str, object]:
        return {
            "model_count": self.model_count,
            "result_count": len(self.results),
            "proven_finding_count": self.proven_finding_count(),
            "status_counts": self.status_counts(),
            "rule_counts": self.rule_counts(),
            "reason_counts": self.reason_counts(),
        }


def scan_dbt_project(
    project_path: Path,
    rules: tuple[RewriteRule, ...],
    include_all: bool = False,
    compiled_path: Path | None = None,
    dialect: SqlDialect = DEFAULT_DIALECT,
) -> DbtScanResult:
    project = discover_dbt_project(project_path, compiled_path=compiled_path)
    constraints = _load_project_constraints(project.schema_yml_files)
    results = []

    for model_path in project.model_sql_files:
        suggestions = _scan_model(model_path, constraints, rules, include_all, dialect)
        if suggestions:
            source_sql = model_path.read_text()
            preprocessed = preprocess_dbt_sql(source_sql)
            source_sql_preprocessed = preprocessed.changed or _has_with_clause(preprocessed.sql)
            results.append(
                DbtModelScanResult(
                    path=model_path,
                    scanned_path=model_path,
                    source_path=_source_path_for_model(project_path, compiled_path, model_path),
                    source_sql_preprocessed=(
                        source_sql_preprocessed and compiled_path is None
                    ),
                    suggestions=tuple(suggestions),
                )
            )

    return DbtScanResult(
        project_path=project_path,
        dialect=dialect,
        model_count=len(project.model_sql_files),
        results=tuple(results),
    )


def _scan_model(
    model_path: Path,
    constraints: ConstraintCatalog,
    rules: tuple[RewriteRule, ...],
    include_all: bool,
    dialect: SqlDialect,
) -> list[RewriteSuggestion]:
    source_sql = model_path.read_text()
    preprocessed = preprocess_dbt_sql(source_sql)
    if preprocessed.unsupported_reason is not None:
        return _visible_suggestions(
            [
                RewriteSuggestion(
                    rule_name="dbt_scan",
                    status=VerificationStatus.UNSUPPORTED,
                    original_sql=source_sql.strip(),
                    reason=preprocessed.unsupported_reason,
                )
            ],
            include_all,
        )

    try:
        query = parse_select(preprocessed.sql, dialect=dialect)
    except UnsupportedSqlError as error:
        subtree = suggest_subtree_rewrites(
            preprocessed.sql,
            constraints,
            rules=rules,
            dialect=dialect,
        )
        if subtree:
            return subtree if include_all else [subtree[0]]
        return _visible_suggestions(
            [
                RewriteSuggestion(
                    rule_name="dbt_scan",
                    status=VerificationStatus.UNSUPPORTED,
                    original_sql=source_sql.strip(),
                    reason=str(error),
                )
            ],
            include_all,
        )

    suggestions = suggest_rewrites(query, constraints, rules=rules)
    has_proven = any(
        suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
        for suggestion in suggestions
    )
    # Whole-query rules cannot see inside opaque CTE bodies, so fall back to
    # fragment rewrites when the whole query proves nothing.
    subtree = []
    if not has_proven:
        subtree = suggest_subtree_rewrites(
            preprocessed.sql,
            constraints,
            rules=rules,
            dialect=dialect,
        )

    if include_all:
        return [
            *subtree,
            *(
                suggestion
                for suggestion in suggestions
                if suggestion.status != VerificationStatus.NOT_APPLICABLE
            ),
        ]

    if subtree:
        return [subtree[0]]
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

    relative = _compiled_model_relative_path(compiled_path, model_path)
    if relative is None:
        return None

    source_path = project_path / "models" / relative
    return source_path if source_path.exists() else None


def _compiled_model_relative_path(compiled_path: Path, model_path: Path) -> Path | None:
    try:
        relative = model_path.relative_to(compiled_path)
    except ValueError:
        return None

    if relative.parts and relative.parts[0] == "models":
        return Path(*relative.parts[1:])

    if "models" in relative.parts:
        models_index = relative.parts.index("models")
        return Path(*relative.parts[models_index + 1 :])

    return relative


def _has_with_clause(sql: str) -> bool:
    return sql.lstrip().lower().startswith("with")


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
