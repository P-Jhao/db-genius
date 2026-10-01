"""SQL facts used by workflow verification; independent of model observations."""

from collections import Counter
from decimal import Decimal

from sqlglot import exp, parse_one

from app.agent.workflow_schema import column_name
from app.agent.workflow_values import ColumnTypes, Row, RowKey, covers, key

__all__ = ["Row", "covers", "expression", "insert_values", "is_insert", "is_select",
           "merge_observations", "ordered_page", "rows", "schema_mutation", "tables",
           "verifies_columns", "write_tables"]


def expression(statement: str, dialect: str | None = None) -> exp.Expression:
    try:
        return parse_one(statement, read=dialect)
    except Exception as error:
        raise ValueError("Workflow SQL could not be parsed for verification") from error


def is_select(statement: str, dialect: str | None = None) -> bool:
    parsed = expression(statement, dialect)
    return isinstance(parsed, exp.Select) and not any(
        isinstance(node, (exp.Into, exp.Insert, exp.Update, exp.Delete, exp.Create)) for node in parsed.walk()
    )


def is_insert(statement: str, dialect: str | None = None) -> bool:
    return isinstance(expression(statement, dialect), exp.Insert)


def tables(statement: str, dialect: str | None = None) -> list[exp.Table]:
    parsed = expression(statement, dialect)
    aliases = {column_name(alias.this, dialect) for cte in parsed.find_all(exp.CTE)
               if isinstance(alias := cte.args.get("alias"), exp.TableAlias)}
    return [table for table in parsed.find_all(exp.Table)
            if table.db or table.catalog or column_name(table.this, dialect) not in aliases]


def write_tables(statement: str, dialect: str | None = None) -> list[exp.Table]:
    parsed = expression(statement, dialect)
    targets: list[exp.Table] = []
    for node in parsed.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Alter, exp.Into)):
            target = node.this.this if isinstance(node.this, exp.Schema) else node.this
            if isinstance(target, exp.Table):
                targets.append(target)
    return targets


def schema_mutation(statement: str, dialect: str | None = None) -> bool:
    return isinstance(expression(statement, dialect), (exp.Create, exp.Alter))


def insert_values(statement: str, headers: list[str], dialect: str | None = None) -> list[Row]:
    parsed = expression(statement, dialect)
    if not isinstance(parsed, exp.Insert) or not isinstance(parsed.expression, exp.Values):
        return []
    columns = ([column_name(column, dialect) for column in parsed.this.expressions]
               if isinstance(parsed.this, exp.Schema) else headers)
    if not columns:
        return []
    rows: list[Row] = []
    for tuple_value in parsed.expression.expressions:
        if not isinstance(tuple_value, exp.Tuple) or len(tuple_value.expressions) != len(columns):
            return []
        values: list[object] = []
        for value in tuple_value.expressions:
            if isinstance(value, exp.Literal):
                values.append(value.this if value.is_string else Decimal(value.this))
            elif isinstance(value, exp.Null):
                values.append(None)
            elif isinstance(value, exp.Boolean):
                values.append(value.this)
            elif isinstance(value, exp.Neg) and isinstance(value.this, exp.Literal):
                values.append(-Decimal(value.this.this))
            else:
                return []
        if dialect in ("mysql", "sqlite"):
            columns = [column.lower() for column in columns]
        rows.append(dict(zip(columns, values, strict=True)))
    return rows


def rows(value: object, dialect: str | None = None) -> list[Row]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise TypeError("Workflow row data must be an array of objects")
    result: list[Row] = []
    for row in value:
        converted: Row = {}
        for name, item in row.items():
            if not isinstance(name, str):
                raise TypeError("Workflow column names must be strings")
            normalized = name.lower() if dialect in ("mysql", "sqlite") else name
            if normalized in converted:
                raise ValueError("Workflow column names collide under the target dialect")
            converted[normalized] = item
        result.append(converted)
    return result


def verifies_columns(statement: str, expected: set[str], dialect: str | None = None) -> bool:
    """Computed/literal output cannot substitute for observing the stored target values."""
    parsed = expression(statement, dialect)
    source = parsed.args.get("from_")
    if (not isinstance(parsed, exp.Select) or not isinstance(source, exp.From) or
            not isinstance(source.this, exp.Table) or parsed.find(exp.Subquery, exp.CTE) is not None):
        return False
    selected: set[str] = set()
    for item in parsed.expressions:
        if isinstance(item, exp.Star) or (isinstance(item, exp.Column) and isinstance(item.this, exp.Star)):
            return True
        value = item.this if isinstance(item, exp.Alias) else item
        if isinstance(value, exp.Column):
            name = column_name(value.this, dialect)
            if not isinstance(item, exp.Alias) or column_name(item.args["alias"], dialect) == name:
                selected.add(name)
    return expected.issubset(selected)


def merge_observations(previous: list[Row], current: list[Row],
                       column_types: ColumnTypes | None = None) -> list[Row]:
    """Union observations with maximum multiplicity; overlapping pages cannot fake coverage."""
    counts = Counter(key(row, column_types) for row in previous)
    current_counts: Counter[RowKey] = Counter()
    result = previous.copy()
    for row in current:
        signature = key(row, column_types)
        current_counts[signature] += 1
        if current_counts[signature] > counts[signature]:
            result.append(row)
    return result


def ordered_page(statement: str, columns: set[str], count: int,
                 dialect: str | None = None) -> tuple[str, int, int] | None:
    """Identify disjoint windows ordered by every compared value, including duplicate rows."""
    parsed = expression(statement, dialect)
    order = parsed.args.get("order")
    if not isinstance(order, exp.Order) or count == 0:
        return None
    ordered = {column_name(item.this.this, dialect) for item in order.expressions
               if isinstance(item, exp.Ordered) and isinstance(item.this, exp.Column)}
    if not columns.issubset(ordered):
        return None
    offset = parsed.args.get("offset")
    start = 0
    if offset is not None:
        value = offset.expression
        if not isinstance(value, exp.Literal) or not value.is_int:
            return None
        start = int(value.this)
        if start < 0:
            return None
    parsed.set("offset", None)
    parsed.set("limit", None)
    return parsed.sql(dialect=dialect), start, start + count
