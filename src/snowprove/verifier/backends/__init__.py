from snowprove.verifier.backends.base import VerifierBackend
from snowprove.verifier.backends.builtin import BuiltinVerifierBackend
from snowprove.verifier.backends.external import ExternalVerifierBackend
from snowprove.verifier.backends.sqlsolver import SqlSolverBackend


def get_verifier_backend(
    name: str,
    solver_command: str | None = None,
    timeout_seconds: int | None = None,
) -> VerifierBackend:
    if name == BuiltinVerifierBackend.name:
        return BuiltinVerifierBackend()
    if name == ExternalVerifierBackend.name:
        return ExternalVerifierBackend(
            solver_command=solver_command,
            timeout_seconds=timeout_seconds,
        )
    if name == SqlSolverBackend.name:
        return SqlSolverBackend(
            solver_command=solver_command,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unknown verifier backend: {name}")
