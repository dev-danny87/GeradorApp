"""Pure helpers for selecting whole tasks against an hour budget."""

from __future__ import annotations


def task_hours(task: dict) -> float:
    try:
        return float(task.get("estimated_hours", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def sum_task_hours(tasks: list[dict]) -> float:
    return round(sum(task_hours(t) for t in tasks), 2)


def ensure_task_ids(tasks: list[dict], prefix: str = "task") -> list[dict]:
    """Return copies with a stable task_id when missing."""
    result: list[dict] = []
    for index, task in enumerate(tasks, start=1):
        copy = dict(task)
        if not copy.get("task_id"):
            copy["task_id"] = f"{prefix}-{index:04d}"
        result.append(copy)
    return result


def select_tasks_by_budget(
        tasks: list[dict],
        budget_hours: float,
) -> list[str]:
    """
    Prefer largest tasks first, but keep filling with smaller ones that still fit.
    Never splits a task. Returns the selected task_id list.
    """
    if not tasks or budget_hours is None or budget_hours <= 0:
        return []

    ordered = sorted(tasks, key=lambda t: task_hours(t), reverse=True)
    selected: list[str] = []
    running = 0.0
    for task in ordered:
        hours = task_hours(task)
        task_id = str(task.get("task_id") or "")
        if not task_id:
            continue
        if running + hours <= float(budget_hours) + 1e-9:
            selected.append(task_id)
            running = round(running + hours, 2)
    return selected


def partition_by_ids(
        tasks: list[dict],
        selected_ids: set[str] | list[str],
) -> tuple[list[dict], list[dict]]:
    """Split tasks into (selected, remainder) preserving original order."""
    ids = {str(tid) for tid in selected_ids if tid}
    selected: list[dict] = []
    remainder: list[dict] = []
    for task in tasks:
        if str(task.get("task_id") or "") in ids:
            selected.append(task)
        else:
            remainder.append(task)
    return selected, remainder
