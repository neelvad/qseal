from pydantic import BaseModel, ConfigDict, Field


class ColumnConstraint(BaseModel):
    nullable: bool | None = None


class TableConstraints(BaseModel):
    columns: dict[str, ColumnConstraint] = Field(default_factory=dict)
    unique: list[tuple[str, ...]] = Field(default_factory=list)

    def has_unique_key(self, columns: tuple[str, ...]) -> bool:
        requested = set(columns)
        return any(set(key) <= requested for key in self.unique)


class ConstraintCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    tables: dict[str, TableConstraints] = Field(default_factory=dict)

    def table(self, name: str) -> TableConstraints | None:
        return self.tables.get(name)
