"""
Persistent storage for leftover AI tasks (banco de horas).

Files live in ~/taskManager/bancoDeHoras so they survive app restarts and
remain outside the project ./diffs wipe cycle.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

from utils.app_config import banco_horas_dir, ensure_task_manager_dirs

FILENAME_PREFIX = "banco_"
_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def ensure_banco_dir() -> Path:
    ensure_task_manager_dirs()
    path = banco_horas_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_user(user: str) -> str:
    cleaned = _SAFE_CHARS.sub("_", (user or "").strip())
    return cleaned or "desconhecido"


def new_banco_path(user: str = "", when: datetime.datetime | None = None) -> Path:
    moment = when or datetime.datetime.now()
    timestamp = moment.strftime("%Y-%m-%d_%H%M%S")
    suffix = sanitize_user(user)
    filename = f"{FILENAME_PREFIX}{suffix}_{timestamp}.json"
    return ensure_banco_dir() / filename


def save_banco_batch(
        tasks: list[dict],
        *,
        user: str = "",
        source_analysis: str = "",
        source_diff_folder: str = "",
        atribuicao_catalogo: str = "",
        when: datetime.datetime | None = None,
) -> str | None:
    """
    Persist leftover tasks. Returns the file path, or None when tasks is empty.
    """
    if not tasks:
        return None

    moment = when or datetime.datetime.now()
    payload = {
        "saved_at": moment.isoformat(timespec="seconds"),
        "saved_by": user or "",
        "source_analysis": source_analysis or "",
        "source_diff_folder": source_diff_folder or "",
        "atribuicao_catalogo": atribuicao_catalogo or "",
        "tasks": [dict(t) for t in tasks],
    }
    path = new_banco_path(user, moment)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return str(path)


def _task_hours(task: dict) -> float:
    try:
        return float(task.get("estimated_hours", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _friendly_label(filename: str, payload: dict | None) -> str:
    tasks = (payload or {}).get("tasks") or []
    task_count = len(tasks) if isinstance(tasks, list) else 0
    total_hours = round(sum(_task_hours(t) for t in tasks), 2) if isinstance(tasks, list) else 0.0

    saved_at = (payload or {}).get("saved_at") or ""
    when_text = ""
    if saved_at:
        try:
            when_text = datetime.datetime.fromisoformat(saved_at).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            when_text = saved_at

    source = (payload or {}).get("source_diff_folder") or ""
    parts = []
    if when_text:
        parts.append(when_text)
    parts.append(f"{task_count} tarefa(s)")
    parts.append(f"{total_hours:g}h")
    if source:
        parts.append(source)
    return " — ".join(parts) if parts else filename


def list_banco_batches() -> list[dict]:
    """All banco JSON files, newest first."""
    root = ensure_banco_dir()
    entries: list[dict] = []

    for filename in sorted(os.listdir(root), reverse=True):
        if not filename.lower().endswith(".json"):
            continue
        if not filename.startswith(FILENAME_PREFIX):
            continue
        path = root / filename
        if not path.is_file():
            continue

        payload = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            payload = None

        tasks = (payload or {}).get("tasks") or []
        if not isinstance(tasks, list):
            tasks = []

        entries.append({
            "path": str(path),
            "filename": filename,
            "label": _friendly_label(filename, payload),
            "tasks": tasks,
            "task_count": len(tasks),
            "total_hours": round(sum(_task_hours(t) for t in tasks), 2),
            "source_diff_folder": (payload or {}).get("source_diff_folder") or "",
            "source_analysis": (payload or {}).get("source_analysis") or "",
            "atribuicao_catalogo": (payload or {}).get("atribuicao_catalogo") or "",
            "saved_at": (payload or {}).get("saved_at") or "",
        })

    entries.sort(key=lambda e: os.path.getmtime(e["path"]), reverse=True)
    return entries


def load_banco_batch(path: str) -> dict:
    if not path or not os.path.exists(path):
        raise FileNotFoundError("Arquivo do banco de horas não encontrado.")

    with open(path, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    if not isinstance(parsed, dict):
        raise ValueError("O arquivo do banco de horas deve ser um objeto JSON.")
    tasks = parsed.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("O arquivo do banco de horas não possui a lista 'tasks' esperada.")
    return parsed


def remove_tasks_by_ids(task_ids: set[str] | list[str]) -> int:
    """
    Remove tasks with the given task_id from every banco file.
    Deletes a file when its task list becomes empty.
    Returns how many tasks were removed.
    """
    ids = {str(tid) for tid in task_ids if tid}
    if not ids:
        return 0

    removed = 0
    for entry in list_banco_batches():
        path = entry["path"]
        try:
            payload = load_banco_batch(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue

        original = payload.get("tasks") or []
        if not isinstance(original, list):
            continue

        kept = [
            task for task in original
            if str(task.get("task_id") or "") not in ids
        ]
        delta = len(original) - len(kept)
        if delta <= 0:
            continue

        removed += delta
        if not kept:
            try:
                os.remove(path)
            except OSError:
                payload["tasks"] = []
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            payload["tasks"] = kept
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    return removed


def totals() -> dict:
    entries = list_banco_batches()
    task_count = sum(e["task_count"] for e in entries)
    total_hours = round(sum(e["total_hours"] for e in entries), 2)
    return {
        "batch_count": len(entries),
        "task_count": task_count,
        "total_hours": total_hours,
        "entries": entries,
    }
