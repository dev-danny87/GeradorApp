"""
Application config: prefer .env / process env, then fall back to ~/taskManager/ge.txt.

On Windows, ge.txt lives at C:\\Users\\<username>\\taskManager\\ge.txt
Format (same as .env):
    KEY=value
    # comments allowed
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional — ge.txt alone is enough
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv()

GE_TXT_FILENAME = "ge.txt"
TASK_MANAGER_DIRNAME = "taskManager"
BANCO_HORAS_DIRNAME = "bancoDeHoras"

GE_TXT_DEFAULTS = [
    "RD_HOST",
    "RD_USER",
    "RD_PASS",
    "CLAUDE_KEY",
    "GITLAB_TOKEN",
    "GITHUB_TOKEN",
    "STARTING_DATE",
    "STARTING_VERSAO",
    "THREADS",
    "GITLAB_DEFAULT_AUTHOR",
    "GITHUB_DEFAULT_AUTHOR",
    "DIFF_DEFAULT_PLATFORM",
    "RD_DEFAULT_SISTEMA",
    "RD_DEFAULT_ORGAO",
    "RD_DEFAULT_ATRIBUICAO",
    "RD_DEFAULT_PROJETO",
    "RD_DEFAULT_DESENVOLVEDOR",
    "RD_MIN_TASK_HOURS",
]

# Defaults applied only when creating a new ge.txt (never overwrite existing).
GE_TXT_DEFAULT_VALUES = {
    "THREADS": "1",
    "RD_DEFAULT_SISTEMA": "SICOR",
    "RD_DEFAULT_ORGAO": "PM",
    "RD_DEFAULT_ATRIBUICAO": "Desenvolvedor Sênior",
    "RD_DEFAULT_PROJETO": "SICOR",
    "RD_DEFAULT_DESENVOLVEDOR": "",
    "RD_MIN_TASK_HOURS": "8",
}


def task_manager_dir() -> Path:
    return Path.home() / TASK_MANAGER_DIRNAME


def banco_horas_dir() -> Path:
    return task_manager_dir() / BANCO_HORAS_DIRNAME


def ge_txt_path() -> Path:
    return task_manager_dir() / GE_TXT_FILENAME


def legacy_ge_txt_path() -> Path:
    """Previous location before the taskManager migration."""
    return Path.home() / GE_TXT_FILENAME


def ensure_task_manager_dirs() -> Path:
    """Create ~/taskManager and ~/taskManager/bancoDeHoras if missing."""
    root = task_manager_dir()
    root.mkdir(parents=True, exist_ok=True)
    banco_horas_dir().mkdir(parents=True, exist_ok=True)
    return root


def _migrate_legacy_ge_txt(new_path: Path) -> None:
    """
    Move ~/ge.txt into ~/taskManager/ge.txt when the new file does not exist.
    If both exist, keep the new file and leave the legacy one untouched.
    """
    legacy = legacy_ge_txt_path()
    if new_path.is_file() or not legacy.is_file():
        return
    try:
        shutil.move(str(legacy), str(new_path))
        print(f"[CONFIG] ge.txt migrado para {new_path}")
    except OSError as ex:
        print(f"[CONFIG WARN] Falha ao migrar ge.txt: {ex}")


def ensure_ge_txt() -> Path:
    """Create ~/taskManager/ge.txt with empty defaults if it does not exist. Never overwrite."""
    ensure_task_manager_dirs()
    path = ge_txt_path()
    _migrate_legacy_ge_txt(path)
    if path.is_file():
        return path

    lines = [
        "# GeradorApp config — fill values as needed",
        f"# {path}",
        "",
        *[
            f"{key}={GE_TXT_DEFAULT_VALUES.get(key, '')}"
            for key in GE_TXT_DEFAULTS
        ],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    _load_ge_txt.cache_clear()
    return path


def _parse_kv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


@lru_cache(maxsize=1)
def _load_ge_txt() -> dict[str, str]:
    ensure_task_manager_dirs()
    path = ge_txt_path()
    _migrate_legacy_ge_txt(path)
    return _parse_kv_file(path)


def reload_config() -> None:
    """Clear cached ge.txt values (useful after editing the file)."""
    _load_ge_txt.cache_clear()
    load_dotenv(override=True)


def load_ge_txt_values() -> dict[str, str]:
    """Return parsed ge.txt values (cache cleared so disk is re-read)."""
    ensure_ge_txt()
    _load_ge_txt.cache_clear()
    return dict(_load_ge_txt())


def save_ge_txt(values: dict[str, str]) -> Path:
    """
    Rewrite ~/taskManager/ge.txt with known keys in GE_TXT_DEFAULTS order.
    Reloads cache and copies non-empty values into os.environ.
    """
    path = ensure_ge_txt()
    lines = [
        "# GeradorApp config — fill values as needed",
        f"# {path}",
        "",
    ]
    for key in GE_TXT_DEFAULTS:
        raw = values.get(key, "")
        value = "" if raw is None else str(raw).strip()
        lines.append(f"{key}={value}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

    reload_config()
    env_wins = set(keys_overridden_by_env())
    for key in GE_TXT_DEFAULTS:
        value = str(values.get(key, "") or "").strip()
        if value and key not in env_wins:
            os.environ[key] = value

    return path


def keys_overridden_by_env() -> list[str]:
    """Keys with a non-empty value in the project .env (those win over ge.txt)."""
    env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        return []
    file_values = _parse_kv_file(env_path)
    return [
        key
        for key in GE_TXT_DEFAULTS
        if (file_values.get(key) or "").strip()
    ]


def get_config(key: str, default: str = "") -> str:
    """
    Resolve a config value.

    Priority:
      1. Non-empty process env / .env variable
      2. Matching key in ~/taskManager/ge.txt
      3. default
    """
    env_value = os.getenv(key)
    if env_value is not None and str(env_value).strip() != "":
        return str(env_value).strip()

    file_value = _load_ge_txt().get(key)
    if file_value is not None and file_value.strip() != "":
        return file_value.strip()

    return default
