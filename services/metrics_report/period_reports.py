"""Read saved monthly report folders and build cover + year + months."""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from collections import defaultdict

from services.metrics_report.aggregate import ProgressCallback, aggregate_tasks, parse_report_date
from services.metrics_report.art_direction import fetch_art_direction
from services.metrics_report.pdf_report import write_metrics_pdf
from utils.month_selector import MONTH_NAMES
from utils.app_config import ensure_task_manager_dirs, task_manager_dir
from utils.output_paths import safe_segment
from utils.pdf_merger import merge_documents


def metrics_project_dir(project: str, root: str | None = None) -> str:
    if root is None:
        ensure_task_manager_dirs()
        base = str(task_manager_dir())
    else:
        base = root
    return os.path.join(base, "relatorios", "metricas", safe_segment(project) or "projeto")


def list_period_reports(project: str, root: str | None = None) -> list[dict]:
    """Monthly folders that have meta.json kind=periodo, calendar order."""
    project_dir = metrics_project_dir(project, root)
    if not os.path.isdir(project_dir):
        return []
    found: list[dict] = []
    for name in os.listdir(project_dir):
        folder = os.path.join(project_dir, name)
        meta_path = os.path.join(folder, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict) or meta.get("kind") != "periodo":
            continue
        period = meta.get("period") or {}
        try:
            year = int(period["year"])
            month = int(period["month"])
        except (KeyError, TypeError, ValueError):
            continue
        tasks_path = meta.get("tasks_copy") or os.path.join(folder, "tarefas.json")
        pdf_path = meta.get("pdf") or os.path.join(folder, "periodo.pdf")
        if not os.path.isabs(tasks_path):
            tasks_path = os.path.join(folder, tasks_path)
        if not os.path.isabs(pdf_path):
            pdf_path = os.path.join(folder, pdf_path)
        found.append({
            "folder": folder,
            "meta": meta,
            "year": year,
            "month": month,
            "label": period.get("label") or f"{year}-{month:02d}",
            "tasks_path": tasks_path,
            "pdf_path": os.path.join(folder, "periodo.pdf"),
            "task_count": meta.get("task_count") or 0,
        })
    found.sort(key=lambda item: (item["year"], item["month"]))
    return found


def _load_tasks(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list):
        raise ValueError(f"Sem lista de tarefas em {path}")
    return [dict(task) for task in tasks if isinstance(task, dict)]


