from typing import Protocol

from snowprove.constraints.model import ConstraintCatalog
from snowprove.verifier.model import VerificationResult


class VerifierBackend(Protocol):
    name: str

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
    ) -> VerificationResult:
        pass
