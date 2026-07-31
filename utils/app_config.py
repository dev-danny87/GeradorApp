"""
Application config: prefer .env / process env, then fall back to ~/ge.txt.

On Windows, ge.txt lives at C:\\Users\\<username>\\ge.txt
Format (same as .env):
    KEY=value
    # comments allowed
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional — ge.txt alone is enough
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv()

GE_TXT_FILENAME = "ge.txt"

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
]


def ge_txt_path() -> Path:
    return Path.home() / GE_TXT_FILENAME


def ensure_ge_txt() -> Path:
    """Create ~/ge.txt with empty defaults if it does not exist. Never overwrite."""
    path = ge_txt_path()
    if path.is_file():
        return path

    lines = [
        "# GeradorApp config — fill values as needed",
        f"# {path}",
        "",
        *[f"{key}=" for key in GE_TXT_DEFAULTS],
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
    return _parse_kv_file(ge_txt_path())


def reload_config() -> None:
    """Clear cached ge.txt values (useful after editing the file)."""
    _load_ge_txt.cache_clear()
    load_dotenv(override=True)


def get_config(key: str, default: str = "") -> str:
    """
    Resolve a config value.

    Priority:
      1. Non-empty process env / .env variable
      2. Matching key in ~/ge.txt
      3. default
    """
    env_value = os.getenv(key)
    if env_value is not None and str(env_value).strip() != "":
        return str(env_value).strip()

    file_value = _load_ge_txt().get(key)
    if file_value is not None and file_value.strip() != "":
        return file_value.strip()

    return default
