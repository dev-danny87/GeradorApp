"""Resolve SSP Redmine task field defaults from ge.txt / .env."""

from __future__ import annotations

from redmine_mappings import (
    LOGIN_TO_USER_ID,
    ORGAN_OPTIONS,
    PROJECT_FILTER_OPTIONS,
    ROLE_OPTIONS,
    SYSTEM_OPTIONS,
    USER_OPTIONS,
)
from utils.app_config import GE_TXT_DEFAULT_VALUES, get_config

_FALLBACK_SISTEMA = GE_TXT_DEFAULT_VALUES.get("RD_DEFAULT_SISTEMA", "SICOR")
_FALLBACK_ORGAO = GE_TXT_DEFAULT_VALUES.get("RD_DEFAULT_ORGAO", "PM")
_FALLBACK_ATRIBUICAO = GE_TXT_DEFAULT_VALUES.get("RD_DEFAULT_ATRIBUICAO", "Desenvolvedor Sênior")
_FALLBACK_PROJETO = GE_TXT_DEFAULT_VALUES.get("RD_DEFAULT_PROJETO", "SICOR")
_FALLBACK_MIN_HOURS = 8.0

_VALID_SISTEMAS = set(SYSTEM_OPTIONS.values())
_VALID_ORGAOS = set(ORGAN_OPTIONS.values())
_VALID_ATRIBUICOES = set(ROLE_OPTIONS.values())
_VALID_PROJETOS = set(PROJECT_FILTER_OPTIONS.values())
_VALID_USER_IDS = set(USER_OPTIONS.values())


def _pick(value: str, valid: set[str], fallback: str) -> str:
    cleaned = (value or "").strip()
    if cleaned and cleaned in valid:
        return cleaned
    if fallback in valid:
        return fallback
    return next(iter(valid), fallback)


def get_min_task_hours() -> float:
    raw = get_config("RD_MIN_TASK_HOURS", str(int(_FALLBACK_MIN_HOURS)))
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return _FALLBACK_MIN_HOURS
    if hours <= 0:
        return _FALLBACK_MIN_HOURS
    return hours


def _configured_user_id(key: str) -> str | None:
    value = (get_config(key) or "").strip()
    if value in _VALID_USER_IDS:
        return value
    return None


def _login_user_id(username: str | None) -> str | None:
    mapped = LOGIN_TO_USER_ID.get(username or "")
    if mapped and mapped in _VALID_USER_IDS:
        return mapped
    return None


def redmine_task_defaults(username: str | None = None) -> dict:
    """
    Return validated SSP task defaults for forms and Redmine creation.

    Keys: sistema, orgao, atribuicao, projeto, desenvolvedor_id, assigned_to_id, min_hours
    """
    sistema = _pick(
        get_config("RD_DEFAULT_SISTEMA", _FALLBACK_SISTEMA),
        _VALID_SISTEMAS,
        _FALLBACK_SISTEMA,
    )
    orgao = _pick(
        get_config("RD_DEFAULT_ORGAO", _FALLBACK_ORGAO),
        _VALID_ORGAOS,
        _FALLBACK_ORGAO,
    )
    atribuicao = _pick(
        get_config("RD_DEFAULT_ATRIBUICAO", _FALLBACK_ATRIBUICAO),
        _VALID_ATRIBUICOES,
        _FALLBACK_ATRIBUICAO,
    )
    projeto = _pick(
        get_config("RD_DEFAULT_PROJETO", _FALLBACK_PROJETO),
        _VALID_PROJETOS,
        _FALLBACK_PROJETO,
    )

    login_user_id = _login_user_id(username)
    desenvolvedor_id = _configured_user_id("RD_DEFAULT_DESENVOLVEDOR") or login_user_id
    assigned_to_id = (
        _configured_user_id("RD_DEFAULT_ATRIBUIDO_PARA")
        or login_user_id
        or desenvolvedor_id
    )

    return {
        "sistema": sistema,
        "orgao": orgao,
        "atribuicao": atribuicao,
        "projeto": projeto,
        "desenvolvedor_id": desenvolvedor_id,
        "assigned_to_id": assigned_to_id,
        "min_hours": get_min_task_hours(),
    }
