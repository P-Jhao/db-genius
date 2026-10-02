"""Distinguish native sequence pseudocolumns from qualified ordinary fields."""

from collections.abc import Callable

import sqlglot
from sqlglot import exp

ReadFieldCheck = Callable[[exp.Column, exp.Expression], bool]


def _name(value: object) -> str | None:
    if not isinstance(value, exp.Identifier):
        return None
    return value.name if value.args.get("quoted") else value.name.upper()


def _source_matches(column: exp.Column, source: exp.Expression) -> bool:
    qualifier = _name(column.args.get("table"))
    alias = source.args.get("alias")
    if isinstance(alias, exp.TableAlias):
        return (column.args.get("db") is None and column.args.get("catalog") is None
                and qualifier == _name(alias.this))
    if not isinstance(source, exp.Table) or qualifier != _name(source.this):
        return False
    for part in ("db", "catalog"):
        if column.args.get(part) is not None and _name(column.args[part]) != _name(source.args.get(part)):
            return False
    return True


def _sources(query: exp.Select) -> list[exp.Expression]:
    clause = query.args.get("from_")
    sources = [clause.this] if isinstance(clause, exp.From) else []
    sources.extend(join.this for join in query.args.get("joins", []) if isinstance(join, exp.Join))
    return sources


def _projected_field(column: exp.Column, query: exp.Expression, alias: exp.TableAlias | None = None,
                     field_exists: ReadFieldCheck | None = None, seen: frozenset[int] = frozenset()) -> bool:
    expected = _name(column.this)
    if alias is not None and alias.args.get("columns"):
        return any(_name(name) == expected for name in alias.args["columns"])
    if isinstance(query, exp.SetOperation):
        return _projected_field(column, query.this, field_exists=field_exists, seen=seen)
    if not isinstance(query, exp.Select) or id(query) in seen:
        return False
    seen = seen | {id(query)}
    for value in query.expressions:
        if isinstance(value, exp.Alias) and _name(value.args.get("alias")) == expected:
            return True
        if isinstance(value, exp.Column) and _name(value.this) == expected:
            return True
        if not isinstance(value, exp.Star) and not (isinstance(value, exp.Column) and value.is_star):
            continue
        for source in _sources(query):
            if isinstance(value, exp.Column) and not _source_matches(value, source):
                continue
            if isinstance(source, exp.Subquery):
                if _projected_field(column, source.this, source.args.get("alias"), field_exists, seen):
                    return True
            elif isinstance(source, exp.Table):
                cte = _cte_source(source, query) if source.args.get("db") is None else None
                if cte is not None:
                    if _projected_field(column, cte.this, cte.args.get("alias"), field_exists, seen):
                        return True
                elif field_exists is not None and field_exists(column, source):
                    return True
    return False


def _cte_source(source: exp.Table, scope: exp.Select) -> exp.CTE | None:
    current: exp.Expression | None = scope
    while current is not None:
        clause = current.args.get("with_") if isinstance(current, (exp.Select, exp.SetOperation)) else None
        if isinstance(clause, exp.With):
            for cte in clause.expressions:
                alias = cte.args.get("alias")
                if isinstance(cte, exp.CTE) and isinstance(alias, exp.TableAlias) and _name(alias.this) == _name(source.this):
                    return cte
        current = current.parent
    return None


def _ordinary_field(column: exp.Column, field_exists: ReadFieldCheck | None) -> bool:
    # Only this SELECT's sources and its outer correlated sources are visible.
    # A same-named alias in an unrelated nested SELECT cannot authorize a sequence.
    scope = column.find_ancestor(exp.Select)
    while isinstance(scope, exp.Select):
        for source in _sources(scope):
            if not _source_matches(column, source):
                continue
            if isinstance(source, exp.Subquery):
                return _projected_field(column, source.this, source.args.get("alias"), field_exists)
            if isinstance(source, exp.Table) and source.args.get("db") is None:
                cte = _cte_source(source, scope)
                if cte is not None:
                    return _projected_field(column, cte.this, cte.args.get("alias"), field_exists)
            return field_exists is not None and field_exists(column, source)
        scope = scope.find_ancestor(exp.Select)
    return False


def sequence_read(statement: str, dialect: str, *, field_exists: ReadFieldCheck | None = None) -> bool:
    root = sqlglot.parse_one(statement, read=dialect)
    if any(isinstance(node, exp.NextValueFor) for node in root.walk()):
        return True
    if dialect != "oracle":
        return False
    return any(isinstance(column, exp.Column) and bool(column.table)
               and _name(column.this) == "NEXTVAL" and not _ordinary_field(column, field_exists)
               for column in root.find_all(exp.Column))
