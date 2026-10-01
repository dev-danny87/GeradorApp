"""Shared collapsed task list with hour-budget selection (Flet)."""

from __future__ import annotations

import flet as ft

from utils.task_hour_selection import select_tasks_by_budget, sum_task_hours, task_hours


class TaskHourListView:
    """
    Collapsed ExpansionTile of tasks with checkboxes and a Horas a criar field.
    Selection never splits a task.
    """

    def __init__(
            self,
            *,
            title: str = "Tarefas estimadas",
            on_selection_change=None,
            initially_expanded: bool = False,
    ):
        self._tasks: list[dict] = []
        self._checkboxes: dict[str, ft.Checkbox] = {}
        self._on_selection_change = on_selection_change
        self._applying_budget = False

        self.lbl_summary = ft.Text("", size=12, color=ft.Colors.GREY_700)
        self.txt_budget = ft.TextField(
            label="Horas a criar",
            width=160,
            input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9.]*$", replacement_string=""),
            on_change=self._on_budget_change,
        )
        self.lbl_selection = ft.Text("", size=12, weight=ft.FontWeight.BOLD)

        self.task_column = ft.Column(spacing=4, tight=True)
        self.expansion = ft.ExpansionTile(
            title=ft.Text(title, weight=ft.FontWeight.BOLD),
            subtitle=self.lbl_summary,
            initially_expanded=initially_expanded,
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [self.txt_budget, self.lbl_selection],
                                alignment=ft.MainAxisAlignment.START,
                                wrap=True,
                                spacing=16,
                            ),
                            self.task_column,
                        ],
                        spacing=10,
                        tight=True,
                    ),
                    padding=ft.padding.only(left=8, right=8, bottom=8),
                )
            ],
        )
        self.root = ft.Container(
            content=self.expansion,
            border=ft.border.all(1, ft.Colors.PURPLE_200),
            border_radius=8,
            padding=5,
            visible=False,
        )

    @property
    def tasks(self) -> list[dict]:
        return list(self._tasks)

    def selected_ids(self) -> set[str]:
        return {
            task_id
            for task_id, checkbox in self._checkboxes.items()
            if checkbox.value
        }

    def selected_tasks(self) -> list[dict]:
        ids = self.selected_ids()
        return [t for t in self._tasks if str(t.get("task_id") or "") in ids]

    def remainder_tasks(self) -> list[dict]:
        ids = self.selected_ids()
        return [t for t in self._tasks if str(t.get("task_id") or "") not in ids]

    def set_tasks(self, tasks: list[dict], *, select_all: bool = False):
        self._tasks = [dict(t) for t in tasks]
        self._checkboxes.clear()
        self.task_column.controls.clear()

        total = sum_task_hours(self._tasks)
        count = len(self._tasks)
        self.lbl_summary.value = f"{count} tarefa(s) — {total:g}h no total"
        self.root.visible = count > 0

        for task in self._tasks:
            task_id = str(task.get("task_id") or "")
            if not task_id:
                continue
            hours = task_hours(task)
            title = task.get("task_title") or task.get("title") or "(sem título)"
            category = task.get("category") or ""
            description = (task.get("description") or "").strip() or "Sem descrição."

            checkbox = ft.Checkbox(
                value=bool(select_all),
                on_change=self._on_checkbox_change,
            )
            self._checkboxes[task_id] = checkbox

            header = ft.Row(
                [
                    checkbox,
                    ft.Text(title, weight=ft.FontWeight.W_500, expand=True),
                    ft.Text(category, size=11, color=ft.Colors.BLUE_GREY_600),
                    ft.Text(f"{hours:g}h", weight=ft.FontWeight.BOLD, width=60),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            self.task_column.controls.append(
                ft.ExpansionTile(
                    title=header,
                    controls=[
                        ft.Container(
                            content=ft.Text(description, size=12, selectable=True),
                            padding=ft.padding.only(left=40, right=8, bottom=8),
                        )
                    ],
                    dense=True,
                )
            )

        self._refresh_selection_label()
        self._notify()

    def apply_budget(self, budget_hours: float | None = None):
        if budget_hours is None:
            raw = (self.txt_budget.value or "").strip()
            if not raw:
                return
            try:
                budget_hours = float(raw)
            except ValueError:
                return

        self._applying_budget = True
        try:
            selected = set(select_tasks_by_budget(self._tasks, float(budget_hours)))
            for task_id, checkbox in self._checkboxes.items():
                checkbox.value = task_id in selected
        finally:
            self._applying_budget = False

        self._refresh_selection_label()
        self._notify()

    def clear(self):
        self.set_tasks([])
        self.txt_budget.value = ""

    def _on_budget_change(self, e):
        self.apply_budget()
        try:
            page = self.root.page
        except RuntimeError:
            return
        if page:
            page.update()

    def _on_checkbox_change(self, e):
        if self._applying_budget:
            return
        self._refresh_selection_label()
        self._notify()
        try:
            page = self.root.page
        except RuntimeError:
            return
        if page:
            page.update()

    def _refresh_selection_label(self):
        selected = self.selected_tasks()
        selected_hours = sum_task_hours(selected)
        remainder = sum_task_hours(self.remainder_tasks())
        self.lbl_selection.value = (
            f"Selecionadas: {len(selected)} ({selected_hours:g}h) — "
            f"Restantes: {remainder:g}h"
        )

    def _notify(self):
        if self._on_selection_change:
            try:
                self._on_selection_change(self)
            except Exception:
                pass
