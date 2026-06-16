# QED spike: convert SQLSolver-UNKNOWN LLM candidates into QED input files.
#
# Reuses the VeriEQL backend's schema attribution to build CREATE TABLE DDL.
# Premise discipline matches the other solvers: uniqueness is emitted only
# when the key columns are also trusted non-null (QED treats UNIQUE as strict,
# including NULLs - verified by spike case 02).
#
#   uv run python scripts/qed_spike_unknowns.py REPORT_B.json BUNDLES_DIR OUT_DIR
import json
import sys
from pathlib import Path

from qseal.constraints.model import ConstraintCatalog
from qseal.verifier.backends.sqlsolver import _unqualify_relations
from qseal.verifier.backends.verieql import _build_request


def main() -> int:
    report_path, bundles_dir, out_dir = (Path(arg) for arg in sys.argv[1:4])
    report = json.loads(report_path.read_text())
    constraints = ConstraintCatalog.model_validate_json(
        (bundles_dir / "constraints.json").read_text()
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = {}
    for row in report["results"]:
        if row["bucket"] != "unknown":
            continue
        bundle = bundles_dir / row["model"]
        original = (bundle / "original.sql").read_text()
        candidate = (bundle / row["candidate"]).read_text()

        normalized = _unqualify_relations(original, candidate, "snowflake")
        if normalized is None:
            skipped["name collision"] = skipped.get("name collision", 0) + 1
            continue
        # Reuse VeriEQL's schema/premise extraction for table -> columns and
        # the abstention discipline; ignore its VeriEQL-specific constraints.
        request = _build_request(*normalized, constraints, "snowflake", 2)
        if isinstance(request, str):
            skipped[request[:60]] = skipped.get(request[:60], 0) + 1
            continue

        ddl = []
        for table, columns in request["schema"].items():
            table_constraints = constraints.table(table.lower())
            column_defs = []
            non_null = set()
            unique_keys = []
            if table_constraints is not None:
                non_null = {
                    column
                    for column, constraint in table_constraints.columns.items()
                    if constraint.nullable is False
                }
                unique_keys = [
                    key
                    for key in table_constraints.unique
                    if all(column in non_null for column in key)
                ]
            for column in columns:
                suffix = " not null" if column.lower() in non_null else ""
                column_defs.append(f"  {column.lower()} integer{suffix}")
            for key in unique_keys:
                column_defs.append(f"  unique ({', '.join(key)})")
            ddl.append(
                f"create table {table.lower()} (\n" + ",\n".join(column_defs) + "\n);"
            )

        name = f"{row['model']}__{row['candidate'].removesuffix('.sql')}"
        sql1, sql2 = (sql.rstrip().rstrip(";") for sql in normalized)
        (out_dir / f"{name}.sql").write_text(
            "\n".join(ddl) + f"\n\n{sql1};\n\n{sql2};\n"
        )
        written += 1

    print(json.dumps({"written": written, "skipped": skipped}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
