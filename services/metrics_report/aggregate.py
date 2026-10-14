"""Group selected banco tasks into years and months. This module never writes files."""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from utils.commit_metadata import build_detailed_fechamento_notas

CATEGORY_ORDER = ("Feature", "Bugfix", "Refactor", "Test", "Chore", "Outros")
TIMELINE_LIMIT = 14
ProgressCallback = Callable[[str], None]

_CANONICAL_CATEGORY = {
    "feature": "Feature",
    "bugfix": "Bugfix",
    "bug": "Bugfix",
    "refactor": "Refactor",
    "test": "Test",
    "tests": "Test",
    "chore": "Chore",
}


def normalize_category(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    return _CANONICAL_CATEGORY.get(key, "Outros")


def _parse_iso_date(raw) -> datetime.date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_report_date(task: dict) -> datetime.date | None:
    """Prefer the period stamped on the task, then the lote save time."""
    worked = _parse_iso_date(task.get("work_date"))
    if worked:
        return worked
    period = task.get("period")
    if isinstance(period, dict):
        try:
            return datetime.date(int(period["year"]), int(period["month"]), 1)
        except (KeyError, TypeError, ValueError):
            pass
    return _parse_iso_date(task.get("_report_date") or task.get("saved_at") or "")


def _day_known(task: dict, spent_on: datetime.date) -> bool:
    """A period stamp on the 1st is the month, not the day the work was done."""
    precision = str(task.get("date_precision") or "").strip().lower()
    if precision == "month":
        return False
    if precision == "day":
        return True
    period = task.get("period")
    if isinstance(period, dict):
        try:
            same_month = (
                spent_on.year == int(period["year"])
                and spent_on.month == int(period["month"])
            )
        except (KeyError, TypeError, ValueError):
            same_month = False
        if same_month and spent_on.day == 1:
            return False
    return True


def _hours(task: dict) -> float:
    try:
        value = float(task.get("estimated_hours") or 0)
    except (TypeError, ValueError):
        return 0.0
    if value < 0:
        return 0.0
    return round(value, 2)


def _links(task: dict) -> tuple[str, ...]:
    raw = task.get("commit_links") or []
    if not isinstance(raw, list):
        return ()
    found = {str(url).strip() for url in raw if str(url).strip()}
    return tuple(sorted(found))


def _files(task: dict) -> list[str]:
    raw = task.get("affected_files") or []
    if not isinstance(raw, list):
        return []
    return [str(path).strip() for path in raw if str(path).strip()]


@dataclass(frozen=True)
class ReportTask:
    task_id: str
    title: str
    category: str
    hours: float
    spent_on: datetime.date
    notes: str
    commit_links: tuple[str, ...]
    day_known: bool = True


@dataclass(frozen=True)
class MonthSlice:
    year: int
    month: int
    tasks: tuple[ReportTask, ...]
    total_hours: float
    hours_with_commits: float
    hours_without_commits: float
    commit_urls: tuple[str, ...]
    tasks_without_commits: int
    hours_by_category: tuple[tuple[str, float], ...]

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def commit_count(self) -> int:
        return len(self.commit_urls)

    @property
    def percent_complete(self) -> int:
        return _percent(self.hours_with_commits, self.total_hours)


@dataclass(frozen=True)
class YearSlice:
    year: int
    months: tuple[MonthSlice, ...]

    @property
    def tasks(self) -> tuple[ReportTask, ...]:
        return tuple(task for month in self.months for task in month.tasks)

    @property
    def total_hours(self) -> float:
        return round(sum(month.total_hours for month in self.months), 2)

    @property
    def hours_with_commits(self) -> float:
        return round(sum(month.hours_with_commits for month in self.months), 2)

    @property
    def hours_without_commits(self) -> float:
        return round(max(0.0, self.total_hours - self.hours_with_commits), 2)

    @property
    def task_count(self) -> int:
        return sum(month.task_count for month in self.months)

    @property
    def tasks_without_commits(self) -> int:
        return sum(month.tasks_without_commits for month in self.months)

    @property
    def commit_urls(self) -> tuple[str, ...]:
        found: set[str] = set()
        for month in self.months:
            found.update(month.commit_urls)
        return tuple(sorted(found))

    @property
    def commit_count(self) -> int:
        return len(self.commit_urls)

    @property
    def percent_complete(self) -> int:
        return _percent(self.hours_with_commits, self.total_hours)

    @property
    def hours_by_category(self) -> tuple[tuple[str, float], ...]:
        totals = {name: 0.0 for name in CATEGORY_ORDER}
        for month in self.months:
            for name, hours in month.hours_by_category:
                totals[name] = totals.get(name, 0.0) + hours
        return tuple(
            (name, round(totals[name], 2))
            for name in CATEGORY_ORDER
            if totals[name] > 0
        )

    def hours_of_month(self, month: int) -> float:
        for item in self.months:
            if item.month == month:
                return item.total_hours
        return 0.0


@dataclass(frozen=True)
class ReportBundle:
    years: tuple[YearSlice, ...]
    prepared_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


def tasks_for_timeline(tasks: tuple[ReportTask, ...] | list[ReportTask], limit: int = TIMELINE_LIMIT) -> list[ReportTask]:
    """Up to `limit` tasks, preferring the ones with the most hours, then by date."""
    ranked = sorted(tasks, key=lambda task: (-task.hours, task.spent_on, task.title, task.task_id))
    chosen = ranked[:limit]
    return sorted(chosen, key=lambda task: (task.spent_on, task.title, task.task_id))


def prepare_report_task(task: dict) -> ReportTask:
    """Build one report task. Raises when the lote date is missing or notes fail."""
    if not isinstance(task, dict):
        raise TypeError("A tarefa precisa ser um objeto.")
    spent_on = parse_report_date(task)
    if spent_on is None:
        title = (str(task.get("task_title") or task.get("title") or "")).strip() or "(sem título)"
        raise ValueError(f"Data do lote ausente ou inválida: {title}")
    return _build_task(task, spent_on)


def aggregate_tasks(
        tasks: list[dict],
        *,
        on_progress: ProgressCallback | None = None,
) -> ReportBundle:
    """Build the report model from in-memory tasks. Does not read or write the banco."""
    log = on_progress or (lambda _message: None)
    total = len(tasks)
    grouped: dict[tuple[int, int], list[ReportTask]] = defaultdict(list)
    prepared = 0
    failed = 0
    skipped = 0

    for index, task in enumerate(tasks, start=1):
        title_hint = ""
        if isinstance(task, dict):
            title_hint = (str(task.get("task_title") or task.get("title") or "")).strip()
        label = title_hint or f"tarefa {index}"
        try:
            report_task = prepare_report_task(task)
        except Exception as err:
            failed += 1
            skipped += 1
            log(f"{index}/{total} — pulada: {label} ({err})")
            continue

        prepared += 1
        grouped[(report_task.spent_on.year, report_task.spent_on.month)].append(report_task)
        when = (
            report_task.spent_on.strftime("%d/%m/%Y")
            if report_task.day_known
            else report_task.spent_on.strftime("%m/%Y")
        )
        log(
            f"{index}/{total} — {report_task.title} "
            f"({report_task.hours:g}h, {when})"
        )

    if not grouped:
        raise ValueError("Nenhuma tarefa com data de lote válida.")

    years: list[YearSlice] = []
    for year in sorted({key[0] for key in grouped}):
        months = []
        for month in sorted(key[1] for key in grouped if key[0] == year):
            items = tuple(sorted(
                grouped[(year, month)],
                key=lambda item: (item.spent_on, item.title, item.task_id),
            ))
            months.append(_make_month(year, month, items))
        years.append(YearSlice(year=year, months=tuple(months)))

    log(f"Agrupamento: {prepared} tarefa(s) em {len(years)} ano(s); {failed} falha(s).")
    return ReportBundle(
        years=tuple(years),
        prepared_count=prepared,
        failed_count=failed,
        skipped_count=skipped,
    )


def _build_task(task: dict, spent_on: datetime.date) -> ReportTask:
    category = normalize_category(str(task.get("category") or ""))
    hours = _hours(task)
    links = _links(task)
    title = (str(task.get("task_title") or task.get("title") or "")).strip() or "Tarefa técnica"
    notes = build_detailed_fechamento_notas({
        "task_title": title,
        "category": category,
        "estimated_hours": hours,
        "description": str(task.get("description") or ""),
        "affected_files": _files(task),
        "commit_links": list(links),
    })
    return ReportTask(
        task_id=str(task.get("task_id") or ""),
        title=title,
        category=category,
        hours=hours,
        spent_on=spent_on,
        notes=notes,
        commit_links=links,
        day_known=_day_known(task, spent_on),
    )


def _make_month(year: int, month: int, tasks: tuple[ReportTask, ...]) -> MonthSlice:
    total = round(sum(task.hours for task in tasks), 2)
    with_commits = round(sum(task.hours for task in tasks if task.commit_links), 2)
    without = round(max(0.0, total - with_commits), 2)
    urls: set[str] = set()
    for task in tasks:
        urls.update(task.commit_links)
    buckets = {name: 0.0 for name in CATEGORY_ORDER}
    for task in tasks:
        buckets[task.category] = buckets.get(task.category, 0.0) + task.hours
    categories = tuple(
        (name, round(buckets[name], 2))
        for name in CATEGORY_ORDER
        if buckets[name] > 0
    )
    missing = sum(1 for task in tasks if not task.commit_links)
    return MonthSlice(
        year=year,
        month=month,
        tasks=tasks,
        total_hours=total,
        hours_with_commits=with_commits,
        hours_without_commits=without,
        commit_urls=tuple(sorted(urls)),
        tasks_without_commits=missing,
        hours_by_category=categories,
    )


def _percent(part: float, total: float) -> int:
    if total <= 0:
        return 0
    return int(round(100.0 * part / total))
