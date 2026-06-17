from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AcceptedValue(BaseModel):
    value: str
    is_string: bool = True


class ColumnConstraint(BaseModel):
    nullable: bool | None = None
    accepted_values: tuple[AcceptedValue, ...] = Field(default_factory=tuple)

    @field_validator("accepted_values", mode="before")
    @classmethod
    def _coerce_accepted_values(cls, value: Any) -> Any:
        if value in (None, ""):
            return ()
        if not isinstance(value, list | tuple):
            return value
        return tuple(_accepted_value_payload(item) for item in value)


def _accepted_value_payload(value: Any) -> Any:
    if isinstance(value, AcceptedValue | dict):
        return value
    if isinstance(value, str):
        return {"value": value, "is_string": True}
    return {"value": str(value), "is_string": False}


class ForeignKeyConstraint(BaseModel):
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


class TableConstraints(BaseModel):
    columns: dict[str, ColumnConstraint] = Field(default_factory=dict)
    # Unique keys use SQL/dbt-test semantics: rows where a key column is NULL are
    # exempt, so duplicate NULL rows may exist unless the columns are also non-null.
    unique: list[tuple[str, ...]] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyConstraint] = Field(default_factory=list)

    def has_unique_key(self, columns: tuple[str, ...]) -> bool:
        return self.unique_key_contained_in(columns) is not None

    def unique_key_contained_in(self, columns: tuple[str, ...]) -> tuple[str, ...] | None:
        requested = set(columns)
        for key in self.unique:
            if set(key) <= requested:
                return key
        return None

    def has_non_null_unique_key(self, columns: tuple[str, ...]) -> bool:
        return self.non_null_unique_key_contained_in(columns) is not None

    def non_null_unique_key_contained_in(
        self,
        columns: tuple[str, ...],
    ) -> tuple[str, ...] | None:
        requested = set(columns)
        for key in self.unique:
            if set(key) <= requested and all(self.is_non_null(column) for column in key):
                return key
        return None

    def is_non_null(self, column: str) -> bool:
        constraint = self.columns.get(column)
        return constraint is not None and constraint.nullable is False

    def has_foreign_key(
        self,
        columns: tuple[str, ...],
        *,
        ref_table: str,
        ref_columns: tuple[str, ...],
    ) -> bool:
        return any(
            foreign_key.columns == columns
            and foreign_key.ref_table == ref_table
            and foreign_key.ref_columns == ref_columns
            for foreign_key in self.foreign_keys
        )


class ConstraintCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    tables: dict[str, TableConstraints] = Field(default_factory=dict)

    def table(self, name: str) -> TableConstraints | None:
        return self.tables.get(name)
