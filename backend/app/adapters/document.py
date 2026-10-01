"""Render neutral metadata in the original database-document layout."""

from app.adapters.types import SchemaMetadata


def render_document(schema: SchemaMetadata) -> str:
    lines = [f"# Database: {schema['databaseName']}", "", f"- Type: {schema['dbType']}",
             f"- Host: {schema['host']}:{schema['port']}", ""]
    inferred = schema.get("schemaInferred", False)
    if not isinstance(inferred, bool):
        raise TypeError("schemaInferred must be a boolean")
    sample = schema.get("sampleSize")
    if "sampleSize" in schema and (not isinstance(sample, int) or isinstance(sample, bool) or sample <= 0):
        raise TypeError("sampleSize must be a positive integer")
    if inferred:
        if sample is None:
            raise ValueError("Inferred schema requires sampleSize")
        lines.extend([(f"**Inferred schema:** at most {sample} sample documents per collection; "
                       "first-seen BSON types and estimated row counts. "
                       "This observation sample is not a complete formal schema; "
                       "fields may be missing and comparison requires manual review."), ""])
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
    if not isinstance(schema["incomplete"], bool):
        raise TypeError("incomplete must be a boolean")
    if schema["incomplete"]:
        error = schema["errorMessage"]
        if error is None or error == "":
            error = "Unknown metadata error"
        elif not isinstance(error, str):
            raise TypeError("Metadata errorMessage must be text or null")
        lines.append(f"**Error reading metadata:** {error}")
    return "\n".join(lines) + "\n"
