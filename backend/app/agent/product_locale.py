"""Source language resources for graph events and safe public stream errors."""

from app.agent.types import Intent
from app.core.localization import _messages, select_locale, translate

_ERRORS = {
    "en": ("The model returned an invalid response.", "Chat request failed (taskId: {task_id})."),
    "zh-CN": ("模型返回了无效响应。", "聊天请求失败（taskId: {task_id}）。"),
    "zh-TW": ("模型傳回了無效回應。", "聊天請求失敗（taskId: {task_id}）。"),
    "fr": ("Le modèle a renvoyé une réponse invalide.", "La requête de chat a échoué (taskId: {task_id})."),
    "ms": ("Model mengembalikan respons yang tidak sah.", "Permintaan sembang gagal (taskId: {task_id})."),
    "ja": ("モデルが無効な応答を返しました。", "チャットのリクエストに失敗しました（taskId: {task_id}）。"),
    "es": ("El modelo devolvió una respuesta no válida.", "La solicitud de chat falló (taskId: {task_id})."),
}


def product_text(key: str, locale: str, *args: object) -> str:
    pattern = _messages(select_locale(locale)).get(key)
    if pattern is None:
        raise KeyError(f"Missing product translation: {key}")
    return pattern.format(*args)


def intent_label(intent: Intent, locale: str) -> str:
    return product_text("intent." + intent, locale)


def clarification(intent: Intent, reason: str, locale: str, *, has_database: bool = False,
                  has_comparison: bool = False) -> dict[str, object]:
    label = intent_label(intent, locale)
    if intent == "sql_query" and not has_database:
        label = product_text("chat.clarify.sqlQueryNeedDb", locale)
    elif intent == "db_compare" and not has_comparison:
        label = product_text("chat.clarify.dbCompareNeedConfig", locale)
    options = [{"intent": intent, "label": label}]
    if intent != "simple_chat":
        options.append({"intent": "simple_chat", "label": product_text("chat.clarify.simpleChat", locale)})
    return {"question": product_text("chat.clarify.question", locale), "reasoning": reason, "options": options}


def missing_database(intent: Intent, locale: str) -> str:
    keys = {"sql_query": "error.chat.sqlQueryNoDbConfig", "workflow": "error.chat.workflowNoDbConfig",
            "db_compare": "error.chat.compareNoDbConfig"}
    return translate(keys[intent], locale)


def stream_error(invalid: bool, locale: str, task_id: str) -> str:
    return _ERRORS[select_locale(locale)][0 if invalid else 1].format(task_id=task_id)
