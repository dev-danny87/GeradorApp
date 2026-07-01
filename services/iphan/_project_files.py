import re
from dataclasses import dataclass
from typing import List, Optional, Set

from bs4 import BeautifulSoup

from services.auth_service import IPHAN_BASE_URL
from services.iphan._common import absolute_url, http_get

PROJECT_FILES_URL = f"{IPHAN_BASE_URL}/projects/premiacoes-iphan/files"

_SPRINT_IN_FILENAME_RE = re.compile(r"SPRINT\s+(\d+)", re.IGNORECASE)


@dataclass
class ProjectFileEntry:
    filename: str
    download_url: str
    sprint_number: int
    created_on: str = ""


def fetch_project_files_html(session) -> str:
    response = http_get(session, PROJECT_FILES_URL)
    return response.text


def sprint_number_from_filename(filename: str) -> Optional[int]:
    match = _SPRINT_IN_FILENAME_RE.search(filename or "")
    if not match:
        return None
    return int(match.group(1))


def parse_project_files_html(html: str) -> List[ProjectFileEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[ProjectFileEntry] = []

    for row in soup.select("table.list.files tbody tr.file"):
        filename_cell = row.select_one("td.filename")
        if not filename_cell:
            continue

        name_link = filename_cell.find("a")
        filename = name_link.get_text(strip=True) if name_link else filename_cell.get_text(strip=True)
        if not filename:
            continue

        sprint_number = sprint_number_from_filename(filename)
        if sprint_number is None:
            continue

        download_link = row.select_one("a.icon-download")
        if not download_link or not download_link.get("href"):
            continue

        created_on = ""
        created_cell = row.select_one("td.created_on")
        if created_cell:
            created_on = created_cell.get_text(" ", strip=True)

        entries.append(
            ProjectFileEntry(
                filename=filename,
                download_url=absolute_url(download_link["href"]),
                sprint_number=sprint_number,
                created_on=created_on,
            )
        )

    return entries


def filter_files_for_sprints(
    entries: List[ProjectFileEntry],
    sprint_numbers: Set[int],
) -> List[ProjectFileEntry]:
    return [entry for entry in entries if entry.sprint_number in sprint_numbers]
