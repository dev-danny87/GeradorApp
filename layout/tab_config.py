import flet as ft

from redmine_mappings import (
    ORGAN_OPTIONS,
    PROJECT_FILTER_OPTIONS,
    ROLE_OPTIONS,
    SYSTEM_OPTIONS,
    USER_OPTIONS,
)
from utils.app_config import (
    GE_TXT_DEFAULT_VALUES,
    GE_TXT_DEFAULTS,
    ge_txt_path,
    keys_overridden_by_env,
    load_ge_txt_values,
    save_ge_txt,
)

_FIELD_LABELS = {
    "RD_HOST": "Redmine Host",
    "RD_USER": "Redmine Usuário",
    "RD_PASS": "Redmine Senha",
    "CLAUDE_KEY": "Claude API Key",
    "GITLAB_TOKEN": "GitLab Token",
    "GITHUB_TOKEN": "GitHub Token",
    "STARTING_DATE": "Starting Date",
    "STARTING_VERSAO": "Starting Versão",
    "THREADS": "Threads",
    "GITLAB_DEFAULT_AUTHOR": "Autor padrão GitLab",
    "GITHUB_DEFAULT_AUTHOR": "Autor padrão GitHub",
    "DIFF_DEFAULT_PLATFORM": "Plataforma padrão (Diffs)",
    "RD_DEFAULT_SISTEMA": "Sistema padrão",
    "RD_DEFAULT_ORGAO": "Órgão solicitante padrão",
    "RD_DEFAULT_ATRIBUICAO": "Atribuição Catálogo - Desenv padrão",
    "RD_DEFAULT_PROJETO": "Projeto Vinculado padrão",
    "RD_DEFAULT_DESENVOLVEDOR": "Desenvolvedor padrão",
    "RD_MIN_TASK_HOURS": "Mínimo de horas por tarefa (agrupamento IA)",
}

_SSP_DROPDOWN_KEYS = {
    "RD_DEFAULT_SISTEMA": (SYSTEM_OPTIONS, "RD_DEFAULT_SISTEMA"),
    "RD_DEFAULT_ORGAO": (ORGAN_OPTIONS, "RD_DEFAULT_ORGAO"),
    "RD_DEFAULT_ATRIBUICAO": (ROLE_OPTIONS, "RD_DEFAULT_ATRIBUICAO"),
    "RD_DEFAULT_PROJETO": (PROJECT_FILTER_OPTIONS, "RD_DEFAULT_PROJETO"),
}


def _dropdown_from_mapping(label: str, mapping: dict, default_value: str, width: int = 420) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        width=width,
        options=[ft.dropdown.Option(key=v, text=k) for k, v in mapping.items()],
        value=default_value if default_value in mapping.values() else None,
    )


