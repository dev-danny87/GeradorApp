from services.iphan._project_stub import (
    stub_generate_evidences,
    stub_get_controls,
    stub_load_options,
    stub_set_app_run,
    stub_validate_selection,
)

PROJECT_KEY = "saip"
PROJECT_LABEL = "SAIP"


def load_options(session, app_state):
    stub_load_options(session, app_state, PROJECT_KEY)


def get_controls(app_state):
    return stub_get_controls(app_state)


def validate_selection(app_state):
    return stub_validate_selection(app_state)


def generate_evidences(session, app_state):
    stub_generate_evidences(session, app_state, PROJECT_LABEL)


def set_app_run(value: bool) -> None:
    stub_set_app_run(value)
