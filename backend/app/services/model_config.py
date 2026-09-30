from dataclasses import dataclass
from datetime import datetime

from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BusinessError, deny_trial
from app.core.security import decrypt, encrypt
from app.models import ModelProvider, User, UserModelConfig
from app.schemas.model_config import (
    ContextWindowLookupVO,
    ModelProviderVO,
    UserModelConfigBase,
    UserModelConfigRequest,
    UserModelConfigUpdate,
    UserModelConfigVO,
)
from app.services.model_config_info import known_context_window, lookup_context_window

BUILTIN_PROVIDERS = (
    ("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-flash", 10),
    ("openai", "OpenAI", "https://api.openai.com", "gpt-4o", 20),
    ("ollama", "Ollama", "http://localhost:11434", "llama3.1", 60),
    ("custom", "自定义（OpenAI 兼容）", None, None, 90),
)


@dataclass(frozen=True)
class ResolvedModel:
    id: int | None
    provider_code: str | None
    provider_type: str
    display_name: str
    base_url: str
    api_key: SecretStr
    model_name: str
    context_window: int | None
    is_default: bool
    status: int
    created_at: datetime | None


def initialize_providers(session: Session) -> None:
    existing = {provider.provider_code: provider for provider in session.scalars(select(ModelProvider)).all()}
    for code, name, base_url, model, order in BUILTIN_PROVIDERS:
        if code in existing:
            provider = existing[code]
            if code == "deepseek" and provider.builtin and provider.default_model != model:
                provider.default_model = model
            continue
        try:
            with session.begin_nested():
                session.add(ModelProvider(provider_code=code, display_name=name,
                                          provider_type="openai_compatible", default_base_url=base_url,
                                          default_model=model, builtin=True, sort_order=order))
                session.flush()
        except IntegrityError:
            if session.scalar(select(ModelProvider.id).where(ModelProvider.provider_code == code)) is None:
                raise
    session.commit()


def list_providers(session: Session) -> list[ModelProviderVO]:
    providers = session.scalars(select(ModelProvider).order_by(ModelProvider.sort_order, ModelProvider.id)).all()
    return [ModelProviderVO.model_validate(item) for item in providers]


def to_vo(config: UserModelConfig) -> UserModelConfigVO:
    return UserModelConfigVO(
        id=config.id, provider_code=config.provider_code, provider_type=config.provider_type,
        display_name=config.display_name, base_url=config.base_url, model_name=config.model_name,
        context_window=config.context_window, is_default=config.is_default, status=config.status,
        status_desc="已启用" if config.status == 1 else "已禁用", created_at=config.created_at,
    )


def owned_config(session: Session, user_id: int, config_id: int) -> UserModelConfig:
    config = session.scalar(select(UserModelConfig).where(
        UserModelConfig.id == config_id, UserModelConfig.user_id == user_id,
    ))
    if config is None:
        raise BusinessError(404, "error.modelConfig.notFound")
    return config


def _base_url(session: Session, request: UserModelConfigBase) -> str:
    provider = session.scalar(select(ModelProvider).where(ModelProvider.provider_code == request.provider_code))
    if provider is None:
        raise BusinessError(400, "Unknown model provider")
    if request.provider_type != "openai_compatible":
        raise BusinessError(400, "Unsupported model provider type")
    url = request.base_url.strip() if request.base_url else provider.default_base_url
    if not url:
        raise BusinessError(400, "baseUrl is required")
    return url


def list_configs(session: Session, user_id: int) -> list[UserModelConfigVO]:
    configs = session.scalars(select(UserModelConfig).where(UserModelConfig.user_id == user_id).order_by(
        UserModelConfig.is_default.desc(), UserModelConfig.created_at.desc(), UserModelConfig.id.desc(),
    )).all()
    return [to_vo(config) for config in configs]


def create_config(session: Session, user_id: int, request: UserModelConfigRequest) -> UserModelConfigVO:
    deny_trial("error.trial.modelConfigCreate")
    session.execute(select(User.id).where(User.id == user_id).with_for_update()).scalar_one()
    base_url = _base_url(session, request)
    existing = session.scalar(select(UserModelConfig.id).where(UserModelConfig.user_id == user_id).limit(1))
    config = UserModelConfig(
        user_id=user_id, provider_code=request.provider_code, provider_type="openai_compatible",
        display_name=request.display_name, base_url=base_url, api_key_encrypted=encrypt(request.api_key),
        model_name=request.model_name,
        context_window=request.context_window or known_context_window(request.model_name),
        is_default=existing is None, status=1,
    )
    session.add(config)
    session.commit()
    session.refresh(config)
    return to_vo(config)


