from snowprove.verifier.backends.base import VerifierBackend
from snowprove.verifier.backends.builtin import BuiltinVerifierBackend
from snowprove.verifier.backends.external import ExternalVerifierBackend


def get_verifier_backend(
    name: str,
    solver_command: str | None = None,
) -> VerifierBackend:
    if name == BuiltinVerifierBackend.name:
        return BuiltinVerifierBackend()
    if name == ExternalVerifierBackend.name:
        return ExternalVerifierBackend(solver_command=solver_command)
    raise ValueError(f"Unknown verifier backend: {name}")
