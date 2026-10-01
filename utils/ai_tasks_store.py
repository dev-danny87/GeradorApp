"""
Persistent storage for AI-generated task lists.

Results live in ./ai_tasks so they survive the ./diffs wipe that happens on
every new diff extraction.
"""

from __future__ import annotations

import datetime
import json
import os
import re

AI_TASKS_DIR = os.path.join(".", "ai_tasks")
DIFFS_ROOT = os.path.join(".", "diffs")
FILENAME_PREFIX = "ai_tasks_"
FECHAMENTO_PREFIX = "fechamento_"
_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def ai_tasks_dir() -> str:
    os.makedirs(AI_TASKS_DIR, exist_ok=True)
    return AI_TASKS_DIR


def sanitize_user(user: str) -> str:
    cleaned = _SAFE_CHARS.sub("_", (user or "").strip())
    return cleaned or "desconhecido"


def new_results_path(user: str, when: datetime.datetime | None = None) -> str:
    moment = when or datetime.datetime.now()
    timestamp = moment.strftime("%Y-%m-%d_%H%M%S")
    filename = f"{FILENAME_PREFIX}{sanitize_user(user)}_{timestamp}.json"
    return os.path.join(ai_tasks_dir(), filename)


def save_results(payload: dict, user: str, when: datetime.datetime | None = None) -> str:
    path = new_results_path(user, when)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _friendly_label(filename: str, payload: dict | None) -> str:
    task_count = len(payload.get("tasks", [])) if payload else 0

    generated_by = (payload or {}).get("generated_by") or ""
    generated_at = (payload or {}).get("generated_at") or ""

    when_text = ""
    if generated_at:
        try:
            when_text = datetime.datetime.fromisoformat(generated_at).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            when_text = generated_at

    if not generated_by or not when_text:
        return f"{filename} ({task_count} tarefa(s))" if task_count else filename

    label = f"{generated_by} — {when_text} — {task_count} tarefa(s)"
    if (payload or {}).get("partial"):
        label += " [parcial]"
    return label


def new_fechamento_path(
        user: str,
        when: datetime.datetime | None = None,
        output_dir: str | None = None,
) -> str:
    moment = when or datetime.datetime.now()
    timestamp = moment.strftime("%Y-%m-%d_%H%M%S")
    filename = f"{FECHAMENTO_PREFIX}{sanitize_user(user)}_{timestamp}.json"
    target_dir = output_dir or ai_tasks_dir()
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, filename)


