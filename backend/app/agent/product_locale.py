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

_REPORT_ERRORS = {
    "en": "The final report could not be completed. Verified operation records are retained; "
          "this report failure does not roll back completed writes. Review the execution steps "
          "before deciding whether to send the request again (taskId: {task_id}).",
    "zh-CN": "最终报告未能完整生成。已确认的操作记录仍保留；报告失败不会撤销已经完成的写入。"
             "请先查看执行步骤，再决定是否重新发送请求（taskId: {task_id}）。",
    "zh-TW": "最終報告未能完整產生。已確認的操作紀錄仍保留；報告失敗不會撤銷已完成的寫入。"
             "請先查看執行步驟，再決定是否重新傳送請求（taskId: {task_id}）。",
    "fr": "Le rapport final n’a pas pu être terminé. Les opérations vérifiées restent consignées ; "
          "cet échec du rapport n’annule pas les écritures déjà effectuées. Consultez les étapes "
          "d’exécution avant de décider de renvoyer la demande (taskId: {task_id}).",
    "ms": "Laporan akhir tidak dapat disiapkan. Rekod operasi yang disahkan masih disimpan; "
          "kegagalan laporan ini tidak membatalkan penulisan yang telah selesai. Semak langkah "
          "pelaksanaan sebelum memutuskan untuk menghantar semula permintaan (taskId: {task_id}).",
    "ja": "最終レポートを完成できませんでした。確認済みの操作記録は保持され、レポートの失敗によって"
          "完了済みの書き込みが取り消されることはありません。リクエストを再送するか決める前に、"
          "実行手順を確認してください（taskId: {task_id}）。",
    "es": "No se pudo completar el informe final. Se conservan los registros de las operaciones "
          "verificadas; este fallo no revierte las escrituras ya completadas. Revise los pasos de "
          "ejecución antes de decidir si envía de nuevo la solicitud (taskId: {task_id}).",
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


def final_report_error(locale: str, task_id: str) -> str:
    return _REPORT_ERRORS[select_locale(locale)].format(task_id=task_id)
