import calendar
import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

import flet as ft

if TYPE_CHECKING:
    from utils.ui_components import DatePickerField

MONTH_NAMES = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)

MONTH_NAMES_UPPER = tuple(name.upper() for name in MONTH_NAMES)


def current_month_key(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    return f"{today.year:04d}-{today.month:02d}"


def month_options(count: int = 24) -> list[tuple[str, str]]:
    today = datetime.date.today()
    year, month = today.year, today.month
    options: list[tuple[str, str]] = []

    for _ in range(count):
        key = f"{year:04d}-{month:02d}"
        label = f"{MONTH_NAMES[month - 1]}/{year}"
        options.append((key, label))
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return options


def month_bounds(reference: datetime.date | None = None) -> tuple[datetime.date, datetime.date]:
    reference = reference or datetime.date.today()
    last_day = calendar.monthrange(reference.year, reference.month)[1]
    return reference.replace(day=1), reference.replace(day=last_day)


def apply_month_to_date_pickers(
    month_key: str,
    date_start: "DatePickerField",
    date_end: "DatePickerField",
) -> None:
    year_str, month_str = month_key.split("-", 1)
    start_date, end_date = month_bounds(datetime.date(int(year_str), int(month_str), 1))
    date_start.set_date(start_date)
    date_end.set_date(end_date)


def month_label_for_key(month_key: str) -> str:
    for key, label in month_options(240):
        if key == month_key:
            return label
    year_str, month_str = month_key.split("-", 1)
    return f"{MONTH_NAMES[int(month_str) - 1]}/{year_str}"


def create_month_shortcut_dropdown(
    on_change: Callable,
    *,
    width: int = 400,
    value: Optional[str] = None,
) -> ft.Dropdown:
    dropdown = ft.Dropdown(
        label="Mês",
        width=width,
        tooltip="Atalho para mês completo",
        options=[ft.dropdown.Option(key=key, text=label) for key, label in month_options()],
        value=value or current_month_key(),
    )
    dropdown.on_change = on_change
    return dropdown
