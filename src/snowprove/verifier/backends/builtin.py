from snowprove.constraints.model import ConstraintCatalog
from snowprove.dialects import DEFAULT_DIALECT, SqlDialect
from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.check import check_equivalence
from snowprove.verifier.model import VerificationResult


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

        return check_equivalence(original, rewritten, constraints)
