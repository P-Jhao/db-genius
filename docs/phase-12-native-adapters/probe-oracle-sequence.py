"""Direct-driver evidence of quoted pseudocolumn side effects; random objects only."""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import oracledb

PHASE = Path(__file__).resolve().parent
sys.path.insert(0, str(PHASE.parents[1] / "backend/tests"))
from native_database_fixtures import runtime_values


def main() -> None:
    values = runtime_values("SQLCHAT_ORACLE_RUNTIME")
    sequence = "probe_seq_" + uuid4().hex[:12]
    table = "probe_cols_" + uuid4().hex[:12]
    records: list[dict[str, object]] = []
    with oracledb.connect(host=values["ORACLE_HOST"], port=int(values["ORACLE_PORT"]),
                          service_name=values["ORACLE_SERVICE"], user=values["ORACLE_USERNAME"],
                          password=values["ORACLE_PASSWORD"]) as connection:
        connection.call_timeout = 5000
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SEQUENCE {sequence} NOCACHE")
            table_created = False
            try:
                cursor.execute(f'CREATE TABLE {table} ("NEXTVAL" NUMBER, "nextval" NUMBER)')
                table_created = True
                cursor.execute(f"INSERT INTO {table} VALUES (701,702)")
                connection.commit()
                def next_number() -> object:
                    cursor.execute("SELECT last_number FROM user_sequences WHERE sequence_name=:name",
                                   name=sequence.upper())
                    row = cursor.fetchone()
                    if row is None:
                        raise ValueError("Probe sequence is absent from the current-user catalog")
                    return row[0]
                statements = [
                    ("unquoted", f"SELECT {sequence}.NEXTVAL FROM DUAL"),
                    ("quoted_upper", f'SELECT {sequence}."NEXTVAL" FROM DUAL'),
                    ("quoted_lower", f'SELECT {sequence}."nextval" FROM DUAL'),
                    ("dual_alias_collision", f'SELECT {sequence}."NEXTVAL" FROM DUAL {sequence}'),
                    ("field_alias_collision", f'SELECT {sequence}."NEXTVAL" FROM {table} {sequence}'),
                    ("ordinary_fields", f'SELECT {table}.NEXTVAL,{table}."NEXTVAL",{table}."nextval" FROM {table}'),
                    ("ordinary_alias", f'SELECT t."NEXTVAL" FROM {table} t'),
                ]
                for label, statement in statements:
                    before = next_number()
                    record: dict[str, object] = {"label": label, "statement": statement, "next_before": before}
                    try:
                        cursor.execute(statement)
                        record["rows"] = cursor.fetchall()
                    except oracledb.Error as error:
                        record["code"] = getattr(error.args[0], "full_code", "unknown")
                    record["next_after"] = next_number()
                    records.append(record)
            finally:
                if table_created:
                    cursor.execute(f"DROP TABLE {table} PURGE")
                cursor.execute(f"DROP SEQUENCE {sequence}")
    output = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    (PHASE / f"oracle-sequence-probe-{uuid4().hex}.json").write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    if "SQLCHAT_ORACLE_RUNTIME" not in os.environ:
        raise ValueError("Pass the ignored runtime path in SQLCHAT_ORACLE_RUNTIME")
    main()
