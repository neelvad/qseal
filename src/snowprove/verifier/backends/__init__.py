from snowprove.verifier.backends.base import VerifierBackend
from snowprove.verifier.backends.builtin import BuiltinVerifierBackend


def get_verifier_backend(name: str) -> VerifierBackend:
    if name == BuiltinVerifierBackend.name:
        return BuiltinVerifierBackend()
    raise ValueError(f"Unknown verifier backend: {name}")
