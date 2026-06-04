from snowprove.constraints.model import ConstraintCatalog
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.model import VerificationResult


class ExternalVerifierBackend:
    name = "external"

    def __init__(self, solver_command: str | None = None) -> None:
        self.solver_command = solver_command

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
    ) -> VerificationResult:
        del constraints
        solver = self.solver_command or "external solver"
        return VerificationResult(
            status=VerificationStatus.UNSUPPORTED,
            original_sql=original_sql.strip(),
            rewritten_sql=rewritten_sql.strip(),
            rule_name=self.name,
            reason=(
                f"{solver} integration is not implemented yet. "
                "Use --verifier builtin for Snowprove's internal verifier."
            ),
        )
