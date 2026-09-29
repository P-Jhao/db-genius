"""Render neutral metadata in the original database-document layout."""

from app.adapters.types import SchemaMetadata


def render_document(schema: SchemaMetadata) -> str:
    lines = [f"# Database: {schema['databaseName']}", "", f"- Type: {schema['dbType']}",
             f"- Host: {schema['host']}:{schema['port']}", ""]
    for table in schema["tables"]:
        lines.append(f"## Table: {table['name']}")
        if table["comment"]:
            lines.append(f"Comment: {table['comment']}")
        count = table["rowCount"] if table["rowCount"] is not None else "unknown"
        lines.extend([f"Row count: ~{count}", "", "| Column | Type | Nullable | Key | Comment |",
                      "|--------|------|----------|-----|----------|"])
        for column in table["columns"]:
            lines.append(f"| {column['name']} | {column['type']} | "
                         f"{'YES' if column['nullable'] else 'NO'} | "
                         f"{'PK' if column['primaryKey'] else ''} | {column['comment'] or ''} |")
        if table["indexes"]:
            lines.append("")
            lines.append("**Indexes:**")
            for index in table["indexes"]:
                lines.append(f"- {index['name']}: {', '.join(index['columns'])}")
        lines.extend(["", "---", ""])
    if schema["incomplete"]:
        lines.append(f"**Error reading metadata:** {schema['errorMessage'] or 'Unknown metadata error'}")
    return "\n".join(lines) + "\n"
