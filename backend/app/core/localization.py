from functools import lru_cache
from importlib.resources import files

SUPPORTED_LOCALES = {
    "en": "",
    "zh-CN": "_zh_CN",
    "zh-TW": "_zh_TW",
    "fr": "_fr",
    "ms": "_ms",
    "ja": "_ja",
    "es": "_es",
}


def select_locale(accept_language: str | None) -> str:
    if not accept_language:
        return "en"
    for option in accept_language.split(","):
        tag = option.split(";", 1)[0].strip().replace("_", "-")
        for supported in SUPPORTED_LOCALES:
            if tag.casefold() == supported.casefold():
                return supported
        if tag.casefold().startswith("zh"):
            return "zh-TW" if tag.casefold() in {"zh-hk", "zh-mo", "zh-hant"} else "zh-CN"
        primary = tag.split("-", 1)[0].casefold()
        if primary in SUPPORTED_LOCALES:
            return primary
    return "en"


@lru_cache
def _messages(locale: str) -> dict[str, str]:
    suffix = SUPPORTED_LOCALES[locale]
    resource = files("app").joinpath("resources", "i18n", f"messages{suffix}.properties")
    messages: dict[str, str] = {}
    for raw_line in resource.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid i18n resource line in {resource.name}")
        key, value = line.split("=", 1)
        messages[key.strip()] = value.strip()
    return messages


def translate(key_or_text: str, accept_language: str | None, *args: object) -> str:
    if not key_or_text.startswith("error."):
        return key_or_text
    locale = select_locale(accept_language)
    pattern = _messages(locale).get(key_or_text, _messages("en").get(key_or_text))
    if pattern is None:
        raise KeyError(f"Missing error translation: {key_or_text}")
    return pattern.format(*args)