def write_period_folders(
        project: str,
        tasks: list[dict],
        *,
        root: str | None = None,
) -> list[dict]:
    """
    Group tasks by their period metadata and write one folder per month.
    Tasks without a period are not given the lote save date.
    """
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if not task.get("work_date") and not isinstance(task.get("period"), dict):
            continue
        when = parse_report_date(task)
        if when is None:
            continue
        grouped[(when.year, when.month)].append(dict(task))
    if not grouped:
        raise ValueError(
            "Nenhuma tarefa selecionada tem período. "
            "O dia em que o lote foi salvo não define o mês do relatório."
        )

    project_dir = metrics_project_dir(project, root)
    os.makedirs(project_dir, exist_ok=True)
    written: list[dict] = []
    for year, month in sorted(grouped):
        items = grouped[(year, month)]
        period = {
            "year": year,
            "month": month,
            "label": f"{MONTH_NAMES[month - 1]} {year}",
        }
        for item in items:
            item["period"] = dict(period)
            item["date_precision"] = "month"
        folder = os.path.join(project_dir, f"{year}-{month:02d}_{MONTH_NAMES[month - 1]}")
        os.makedirs(folder, exist_ok=True)
        tasks_path = os.path.join(folder, "tarefas.json")
        pdf_path = os.path.join(folder, "periodo.pdf")
        with open(tasks_path, "w", encoding="utf-8") as handle:
            json.dump({"period": period, "project": project, "tasks": items}, handle, ensure_ascii=False, indent=2)
        meta = {
            "kind": "periodo",
            "project": project,
            "period": period,
            "task_count": len(items),
            "tasks_copy": os.path.abspath(tasks_path),
            "pdf": os.path.abspath(pdf_path),
            "written_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, indent=2)
        written.append({
            "folder": folder,
            "meta": meta,
            "year": year,
            "month": month,
            "label": period["label"],
            "tasks_path": tasks_path,
            "pdf_path": pdf_path,
            "task_count": len(items),
        })
    return written


def consolidate_tasks(
        tasks: list[dict],
        project: str,
        dest_path: str,
        *,
        cover_pdf: str | None = None,
        close_pdf: str | None = None,
        on_progress: ProgressCallback | None = None,
) -> str:
    """One file: optional cover, year page, monthly chapters, optional close."""
    log = on_progress or (lambda _message: None)
    if not tasks:
        raise ValueError("Nenhuma tarefa para o relatório.")
    log("Direção visual")
    direction = fetch_art_direction(aggregate_tasks(tasks, on_progress=log), project)
    year_fd, year_pdf = tempfile.mkstemp(suffix=".pdf")
    month_fd, month_pdf = tempfile.mkstemp(suffix=".pdf")
    os.close(year_fd)
    os.close(month_fd)
    try:
        log("Página anual")
        write_metrics_pdf(year_pdf, tasks, project, art=direction, body="year", on_progress=log)
        log("Capítulos mensais")
        write_metrics_pdf(month_pdf, tasks, project, art=direction, body="months", on_progress=log)
        parts: list[str] = []
        if cover_pdf:
            parts.append(cover_pdf)
        parts.append(year_pdf)
        parts.append(month_pdf)
        if close_pdf:
            parts.append(close_pdf)
        merge_documents(parts, dest_path)
    finally:
        for path in (year_pdf, month_pdf):
            try:
                os.remove(path)
            except OSError:
                pass
    log(f"Consolidado: {os.path.abspath(dest_path)}")
    return os.path.abspath(dest_path)


def consolidate_period_reports(
        project: str,
        reports: list[dict],
        *,
        cover_pdf: str | None = None,
        close_pdf: str | None = None,
        on_progress: ProgressCallback | None = None,
        root: str | None = None,
        art=None,
) -> str:
    """
    Rebuild each monthly PDF from its tarefas.json, then write
    cover + year page + those monthly PDFs + optional close.
    """
    log = on_progress or (lambda _message: None)
    if not reports:
        raise ValueError("Nenhum relatório mensal selecionado.")

    ordered = sorted(reports, key=lambda item: (item["year"], item["month"]))
    by_year: dict[int, list[dict]] = defaultdict(list)
    loaded: dict[str, list[dict]] = {}
    for item in ordered:
        tasks = _load_tasks(item["tasks_path"])
        loaded[item["folder"]] = tasks
        by_year[item["year"]].append(item)
        log(f"Referência {item['label']}: {len(tasks)} tarefa(s)")

    all_tasks = [task for tasks in loaded.values() for task in tasks]
    if art is not None:
        direction = art
        log("Visual: direção informada")
    else:
        log("Direção visual da consolidação")
        direction = fetch_art_direction(aggregate_tasks(all_tasks), project)

    parts: list[str] = []
    if cover_pdf:
        log(f"Capa: {cover_pdf}")
        parts.append(cover_pdf)

    project_dir = metrics_project_dir(project, root)
    for year in sorted(by_year):
        months = by_year[year]
        year_tasks: list[dict] = []
        month_pdfs: list[str] = []
        total = len(months)
        for index, item in enumerate(months, start=1):
            tasks = loaded[item["folder"]]
            year_tasks.extend(tasks)
            pdf_path = item["pdf_path"]
            log(f"PDF mensal {index}/{total}: {item['label']}")
            write_metrics_pdf(
                pdf_path,
                tasks,
                project,
                art=direction,
                body="months",
                on_progress=log,
            )
            month_pdfs.append(pdf_path)

        year_dir = os.path.join(project_dir, f"{year}_anual")
        os.makedirs(year_dir, exist_ok=True)
        year_pdf = os.path.join(year_dir, "ano.pdf")
        log(f"Página anual {year}")
        write_metrics_pdf(
            year_pdf,
            year_tasks,
            project,
            art=direction,
            body="year",
            on_progress=log,
        )
        parts.append(year_pdf)
        parts.extend(month_pdfs)

    if close_pdf:
        log(f"Encerramento: {close_pdf}")
        parts.append(close_pdf)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = os.path.join(project_dir, f"consolidado_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, "anual.pdf")
    log(f"Unindo {len(parts)} PDF(s)")
    merge_documents(parts, dest)
    meta = {
        "kind": "consolidado",
        "project": project,
        "order": "capa, pagina anual, relatorios mensais, encerramento",
        "parts": [os.path.abspath(path) for path in parts],
        "pdf": os.path.abspath(dest),
        "written_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
    log(f"Consolidado: {os.path.abspath(dest)}")
    return os.path.abspath(dest)
