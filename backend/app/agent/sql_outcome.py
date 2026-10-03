"""Authoritative zero-execution SQL outcomes for explicit forbidden requests."""

import re

from app.adapters.safety import UnsafeStatement, check_statement
from app.core.localization import select_locale

_SQL_COMMAND = (
    r"(?:DROP\s+(?:TABLE|DATABASE|SCHEMA)\s+|TRUNCATE\s+(?:TABLE\s+)?|"
    r"ALTER\s+TABLE\s+\S+\s+DROP\s+(?:COLUMN\s+)?)"
    r"(?:[`\"\[]?[A-Za-z_][\w.]*[`\"\]]?)"
)
_EXECUTE_REQUEST = re.compile(
    r"\A\s*(?:(?:请执行|执行)\s*|(?:please\s+execute|execute|run)\s+)"
    rf"(?P<sql>{_SQL_COMMAND})",
    re.IGNORECASE,
)
_DIRECT_COMMAND = re.compile(rf"\A\s*(?P<sql>{_SQL_COMMAND})\s*;?\s*\Z", re.IGNORECASE)

_REFUSAL = {
    "en": "I cannot execute the requested DROP, TRUNCATE, or ALTER ... DROP operation. It is forbidden by the database safety rules; no statement was executed.",
    "zh-CN": "无法执行请求的 DROP、TRUNCATE 或 ALTER ... DROP 操作：数据库安全规则禁止该操作；没有执行任何语句。",
    "zh-TW": "無法執行要求的 DROP、TRUNCATE 或 ALTER ... DROP 操作：資料庫安全規則禁止該操作；未執行任何語句。",
    "fr": "Je ne peux pas exécuter l'opération DROP, TRUNCATE ou ALTER ... DROP demandée : les règles de sécurité de la base de données l'interdisent. Aucune instruction n'a été exécutée.",
    "ms": "Saya tidak boleh melaksanakan operasi DROP, TRUNCATE atau ALTER ... DROP yang diminta: peraturan keselamatan pangkalan data melarangnya. Tiada pernyataan dilaksanakan.",
    "ja": "要求された DROP、TRUNCATE、または ALTER ... DROP 操作は、データベースの安全規則で禁止されているため実行できません。文は実行されていません。",
    "es": "No puedo ejecutar la operación DROP, TRUNCATE o ALTER ... DROP solicitada: las reglas de seguridad de la base de datos la prohíben. No se ejecutó ninguna sentencia.",
}

_UNFINISHED = {
    "en": "No database statement was successfully executed. Unfinished work: the requested database operation was not completed.",
    "zh-CN": "没有成功执行任何数据库语句。未完成：请求的数据库操作尚未完成。",
    "zh-TW": "沒有成功執行任何資料庫語句。未完成：要求的資料庫操作尚未完成。",
    "fr": "Aucune instruction de base de données n'a été exécutée avec succès. Travail inachevé : l'opération demandée n'a pas été effectuée.",
    "ms": "Tiada pernyataan pangkalan data berjaya dilaksanakan. Kerja belum selesai: operasi yang diminta belum diselesaikan.",
    "ja": "データベース文は正常に実行されていません。未完了：要求された操作は完了していません。",
    "es": "No se ejecutó correctamente ninguna sentencia de base de datos. Trabajo pendiente: la operación solicitada no se completó.",
}

_ERRORS = {
    "en": "Statement errors:", "zh-CN": "语句错误：", "zh-TW": "語句錯誤：",
    "fr": "Erreurs des instructions :", "ms": "Ralat pernyataan:",
    "ja": "文のエラー：", "es": "Errores de las sentencias:",
}


def explicit_forbidden_request(message: str) -> bool:
    """Require an execution verb or a complete standalone prohibited SQL command."""
    match = _EXECUTE_REQUEST.match(message) or _DIRECT_COMMAND.fullmatch(message)
    if match is None:
        return False
    try:
        check_statement(match.group("sql"), "mysql")
    except UnsafeStatement as error:
        return "forbidden" in str(error)
    return False


def zero_execution_summary(message: str, locale: str, errors: list[str]) -> str:
    selected = select_locale(locale)
    if explicit_forbidden_request(message) and not errors:
        return _REFUSAL[selected]
    content = _UNFINISHED[selected]
    if errors:
        content += "\n\n" + _ERRORS[selected] + "\n" + "\n".join(errors)
    return content
