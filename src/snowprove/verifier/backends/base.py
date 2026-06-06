from typing import Protocol

from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.verifier.model import VerificationResult


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
