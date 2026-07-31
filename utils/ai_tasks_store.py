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
FILENAME_PREFIX = "ai_tasks_"
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


def list_saved_results() -> list[dict]:
    """Saved analyses, newest first (filenames are timestamped)."""
    if not os.path.isdir(AI_TASKS_DIR):
        return []

    entries: list[dict] = []
    for filename in sorted(os.listdir(AI_TASKS_DIR), reverse=True):
        if not filename.lower().endswith(".json"):
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