def update_config(session: Session, user_id: int, config_id: int,
                  request: UserModelConfigUpdate) -> UserModelConfigVO:
    deny_trial("error.trial.modelConfigUpdate")
    config = owned_config(session, user_id, config_id)
    config.base_url = _base_url(session, request)
    config.provider_code = request.provider_code
    config.provider_type = "openai_compatible"
    config.display_name = request.display_name
    if request.api_key.strip():
        config.api_key_encrypted = encrypt(request.api_key)
    config.model_name = request.model_name
    config.context_window = request.context_window or known_context_window(request.model_name) or config.context_window
    session.commit()
    session.refresh(config)
    return to_vo(config)


def delete_config(session: Session, user_id: int, config_id: int) -> None:
    deny_trial("error.trial.modelConfigDelete")
    config = owned_config(session, user_id, config_id)
    if config.is_default:
        raise BusinessError(400, "error.modelConfig.cannotDeleteDefault")
    session.delete(config)
    session.commit()


def set_default(session: Session, user_id: int, config_id: int) -> None:
    deny_trial("error.trial.modelConfigSetDefault")
    session.execute(select(User.id).where(User.id == user_id).with_for_update()).scalar_one()
    config = owned_config(session, user_id, config_id)
    if config.status != 1:
        raise BusinessError(400, "error.modelConfig.disabledCannotBeDefault")
    session.execute(update(UserModelConfig).where(UserModelConfig.user_id == user_id).values(is_default=False))
    config.is_default = True
    session.commit()


def _active_user_config(session: Session, user_id: int) -> UserModelConfig | None:
    config = session.scalar(select(UserModelConfig).where(
        UserModelConfig.user_id == user_id, UserModelConfig.is_default.is_(True),
        UserModelConfig.status == 1,
    ).order_by(UserModelConfig.id.desc()))
    if config is None:
        config = session.scalar(select(UserModelConfig).where(
            UserModelConfig.user_id == user_id, UserModelConfig.status == 1,
        ).order_by(UserModelConfig.created_at.desc(), UserModelConfig.id.desc()))
    return config


def resolve_active_model(session: Session, user_id: int) -> ResolvedModel:
    config = _active_user_config(session, user_id)
    if config is not None:
        return ResolvedModel(
            id=config.id, provider_code=config.provider_code,
            provider_type=config.provider_type, display_name=config.display_name,
            base_url=config.base_url, api_key=SecretStr(decrypt(config.api_key_encrypted)),
            model_name=config.model_name, context_window=config.context_window,
            is_default=config.is_default, status=config.status, created_at=config.created_at,
        )
    settings = get_settings()
    if not settings.default_model_api_key.strip():
        raise BusinessError(400, "error.modelConfig.notConfigured")
    return ResolvedModel(
        id=None, provider_code="system", provider_type="openai_compatible",
        display_name="系统默认", base_url=settings.default_model_base_url,
        api_key=SecretStr(settings.default_model_api_key), model_name=settings.default_model_name,
        context_window=known_context_window(settings.default_model_name),
        is_default=True, status=1, created_at=None,
    )


def active_config_vo(session: Session, user_id: int) -> UserModelConfigVO:
    model = resolve_active_model(session, user_id)
    return UserModelConfigVO(
        id=model.id, provider_code=model.provider_code, provider_type=model.provider_type,
        display_name=model.display_name, base_url=model.base_url, model_name=model.model_name,
        context_window=model.context_window, is_default=model.is_default, status=model.status,
        status_desc="已启用" if model.status == 1 else "已禁用", created_at=model.created_at,
    )


def saved_context_window(session: Session, user_id: int, config_id: int) -> ContextWindowLookupVO:
    deny_trial("error.trial.contextWindowLookup")
    config = owned_config(session, user_id, config_id)
    return lookup_context_window(config.base_url, decrypt(config.api_key_encrypted), config.model_name)
