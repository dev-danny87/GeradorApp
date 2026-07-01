from typing import Any, List, Optional

from services.iphan import (
    editais_iphan,
    fiscalis,
    painel_ouvidoria,
    saip,
    sustentacao,
)

PROJECTS = {
    editais_iphan.PROJECT_KEY: editais_iphan,
    painel_ouvidoria.PROJECT_KEY: painel_ouvidoria,
    sustentacao.PROJECT_KEY: sustentacao,
    saip.PROJECT_KEY: saip,
    fiscalis.PROJECT_KEY: fiscalis,
}

DEFAULT_PROJECT_KEY = editais_iphan.PROJECT_KEY


def get_project_options() -> List[dict]:
    return [
        {"key": module.PROJECT_KEY, "label": module.PROJECT_LABEL}
        for module in PROJECTS.values()
    ]


def get_service(project_key: str) -> Optional[Any]:
    return PROJECTS.get(project_key)


def get_default_project_key() -> str:
    return DEFAULT_PROJECT_KEY
