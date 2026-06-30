# ui_components.py
import flet as ft
import datetime


class DatePickerField(ft.Row):
    def __init__(self, label: str, default_date: datetime.date, width: int = 200, icon=ft.Icons.CALENDAR_TODAY):
        super().__init__()
        self.alignment = ft.MainAxisAlignment.START
        self.spacing = 0

        # 1. The hidden Date Picker Dialog
        self.date_picker = ft.DatePicker(
            on_change=self._handle_date_change,
            first_date=datetime.datetime(2020, 1, 1),
            last_date=datetime.datetime(2030, 12, 31),
            help_text=f"Selecione: {label}",
            value=datetime.datetime.combine(default_date, datetime.time()),
        )

        # 2. The visible Text Field
        self.text_field = ft.TextField(
            label=label,
            value=default_date.strftime("%Y-%m-%d"),
            width=width,
            icon=icon,
            read_only=True,  # Prevent manual typing to enforce format
        )

        # 3. The invisible button over the TextField (or an icon button next to it)
        # We will use an IconButton right next to the text field to trigger the calendar
        self.btn_calendar = ft.IconButton(
            icon=ft.Icons.EDIT_CALENDAR,
            tooltip="Abrir calendário",
            on_click=self._open_calendar
        )

        # Add them to the Row
        self.controls = [self.text_field, self.btn_calendar]

    def _handle_date_change(self, e):
        # Update the text field when a date is selected
        if self.date_picker.value:
            self.text_field.value = self.date_picker.value.strftime("%Y-%m-%d")
            self.update()

    def _open_calendar(self, e):
        if self.date_picker not in e.page.overlay:
            e.page.overlay.append(self.date_picker)
        e.page.open(self.date_picker)

    def set_date(self, target_date: datetime.date):
        self.text_field.value = target_date.strftime("%Y-%m-%d")
        self.date_picker.value = datetime.datetime.combine(target_date, datetime.time())

    @property
    def value(self):
        return self.text_field.value