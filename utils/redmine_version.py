import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup

from utils.app_config import get_config

BASE_URL = "https://redmine.ssp.go.gov.br"
VERSIONS_URL = (
    f"{BASE_URL}/projects/item-01-inovacao/settings/versions"
    "?version_status=open&version_name="
)
_VERSION_HREF = re.compile(r"^/versions/(\d+)/?$")


def get_dynamic_version(
    base_version: Optional[str] = None,
    reference_date: Optional[datetime.datetime] = None,
) -> str:
    """Compute Redmine fixed_version_id from .env / ge.txt anchor and month offset."""
    base = base_version or get_config("STARTING_VERSAO", "489")
    starting_date_str = get_config("STARTING_DATE")
    if not starting_date_str:
        return str(base)

    start_dt = datetime.datetime.strptime(starting_date_str, "%Y-%m-%d")
    ref = reference_date or datetime.datetime.now()
    months_diff = (ref.year - start_dt.year) * 12 + (ref.month - start_dt.month)
    months_diff = max(0, months_diff)
    return str(int(base) + months_diff * 4)


def default_open_version_id(versions: list[dict]) -> Optional[str]:
    """Prefer an open version whose name contains JAVA; otherwise the first open one."""
    if not versions:
        return None
    for version in versions:
        if "java" in (version.get("name") or "").lower():
            return version["id"]
    return versions[0]["id"]


def fetch_open_versions(session) -> list[dict]:
    """
    Load open (aberto) versions from the project settings page.

    Returns [{"id": "496", "name": "Sprint Java - Julho 2026"}, ...].
    """
    if session is None:
        return []

    try:
        response = session.get(VERSIONS_URL, timeout=60)
        response.raise_for_status()
    except Exception as ex:
        print(f"[VERSÃO] Falha ao buscar versões abertas: {ex}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    versions: list[dict] = []
    seen_ids: set[str] = set()

    rows = soup.select("table.list.versions tbody tr")
    if not rows:
        rows = soup.select("table.versions tbody tr, table.list tbody tr")

    for row in rows:
        classes = " ".join(row.get("class") or []).lower()
        status_td = row.select_one("td.status")
        status_text = status_td.get_text(strip=True).lower() if status_td else ""
        is_open = "open" in classes or status_text == "aberto"
        if not is_open:
            continue

        version_id = None
        name = None
        for anchor in row.select("a[href^='/versions/']"):
            href = (anchor.get("href") or "").split("?")[0]
            match = _VERSION_HREF.match(href)
            if not match:
                continue
            version_id = match.group(1)
            name = anchor.get_text(strip=True)
            break

        if not version_id or not name or version_id in seen_ids:
            continue
        seen_ids.add(version_id)
        versions.append({"id": version_id, "name": name})

    print(f"[VERSÃO] {len(versions)} versão(ões) aberta(s) carregada(s).")
    return versions
