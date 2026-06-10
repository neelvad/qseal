# Runs inside a VeriEQL checkout's virtualenv (PYTHONPATH set by the caller).
# Reads a JSON request on argv[1] and prints a JSON verdict to stdout.
#
# Request: {"sql1": str, "sql2": str, "schema": {table: {column: type}},
#           "constraints": [...], "bound": int}
# Verdict: {"result": "refuted" | "bounded_ok" | "unsupported",
#           "counterexample": str | null, "reason": str | null, "bound": int}
import contextlib
import io
import json
import sys


def main() -> None:
    with open(sys.argv[1]) as handle:
        request = json.load(handle)

    from constants import DIALECT
    from environment import Environment

    bound = int(request.get("bound", 2))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            with Environment(
                generate_code=False,
                timer=False,
                show_counterexample=True,
                dialect=DIALECT.MYSQL,
            ) as env:
                for table, attributes in request["schema"].items():
                    env.create_database(attributes=attributes, bound_size=bound, name=table)
                env.add_constraints(request.get("constraints") or None)
                env.save_checkpoints()
                equivalent = env.analyze(request["sql1"], request["sql2"])
                counterexample = None if equivalent else str(env.counterexample)
    except Exception as error:  # noqa: BLE001 - any VeriEQL failure means abstain
        print(
            json.dumps(
                {
                    "result": "unsupported",
                    "counterexample": None,
                    "reason": f"{type(error).__name__}: {error}",
                    "bound": bound,
                }
            )
        )
        return

    print(
        json.dumps(
            {
                "result": "bounded_ok" if equivalent else "refuted",
                "counterexample": counterexample,
                "reason": None,
                "bound": bound,
            }
        )
    )


if __name__ == "__main__":
    main()