def save_fechamento(
        payload: dict,
        user: str,
        when: datetime.datetime | None = None,
        output_dir: str | None = None,
) -> str:
    path = new_fechamento_path(user, when, output_dir=output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _fechamento_label(filename: str, payload: dict | None, folder_hint: str = "") -> str:
    task_count = len(payload.get("tasks", [])) if payload else 0
    parent_id = (payload or {}).get("parent_id") or "?"
    generated_at = (payload or {}).get("generated_at") or ""

    when_text = ""
    if generated_at:
        try:
            when_text = datetime.datetime.fromisoformat(generated_at).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            when_text = generated_at

    base = (
        f"Pai #{parent_id} — {task_count} tarefa(s) — {when_text}"
        if when_text
        else f"Pai #{parent_id} — {task_count} tarefa(s)"
    )
    if folder_hint:
        return f"{base} [{folder_hint}]"
    return base


def _fechamento_entry_from_path(path: str, folder_hint: str = "") -> dict | None:
    if not os.path.isfile(path):
        return None
    filename = os.path.basename(path)
    if not filename.startswith(FECHAMENTO_PREFIX) or not filename.lower().endswith(".json"):
        return None

    payload = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            payload = loaded
    except (OSError, json.JSONDecodeError):
        payload = None

    return {
        "path": path,
        "filename": filename,
        "label": _fechamento_label(filename, payload, folder_hint=folder_hint),
        "task_count": len(payload.get("tasks", [])) if payload else 0,
        "parent_id": (payload or {}).get("parent_id"),
    }


def list_saved_fechamentos() -> list[dict]:
    """Fechamento files from ./diffs/*/ and legacy ./ai_tasks/, newest first."""
    entries: list[dict] = []
    seen_paths: set[str] = set()

    if os.path.isdir(DIFFS_ROOT):
        for folder_name in os.listdir(DIFFS_ROOT):
            folder_path = os.path.join(DIFFS_ROOT, folder_name)
            if not os.path.isdir(folder_path):
                continue
            for filename in os.listdir(folder_path):
                path = os.path.join(folder_path, filename)
                entry = _fechamento_entry_from_path(path, folder_hint=folder_name)
                if not entry:
                    continue
                norm = os.path.normcase(os.path.abspath(path))
                if norm in seen_paths:
                    continue
                seen_paths.add(norm)
                entries.append(entry)

    if os.path.isdir(AI_TASKS_DIR):
        for filename in os.listdir(AI_TASKS_DIR):
            path = os.path.join(AI_TASKS_DIR, filename)
            entry = _fechamento_entry_from_path(path, folder_hint="ai_tasks")
            if not entry:
                continue
            norm = os.path.normcase(os.path.abspath(path))
            if norm in seen_paths:
                continue
            seen_paths.add(norm)
            entries.append(entry)

    entries.sort(key=lambda e: os.path.getmtime(e["path"]), reverse=True)
    return entries


def load_fechamento(path: str) -> dict:
    if not path or not os.path.exists(path):
        raise FileNotFoundError("Arquivo de fechamento não encontrado.")

    with open(path, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    if not isinstance(parsed, dict):
        raise ValueError("O arquivo de fechamento deve ser um objeto JSON.")
    tasks = parsed.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("O arquivo de fechamento não possui a lista 'tasks' esperada.")
    return parsed


def list_saved_results() -> list[dict]:
    """Saved analyses, newest first (filenames are timestamped)."""
    if not os.path.isdir(AI_TASKS_DIR):
        return []

    entries: list[dict] = []
    for filename in sorted(os.listdir(AI_TASKS_DIR), reverse=True):
        if not filename.lower().endswith(".json"):
            continue
        if filename.startswith(FECHAMENTO_PREFIX):
            continue
        path = os.path.join(AI_TASKS_DIR, filename)
        if not os.path.isfile(path):
            continue

        payload = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            payload = None

        entries.append({
            "path": path,
            "filename": filename,
            "label": _friendly_label(filename, payload),
            "task_count": len(payload.get("tasks", [])) if payload else 0,
        })

    return entries


def _load_tasks_from_jsonl(path: str) -> list:
    tasks: list = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            batch_obj = json.loads(line)
            result_meta = batch_obj.get("result", {})
            if result_meta.get("type") != "succeeded":
                error_info = result_meta.get("error", {}).get("message", "Erro desconhecido retornado pela API")
                raise ValueError(f"O processamento da API falhou: {error_info}")

            raw_content = result_meta["message"]["content"][0]["text"].strip()
            if "```json" in raw_content:
                raw_content = raw_content.split("```json")[-1].split("```")[0].strip()
            elif raw_content.startswith("```"):
                raw_content = raw_content.strip("`").strip()

            parsed_payload = json.loads(raw_content)
            batch_tasks = parsed_payload.get("tasks", [])
            if not batch_tasks:
                raise ValueError("O JSON retornado não possui a lista de 'tasks' esperada.")
            tasks.extend(batch_tasks)

    return tasks


def load_tasks(path: str) -> list:
    if not path or not os.path.exists(path):
        raise FileNotFoundError("Arquivo de resultados não encontrado.")

    if path.lower().endswith(".jsonl"):
        return _load_tasks_from_jsonl(path)

    with open(path, "r", encoding="utf-8") as f:
        parsed_payload = json.load(f)

    tasks = parsed_payload.get("tasks", []) if isinstance(parsed_payload, dict) else []
    if not tasks:
        raise ValueError("O JSON retornado não possui a lista de 'tasks' esperada.")
    return tasks
