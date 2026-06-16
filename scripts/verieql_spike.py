# QuerySeal spike: exercise VeriEQL as a refuter on QuerySeal's rewrite shapes.
import contextlib
import io

from constants import DIALECT
from environment import Environment


def check(name, sql1, sql2, schema, constraints, bound=2, expect=None):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            with Environment(generate_code=False, timer=False, show_counterexample=True,
                             dialect=DIALECT.MYSQL) as env:
                for table, attributes in schema.items():
                    env.create_database(attributes=attributes, bound_size=bound, name=table)
                env.add_constraints(constraints)
                env.save_checkpoints()
                result = env.analyze(sql1, sql2)
                counterexample = env.counterexample if not result else None
    except Exception as error:  # noqa: BLE001
        print(f"{name:55} ERROR: {type(error).__name__}: {str(error)[:90]}")
        return
    verdict = "BOUNDED-EQ" if result else "REFUTED"
    marker = "" if expect is None or expect == verdict else "  <<< UNEXPECTED"
    print(f"{name:55} {verdict}{marker}")
    if counterexample is not None:
        text = str(counterexample).replace("\n", " ")[:140]
        print(f"{'':55} counterexample: {text}")


USERS = {"USERS": {"USER_ID": "INT", "STATUS": "INT", "EMAIL": "INT"}}
ORDERS = {"ORDERS": {"ORDER_ID": "INT", "AMOUNT": "INT"}}
JOIN_SCHEMA = {
    "FACT_ORDERS": {"USER_ID": "INT", "REVENUE": "INT"},
    "DIM_USERS": {"USER_ID": "INT", "NAME": "INT"},
}

PK_USER = [{"primary": [{"value": "USERS__USER_ID"}]}]
# not_null takes a single attribute dict; a list of dicts crashes their encoder.
NN_EMAIL = [{"not_null": {"value": "USERS__EMAIL"}}]
PK_DIM = [{"primary": [{"value": "DIM_USERS__USER_ID"}]}]

print("== Sound rewrites (premises supplied): expect BOUNDED-EQ ==")
check(
    "distinct removal w/ primary key",
    "SELECT DISTINCT USER_ID FROM USERS",
    "SELECT USER_ID FROM USERS",
    USERS, PK_USER, expect="BOUNDED-EQ",
)
check(
    "not-null filter removal w/ not_null",
    "SELECT USER_ID FROM USERS WHERE EMAIL IS NOT NULL",
    "SELECT USER_ID FROM USERS",
    USERS, NN_EMAIL, expect="BOUNDED-EQ",
)
check(
    "unused left join elimination w/ primary key",
    "SELECT F.USER_ID, F.REVENUE FROM FACT_ORDERS F LEFT JOIN DIM_USERS U ON F.USER_ID = U.USER_ID",
    "SELECT F.USER_ID, F.REVENUE FROM FACT_ORDERS F",
    JOIN_SCHEMA, PK_DIM, expect="BOUNDED-EQ",
)
check(
    "join+distinct to exists (no premises)",
    "SELECT DISTINCT U.USER_ID FROM USERS U JOIN ORDERS O ON U.USER_ID = O.ORDER_ID",
    "SELECT U.USER_ID FROM USERS U "
    "WHERE EXISTS (SELECT 1 FROM ORDERS O WHERE U.USER_ID = O.ORDER_ID)",
    {**USERS, **ORDERS}, [], expect="BOUNDED-EQ",
)

print()
print("== Unsound rewrites (this week's pre-fix bugs): expect REFUTED ==")
check(
    "distinct removal w/o constraints",
    "SELECT DISTINCT USER_ID FROM USERS",
    "SELECT USER_ID FROM USERS",
    USERS, [], expect="REFUTED",
)
check(
    "not-null filter removal w/o constraint",
    "SELECT USER_ID FROM USERS WHERE EMAIL IS NOT NULL",
    "SELECT USER_ID FROM USERS",
    USERS, [], expect="REFUTED",
)
check(
    "left join elim w/ non-unique key",
    "SELECT F.USER_ID, F.REVENUE FROM FACT_ORDERS F LEFT JOIN DIM_USERS U ON F.USER_ID = U.USER_ID",
    "SELECT F.USER_ID, F.REVENUE FROM FACT_ORDERS F",
    JOIN_SCHEMA, [], expect="REFUTED",
)
check(
    "left join elim dropping COALESCE(u.name) projection",
    "SELECT F.USER_ID, COALESCE(U.NAME, 0) AS N FROM FACT_ORDERS F "
    "LEFT JOIN DIM_USERS U ON F.USER_ID = U.USER_ID",
    "SELECT F.USER_ID, COALESCE(0, 0) AS N FROM FACT_ORDERS F",
    JOIN_SCHEMA, PK_DIM, expect="REFUTED",
)

print()
print("== Interface limits ==")
check(
    "qualified snowflake-style names",
    'SELECT USER_ID FROM ANALYTICS.PUBLIC.USERS',
    'SELECT USER_ID FROM ANALYTICS.PUBLIC.USERS',
    USERS, [],
)
# VeriEQL silently ignores QUALIFY: a QUALIFY-filtered query is reported
# bounded-equivalent to its unfiltered form. A refuter must therefore
# refuse pairs containing QUALIFY or it produces wrong verdicts.
check(
    "QUALIFY silently ignored (filtered vs unfiltered)",
    "SELECT USER_ID FROM USERS QUALIFY ROW_NUMBER() OVER (ORDER BY USER_ID) = 1",
    "SELECT USER_ID FROM USERS",
    USERS, [],
)
check(
    "invalid SQL (dangling reference, the pre-fix broken output)",
    "SELECT F.USER_ID, COALESCE(U.NAME, 0) AS N FROM FACT_ORDERS F "
    "LEFT JOIN DIM_USERS U ON F.USER_ID = U.USER_ID",
    "SELECT F.USER_ID, COALESCE(U.NAME, 0) AS N FROM FACT_ORDERS F",
    JOIN_SCHEMA, PK_DIM,
)
