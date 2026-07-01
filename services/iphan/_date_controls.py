import datetime

import flet as ft

from services.iphan._common import month_bounds
from utils.month_selector import create_month_shortcut_dropdown
from utils.ui_components import DatePickerField


def _apply_month_selection(
    month_key: str,
    date_start: DatePickerField,
    date_end: DatePickerField,
) -> None:
    year_str, month_str = month_key.split("-", 1)
    start_date, end_date = month_bounds(datetime.date(int(year_str), int(month_str), 1))
    date_start.set_date(start_date)
    date_end.set_date(end_date)


def build_date_controls(cache: dict) -> tuple[DatePickerField, DatePickerField]:
    if "date_start" in cache and "date_end" in cache:
        return cache["date_start"], cache["date_end"]

    start_default, end_default = month_bounds()
    date_start = DatePickerField(label="Data inicial", default_date=start_default, width=190)
    date_end = DatePickerField(label="Data final", default_date=end_default, width=190, icon=ft.Icons.EVENT)

    def on_month_change(e):
        if not dropdown_month.value:
            return
        _apply_month_selection(dropdown_month.value, date_start, date_end)
        if date_start.page:
            date_start.update()
            date_end.update()

    dropdown_month = create_month_shortcut_dropdown(
        on_month_change,
        value=f"{start_default.year:04d}-{start_default.month:02d}",
    )

    cache["date_start"] = date_start
    cache["date_end"] = date_end
    cache["month_dropdown"] = dropdown_month
    cache["controls"] = [
        ft.Row([dropdown_month], alignment=ft.MainAxisAlignment.CENTER),
        ft.Row([date_start, date_end], alignment=ft.MainAxisAlignment.CENTER, spacing=20),
    ]
    return date_start, date_end