def create_config_tab(app_state, set_auth, sync_callbacks):
    lbl_path = ft.Text(
        str(ge_txt_path()),
        size=13,
        selectable=True,
        color="grey",
    )
    lbl_env_warning = ft.Text("", color="orange", visible=False, size=13)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)

    fields: dict[str, ft.Control] = {}

    def _make_text_field(key: str, password: bool = False) -> ft.TextField:
        return ft.TextField(
            label=_FIELD_LABELS.get(key, key),
            width=420,
            password=password,
            can_reveal_password=password,
        )

    for key in ("GITLAB_TOKEN", "GITHUB_TOKEN", "CLAUDE_KEY", "RD_PASS"):
        fields[key] = _make_text_field(key, password=True)

    fields["GITLAB_DEFAULT_AUTHOR"] = _make_text_field("GITLAB_DEFAULT_AUTHOR")
    fields["GITHUB_DEFAULT_AUTHOR"] = _make_text_field("GITHUB_DEFAULT_AUTHOR")
    fields["DIFF_DEFAULT_PLATFORM"] = ft.Dropdown(
        label=_FIELD_LABELS["DIFF_DEFAULT_PLATFORM"],
        width=420,
        options=[
            ft.dropdown.Option(key="gitlab", text="GitLab"),
            ft.dropdown.Option(key="github", text="GitHub"),
        ],
        value="gitlab",
    )

    fields["RD_HOST"] = _make_text_field("RD_HOST")
    fields["RD_USER"] = _make_text_field("RD_USER")
    fields["STARTING_DATE"] = _make_text_field("STARTING_DATE")
    fields["STARTING_VERSAO"] = _make_text_field("STARTING_VERSAO")
    fields["THREADS"] = ft.TextField(
        label=_FIELD_LABELS["THREADS"],
        width=200,
        input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9]*$", replacement_string=""),
    )

    for key, (mapping, default_key) in _SSP_DROPDOWN_KEYS.items():
        fields[key] = _dropdown_from_mapping(
            _FIELD_LABELS[key],
            mapping,
            GE_TXT_DEFAULT_VALUES.get(default_key, ""),
        )

    fields["RD_DEFAULT_DESENVOLVEDOR"] = ft.Dropdown(
        label=_FIELD_LABELS["RD_DEFAULT_DESENVOLVEDOR"],
        width=420,
        options=[ft.dropdown.Option(key=v, text=k) for k, v in USER_OPTIONS.items()],
        value=None,
        hint_text="Opcional — usa o login mapeado se vazio",
    )
    fields["RD_MIN_TASK_HOURS"] = ft.TextField(
        label=_FIELD_LABELS["RD_MIN_TASK_HOURS"],
        width=200,
        input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9.]*$", replacement_string=""),
    )

    btn_save = ft.ElevatedButton(
        "Salvar",
        icon=ft.Icons.SAVE,
        bgcolor="blue",
        color="white",
    )

    def _show_status(message: str, color: str):
        lbl_status.value = message
        lbl_status.color = color
        lbl_status.visible = True
        if lbl_status.page:
            lbl_status.update()

    def _field_value(key: str) -> str:
        control = fields[key]
        return (control.value or "").strip()

    def _set_field_value(key: str, value: str):
        control = fields[key]
        if key == "DIFF_DEFAULT_PLATFORM":
            platform = (value or "gitlab").lower()
            control.value = platform if platform in ("gitlab", "github") else "gitlab"
        elif key == "THREADS":
            control.value = value if value else GE_TXT_DEFAULT_VALUES.get("THREADS", "1")
        elif key in _SSP_DROPDOWN_KEYS:
            mapping, default_key = _SSP_DROPDOWN_KEYS[key]
            fallback = GE_TXT_DEFAULT_VALUES.get(default_key, "")
            cleaned = (value or "").strip()
            control.value = cleaned if cleaned in mapping.values() else fallback
        elif key == "RD_DEFAULT_DESENVOLVEDOR":
            cleaned = (value or "").strip()
            control.value = cleaned if cleaned in USER_OPTIONS.values() else None
        elif key == "RD_MIN_TASK_HOURS":
            control.value = value if value else GE_TXT_DEFAULT_VALUES.get("RD_MIN_TASK_HOURS", "8")
        else:
            control.value = value or ""

    def load_fields():
        values = load_ge_txt_values()
        for key in GE_TXT_DEFAULTS:
            _set_field_value(key, values.get(key, ""))

        overridden = keys_overridden_by_env()
        if overridden:
            lbl_env_warning.value = (
                "Atenção: o arquivo .env do projeto tem valor(es) para: "
                + ", ".join(overridden)
                + ". Esses valores têm prioridade sobre taskManager/ge.txt."
            )
            lbl_env_warning.visible = True
        else:
            lbl_env_warning.value = ""
            lbl_env_warning.visible = False

        lbl_path.value = str(ge_txt_path())

    def handle_save(e):
        values = {key: _field_value(key) for key in GE_TXT_DEFAULTS}
        if not values.get("THREADS"):
            values["THREADS"] = GE_TXT_DEFAULT_VALUES.get("THREADS", "1")
        for key, (mapping, default_key) in _SSP_DROPDOWN_KEYS.items():
            if values.get(key) not in mapping.values():
                values[key] = GE_TXT_DEFAULT_VALUES.get(default_key, "")
        if values.get("RD_DEFAULT_DESENVOLVEDOR") not in USER_OPTIONS.values():
            values["RD_DEFAULT_DESENVOLVEDOR"] = ""
        if not values.get("RD_MIN_TASK_HOURS"):
            values["RD_MIN_TASK_HOURS"] = GE_TXT_DEFAULT_VALUES.get("RD_MIN_TASK_HOURS", "8")
        else:
            try:
                hours = float(values["RD_MIN_TASK_HOURS"])
                if hours <= 0:
                    values["RD_MIN_TASK_HOURS"] = GE_TXT_DEFAULT_VALUES.get("RD_MIN_TASK_HOURS", "8")
            except ValueError:
                values["RD_MIN_TASK_HOURS"] = GE_TXT_DEFAULT_VALUES.get("RD_MIN_TASK_HOURS", "8")
        try:
            path = save_ge_txt(values)
            load_fields()
            _show_status(f"Configuração salva em {path}", "green")
        except OSError as ex:
            _show_status(f"Falha ao salvar: {ex}", "red")

    def sync_ui():
        if app_state.get("session"):
            load_fields()
            lbl_status.visible = False

    sync_callbacks.append(sync_ui)
    btn_save.on_click = handle_save

    def _section(title: str, controls: list) -> ft.Column:
        return ft.Column(
            [
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
                *controls,
            ],
            spacing=8,
            tight=True,
        )

    config_view = ft.Column(
        [
            ft.Text("Configurações", size=24, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Edite o arquivo ge.txt em ~/taskManager. Alterações passam a valer após Salvar "
                "(sem reiniciar o app).",
                size=13,
            ),
            ft.Row(
                [
                    ft.Text("Arquivo:", weight=ft.FontWeight.BOLD),
                    lbl_path,
                ],
                wrap=True,
            ),
            lbl_env_warning,
            ft.Divider(),
            _section(
                "Tokens e senhas",
                [
                    fields["GITLAB_TOKEN"],
                    fields["GITHUB_TOKEN"],
                    fields["CLAUDE_KEY"],
                    fields["RD_PASS"],
                ],
            ),
            ft.Divider(),
            _section(
                "Git / Diffs",
                [
                    fields["GITLAB_DEFAULT_AUTHOR"],
                    fields["GITHUB_DEFAULT_AUTHOR"],
                    fields["DIFF_DEFAULT_PLATFORM"],
                ],
            ),
            ft.Divider(),
            _section(
                "Redmine",
                [
                    fields["RD_HOST"],
                    fields["RD_USER"],
                    fields["STARTING_DATE"],
                    fields["STARTING_VERSAO"],
                ],
            ),
            ft.Divider(),
            _section(
                "SSP (tarefas Redmine)",
                [
                    fields["RD_DEFAULT_SISTEMA"],
                    fields["RD_DEFAULT_ORGAO"],
                    fields["RD_DEFAULT_ATRIBUICAO"],
                    fields["RD_DEFAULT_PROJETO"],
                    fields["RD_DEFAULT_DESENVOLVEDOR"],
                    fields["RD_MIN_TASK_HOURS"],
                ],
            ),
            ft.Divider(),
            _section("Runtime", [fields["THREADS"]]),
            ft.Row([btn_save], alignment=ft.MainAxisAlignment.START),
            lbl_status,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    return ft.Tab(
        text="Configurações",
        icon=ft.Icons.SETTINGS,
        content=ft.Container(content=config_view, padding=20, expand=True),
    )
