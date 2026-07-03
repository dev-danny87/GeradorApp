import datetime
import os
import re
import time

from utils.month_selector import MONTH_NAMES

RELATORIOS_ROOT = "relatorios"
HOST_SSP = "ssp"
HOST_PGE = "pge"
HOST_IPHAN = "iphan"

EVIDENCIAS_DIR = "Evidências"
RELATORIO_INDIVIDUAIS_DIR = "Relatório de Atividades Individuais"
RELATORIO_PF_DIR = "Relatório de Contagem de Pontos de Função"


def safe_segment(name: str) -> str:
    if name is None:
        return "desconhecido"
    name = str(name).strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:150] if len(name) > 150 else name


def day_stamp(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    return today.strftime("%d-%m")


def run_stamp(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    return day_stamp(today) + "-" + time.strftime("%H_%M")


def month_label_from_date(d: datetime.date) -> str:
    return MONTH_NAMES[d.month - 1]


def month_token(month_label: str) -> str:
    label = (month_label or "").strip()
    if "/" in label:
        label = label.split("/", 1)[0].strip()
    token = safe_segment(label).upper().replace(" ", "_")
    return token or "MES"


def month_run_folder_name(month_label: str) -> str:
    return f"{month_token(month_label)}_{run_stamp()}"


def build_ssp_run_dir(projeto: str) -> str:
    path = os.path.join(
        ".",
        RELATORIOS_ROOT,
        HOST_SSP,
        day_stamp(),
        safe_segment(projeto),
        run_stamp(),
    )
    os.makedirs(path, exist_ok=True)
    return path


def build_pge_run_dir(month_label: str) -> str:
    path = os.path.join(".", RELATORIOS_ROOT, HOST_PGE, month_run_folder_name(month_label))
    os.makedirs(path, exist_ok=True)
    return path


def build_iphan_run_dirs(
    contract_key: str,
    month_label: str,
    *,
    include_pf_contagem: bool = True,
) -> dict[str, str]:
    base_out_dir = os.path.join(
        ".",
        RELATORIOS_ROOT,
        HOST_IPHAN,
        safe_segment(contract_key),
        month_run_folder_name(month_label),
    )
    dirs = {
        "base": base_out_dir,
        "evidencias": os.path.join(base_out_dir, EVIDENCIAS_DIR),
        "individual": os.path.join(base_out_dir, RELATORIO_INDIVIDUAIS_DIR),
    }
    if include_pf_contagem:
        dirs["pf_contagem"] = os.path.join(base_out_dir, RELATORIO_PF_DIR)
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs
