from enum import StrEnum


class VerifierOutcome(StrEnum):
    PROVEN = "PROVEN"
    DISPROVEN = "DISPROVEN"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
