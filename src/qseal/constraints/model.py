from pydantic import BaseModel, ConfigDict, Field


class ColumnConstraint(BaseModel):
    nullable: bool | None = None


class TableConstraints(BaseModel):
    columns: dict[str, ColumnConstraint] = Field(default_factory=dict)
    # Unique keys use SQL/dbt-test semantics: rows where a key column is NULL are
    # exempt, so duplicate NULL rows may exist unless the columns are also non-null.
    unique: list[tuple[str, ...]] = Field(default_factory=list)

    def has_unique_key(self, columns: tuple[str, ...]) -> bool:
        requested = set(columns)
        return any(set(key) <= requested for key in self.unique)

    def has_non_null_unique_key(self, columns: tuple[str, ...]) -> bool:
        requested = set(columns)
        return any(
            set(key) <= requested and all(self.is_non_null(column) for column in key)
            for key in self.unique
        )

    def is_non_null(self, column: str) -> bool:
        constraint = self.columns.get(column)
        return constraint is not None and constraint.nullable is False


class ConstraintCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    tables: dict[str, TableConstraints] = Field(default_factory=dict)

    def table(self, name: str) -> TableConstraints | None:
        return self.tables.get(name)
