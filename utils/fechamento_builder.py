"""
Build and regenerate fechamento JSON from AI task analyses + Redmine IDs.
"""

from __future__ import annotations

import datetime
import json
import os
import re

from utils.ai_tasks_store import AI_TASKS_DIR, DIFFS_ROOT, save_fechamento
from utils.commit_metadata import (
    build_commits_index,
    build_detailed_fechamento_notas,
    enrich_tasks_commit_links_from_diffs,
    strip_urls_from_description,
)
from utils.redmine_task_defaults import get_min_task_hours

_TITLE_CLEAN_RE = re.compile(r"[^a-z0-9]+")
CHECKPOINT_FILENAME = "ai_tasks_checkpoint.json"

SOURCE_ANALYSIS = "analysis"
SOURCE_CHECKPOINT = "checkpoint"


def _normalize_title(value: str) -> str:
    cleaned = _TITLE_CLEAN_RE.sub(" ", (value or "").lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def resolve_diff_folder_path(diff_folder: str | None) -> str | None:
    if not diff_folder:
        return None
    folder_path = (
        diff_folder
        if os.path.isabs(diff_folder) or (os.path.dirname(diff_folder) not in ("", "."))
        else os.path.join(DIFFS_ROOT, diff_folder)
    )
    if os.path.isdir(folder_path):
        return folder_path
    alt = os.path.join(DIFFS_ROOT, os.path.basename(diff_folder))
    if os.path.isdir(alt):
        return alt
    return None


def load_diff_texts(diff_folder: str | None) -> list[str]:
    folder_path = resolve_diff_folder_path(diff_folder)
    if not folder_path:
        return []

    texts: list[str] = []
    for filename in sorted(os.listdir(folder_path)):
        if not filename.endswith(".txt"):
            continue
        path = os.path.join(folder_path, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                texts.append(f.read())
        except OSError:
            continue
    return texts


def checkpoint_path_for_folder(diff_folder: str | None) -> str | None:
    folder_path = resolve_diff_folder_path(diff_folder)
    if not folder_path:
        return None
    path = os.path.join(folder_path, CHECKPOINT_FILENAME)
    return path if os.path.isfile(path) else None


def list_diff_folders_with_checkpoint() -> list[dict]:
    """Diff folders that contain ai_tasks_checkpoint.json, newest first."""
    if not os.path.isdir(DIFFS_ROOT):
        return []

    entries: list[dict] = []
    for name in os.listdir(DIFFS_ROOT):
        folder_path = os.path.join(DIFFS_ROOT, name)
        if not os.path.isdir(folder_path):
            continue
        checkpoint = os.path.join(folder_path, CHECKPOINT_FILENAME)
        if not os.path.isfile(checkpoint):
            continue
        try:
            mtime = os.path.getmtime(checkpoint)
        except OSError:
            mtime = 0
        task_count = 0
        try:
            with open(checkpoint, "r", encoding="utf-8") as f:
                data = json.load(f)
            for unit in data.get("unit_tasks") or []:
                if isinstance(unit, dict):
                    task_count += len(unit.get("tasks") or [])
        except (OSError, json.JSONDecodeError, TypeError):
            task_count = 0
        entries.append({
            "folder": name,
            "path": folder_path,
            "checkpoint_path": checkpoint,
            "task_count": task_count,
            "mtime": mtime,
            "label": f"{name} ({task_count} tarefa(s) no checkpoint)",
        })

    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries


def load_tasks_from_checkpoint(diff_folder: str | None) -> list[dict]:
    path = checkpoint_path_for_folder(diff_folder)
    if not path:
        raise FileNotFoundError(
            f"Checkpoint '{CHECKPOINT_FILENAME}' não encontrado na pasta de diffs."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Checkpoint inválido: esperado um objeto JSON.")

    tasks: list[dict] = []
    for unit in data.get("unit_tasks") or []:
        if not isinstance(unit, dict):
            continue
        for task in unit.get("tasks") or []:
            if isinstance(task, dict):
                tasks.append(dict(task))
    if not tasks:
        raise ValueError("O checkpoint não contém tarefas em 'unit_tasks'.")
    return tasks


def load_analysis_payload(analysis_path: str) -> dict:
    with open(analysis_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("A análise deve ser um objeto JSON.")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("A análise não possui a lista 'tasks' esperada.")
    return payload


def resolve_analysis_path(source_analysis: str | None) -> str | None:
    if not source_analysis:
        return None
    if os.path.isfile(source_analysis):
        return source_analysis
    candidate = os.path.join(AI_TASKS_DIR, os.path.basename(source_analysis))
    if os.path.isfile(candidate):
        return candidate
    return None


def prepare_tasks_with_commits(
        tasks: list[dict],
        diff_folder: str | None,
        *,
        use_diffs: bool = True,
) -> tuple[list[dict], dict]:
    """Enrich tasks with commit_links (optional) and return (tasks, commits_index)."""
    prepared = [dict(t) for t in tasks]
    if use_diffs:
        diff_texts = load_diff_texts(diff_folder)
        if diff_texts:
            enrich_tasks_commit_links_from_diffs(prepared, diff_texts)
        commits_index = build_commits_index(diff_texts)
    else:
        commits_index = {}
    prepared = [strip_urls_from_description(t) for t in prepared]
    return prepared, commits_index


def _title_similarity(a: str, b: str) -> float:
    na = _normalize_title(a)
    nb = _normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.85
    wa = set(na.split())
    wb = set(nb.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa | wb), 1)


def map_ids_to_tasks(
        id_items: list[dict],
        tasks: list[dict],
) -> list[tuple[dict, dict | None]]:
    """
    Pair Redmine id items with analysis tasks.

    id_items: [{"id": "...", "title": optional}, ...]
    Prefer zip when lengths match; otherwise title match; leftover ids get None task.
    """
    if not id_items:
        return []

    if len(id_items) == len(tasks):
        return list(zip(id_items, tasks))

    remaining = list(enumerate(tasks))
    paired: list[tuple[dict, dict | None]] = []

    for item in id_items:
        title = item.get("title") or item.get("task_title") or ""
        best_idx = None
        best_score = 0.0
        for idx, (_orig_i, task) in enumerate(remaining):
            score = _title_similarity(title, task.get("task_title") or task.get("title") or "")
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx is not None and best_score >= 0.35:
            _, task = remaining.pop(best_idx)
            paired.append((item, task))
        elif remaining and not title:
            _, task = remaining.pop(0)
            paired.append((item, task))
        else:
            paired.append((item, None))

    return paired


def build_fechamento_task_entries(
        id_items: list[dict],
        tasks: list[dict],
        commits_index: dict | None = None,
        preserve_files: bool = True,
) -> list[dict]:
    """Build fechamento tasks list with detailed notas."""
    entries: list[dict] = []
    for item, task in map_ids_to_tasks(id_items, tasks):
        issue_id = str(item.get("id", "")).strip()
        if not issue_id:
            continue
        files = item.get("files") if preserve_files and isinstance(item.get("files"), list) else []
        if task is None:
            notas = (
                "## Encerramento\n"
                "Tarefa fechada no Redmine. Não foi possível associar automaticamente "
                "uma tarefa da análise de IA para montar notas detalhadas."
            )
        else:
            notas = build_detailed_fechamento_notas(task, commits_index)
        entries.append({
            "id": issue_id,
            "notas": notas,
            "files": [str(p).strip() for p in (files or []) if str(p).strip()],
        })
    return entries


def build_fechamento_payload(
        *,
        parent_id: str,
        id_items: list[dict],
        tasks: list[dict],
        commits_index: dict | None = None,
        generated_by: str = "",
        source_analysis: str = "",
        source_diff_folder: str = "",
        preserve_files: bool = True,
) -> dict:
    return {
        "parent_id": str(parent_id),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "generated_by": generated_by or "",
        "source_analysis": source_analysis or "",
        "source_diff_folder": source_diff_folder or "",
        "tasks": build_fechamento_task_entries(
            id_items,
            tasks,
            commits_index=commits_index,
            preserve_files=preserve_files,
        ),
    }


def regenerate_fechamento(
        *,
        id_items: list[dict],
        parent_id: str,
        user: str = "",
        analysis_path: str | None = None,
        diff_folder: str | None = None,
        source_mode: str = SOURCE_ANALYSIS,
        use_diffs: bool = True,
        output_dir: str | None = None,
        preserve_files: bool = True,
        synthesize_fn=None,
        selected_model: str | None = None,
        target_task_count: int | None = None,
) -> tuple[dict, str]:
    """
    Regenerate fechamento JSON from analysis or checkpoint + Redmine IDs.

    Returns (payload, saved_path).
    """
    source_mode = (source_mode or SOURCE_ANALYSIS).lower()
    source_label = ""

    if source_mode == SOURCE_CHECKPOINT:
        source_diff = diff_folder or ""
        if not source_diff:
            raise ValueError("Selecione a pasta de diffs que contém o checkpoint.")
        tasks = load_tasks_from_checkpoint(source_diff)
        source_label = f"checkpoint:{os.path.basename(source_diff)}"
    else:
        if not analysis_path:
            raise ValueError("Selecione uma análise IA salva.")
        analysis = load_analysis_payload(analysis_path)
        tasks = [dict(t) for t in analysis.get("tasks", [])]
        source_diff = (
            diff_folder
            or analysis.get("source_diff_folder")
            or ""
        )
        source_label = os.path.basename(analysis_path)

    tasks, commits_index = prepare_tasks_with_commits(
        tasks,
        source_diff or None,
        use_diffs=use_diffs,
    )

    if synthesize_fn and selected_model and target_task_count and len(tasks) != target_task_count:
        if len(tasks) > target_task_count:
            try:
                tasks = synthesize_fn(tasks, selected_model, min_hours=get_min_task_hours())
            except Exception as ex:
                print(f"[FECHAMENTO] Síntese durante regeneração falhou ({ex}). Usando tarefas originais.")

    payload = build_fechamento_payload(
        parent_id=parent_id,
        id_items=id_items,
        tasks=tasks,
        commits_index=commits_index,
        generated_by=user,
        source_analysis=source_label,
        source_diff_folder=source_diff or "",
        preserve_files=preserve_files,
    )
    payload["source_mode"] = source_mode
    payload["use_diffs"] = bool(use_diffs)

    save_dir = output_dir
    if not save_dir and source_diff:
        candidate = resolve_diff_folder_path(source_diff)
        if candidate:
            save_dir = candidate

    path = save_fechamento(payload, user or "desconhecido", output_dir=save_dir)
    return payload, path
