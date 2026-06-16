from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import DEFAULT_DIALECT, SqlDialect
from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.check import check_equivalence
from qseal.verifier.model import VerificationResult


class BuiltinVerifierBackend:
    name = "builtin"

    def verify(
        self,
        original_sql: str,
        rewritten_sql: str,
        constraints: ConstraintCatalog,
        dialect: SqlDialect = DEFAULT_DIALECT,
    ) -> VerificationResult:
        try:
            original = parse_select(original_sql, dialect=dialect)
        except UnsupportedSqlError as error:
            return VerificationResult(
                status=VerificationStatus.UNSUPPORTED,
                original_sql=original_sql.strip(),
                rewritten_sql=rewritten_sql.strip(),
                reason=f"Original query unsupported: {error}",
            )

        try:
            rewritten = parse_select(rewritten_sql, dialect=dialect)
        except UnsupportedSqlError as error:
            return VerificationResult(
                status=VerificationStatus.UNSUPPORTED,
                original_sql=original_sql.strip(),
                rewritten_sql=rewritten_sql.strip(),
                reason=f"Rewritten query unsupported: {error}",
            )

        result = check_equivalence(original, rewritten, constraints)
        if result.status == VerificationStatus.PROVEN_EQUIVALENT:
            method = (
                "builtin_normalized_identity"
                if result.rule_name == "normalized_identity"
                else "builtin_rule_replay"
            )
            claim = (
                "NORMALIZED_IDENTITY"
                if result.rule_name == "normalized_identity"
                else "VERIFIED_BY_RULE"
            )
            reason = result.reason
            if result.rule_name != "normalized_identity" and reason:
                reason = f"Builtin verifier matched a supported rewrite rule. {reason}"
            elif result.rule_name != "normalized_identity":
                reason = "Builtin verifier matched a supported rewrite rule."
            return result.model_copy(
                update={
                    "verification_method": method,
                    "safety_claim": claim,
                    "reason": reason,
                }
            )
        return result.model_copy(update={"verification_method": "builtin_rule_replay"})
