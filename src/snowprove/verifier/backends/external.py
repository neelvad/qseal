from snowprove.constraints.model import ConstraintCatalog
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.external_contract import ExternalSolverRequest
from snowprove.verifier.model import VerificationResult


class ExternalVerifierBackend:
    name = "external"

    def __init__(
        self,
        solver_command: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.solver_command = solver_command
        self.timeout_seconds = timeout_seconds

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
    ) -> VerificationResult:
        request = ExternalSolverRequest(
            original_sql=original_sql,
            rewritten_sql=rewritten_sql,
            constraints=constraints,
            solver_command=self.solver_command,
            timeout_seconds=self.timeout_seconds,
        )
        solver = self.solver_command or "external solver"
        return VerificationResult(
            status=VerificationStatus.UNSUPPORTED,
            original_sql=request.normalized_original_sql(),
            rewritten_sql=request.normalized_rewritten_sql(),
            rule_name=self.name,
            reason=(
                f"{solver} integration is not implemented yet. "
                "Use --verifier builtin for Snowprove's internal verifier."
            ),
        )
