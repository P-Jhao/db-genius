"""One completion gate for SQL direct answers and terminal summaries."""

from app.agent.product_locale import product_text
from app.agent.sql_outcome import zero_execution_summary
from app.agent.tools import RunTools


def completion_override(tools: RunTools, message: str, locale: str) -> str | None:
    goal = tools.task_goal
    if goal is None:
        raise RuntimeError("SQL completion requires an analyzed task goal")
    if goal.mode == "metadata_only":
        evidence = tools.schema_evidence.status(goal)
        if evidence["complete"] is True:
            return None
        databases = evidence["databases"]
        if not isinstance(databases, list):
            raise TypeError("Schema evidence databases must be an array")
        details = []
        for database in databases:
            if not isinstance(database, dict):
                raise TypeError("Schema evidence database must be an object")
            scope = database["tables"]
            if scope is None:
                target = product_text("chat.schema.allTables", locale)
            elif isinstance(scope, list):
                target = ", ".join(str(name) for name in scope)
            else:
                raise TypeError("Schema evidence table scope is invalid")
            observed = ", ".join(str(name) for name in database["observedTables"])
            details.append(product_text("chat.schema.scope", locale, database["dbId"], target, observed))
            if database["complete"] is not True:
                details.append(product_text("chat.schema.limitation", locale,
                                            database["limitation"], ", ".join(database["missingTables"])))
        return product_text("chat.schema.incomplete", locale) + "\n" + "\n".join(details)
    if tools.statements_executed == 0:
        return zero_execution_summary(message if tools.statements_attempted == 0 else "",
                                      locale, tools.statement_errors)
    return None
