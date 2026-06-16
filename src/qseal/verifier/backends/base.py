from typing import Protocol

from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.verifier.model import VerificationResult


class VerifierBackend(Protocol):
    name: str

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
        dialect: SqlDialect = DEFAULT_DIALECT,
    ) -> VerificationResult:
        pass
