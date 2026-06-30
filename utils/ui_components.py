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
            help_text=f"Selecione: {label}"
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
        # e.page ensures we can open the dialog without needing to pass the 'page' object everywhere
        e.page.open(self.date_picker)

    @property
    def value(self):
        # A helper property so you can easily get the value just like a normal TextField
        return self.text_field.value