from typing import Any, List, Tuple

from services.iphan._common import options_cache, set_app_run, timestamp


def stub_load_options(session, app_state: dict, project_key: str) -> None:
    options_cache(app_state, project_key)["loaded"] = True


def stub_get_controls(app_state: dict) -> List[Any]:
    return []


def stub_validate_selection(app_state: dict) -> Tuple[bool, str]:
    return True, ""


def stub_generate_evidences(session, app_state: dict, project_label: str) -> None:
    set_app_run(True)
    print(f"\n[{timestamp()}] Regras ainda não configuradas para {project_label}.")


def stub_set_app_run(value: bool) -> None:
    set_app_run(value)
