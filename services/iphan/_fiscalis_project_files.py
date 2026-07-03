import re
from dataclasses import dataclass
from typing import List, Optional, Set

from bs4 import BeautifulSoup

from services.auth_service import IPHAN_BASE_URL
from services.iphan._common import absolute_url, http_get
from services.iphan._saip_project_files import (
    matches_pf_planilha,
    sprint_numbers_from_filename,
)

FISCALIS_FILES_URL = f"{IPHAN_BASE_URL}/projects/fiscalis/files"


@dataclass
class FiscalisFileEntry:
    filename: str
    download_url: str
    created_on: str = ""


def fetch_fiscalis_files_html(session) -> str:
    response = http_get(session, FISCALIS_FILES_URL)
    return response.text


def parse_fiscalis_files_html(html: str) -> List[FiscalisFileEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[FiscalisFileEntry] = []

    for row in soup.select("table.list.files tbody tr.file"):
        filename_cell = row.select_one("td.filename")
        if not filename_cell:
            continue

        name_link = filename_cell.find("a")
        filename = name_link.get_text(strip=True) if name_link else filename_cell.get_text(strip=True)
        if not filename:
            continue

        download_link = row.select_one("a.icon-download")
        if not download_link or not download_link.get("href"):
            continue

        created_on = ""
        created_cell = row.select_one("td.created_on")
        if created_cell:
            created_on = created_cell.get_text(" ", strip=True)

        entries.append(
            FiscalisFileEntry(
                filename=filename,
                download_url=absolute_url(download_link["href"]),
                created_on=created_on,
            )
        )

    return entries


def _sprint_overlap_score(filename: str, sprint_numbers: Set[int]) -> int:
    if not sprint_numbers:
        return 0
    file_sprints = sprint_numbers_from_filename(filename)
    return len(file_sprints & sprint_numbers)


def find_best_pf_planilha(
    entries: List[FiscalisFileEntry],
    year: int,
    month: int,
    sprint_numbers: Optional[Set[int]] = None,
) -> Optional[FiscalisFileEntry]:
    matched = [
        entry
        for entry in entries
        if matches_pf_planilha(entry.filename, year, month)
    ]
    if not matched:
        return None

    sprint_numbers = sprint_numbers or set()

    def sort_key(entry: FiscalisFileEntry) -> tuple:
        fiscalis20 = 1 if re.search(r"(?i)fiscalis\s*20", entry.filename) else 0
        overlap = _sprint_overlap_score(entry.filename, sprint_numbers)
        return (fiscalis20, overlap, entry.filename)

    matched.sort(key=sort_key, reverse=True)
    return matched[0]
