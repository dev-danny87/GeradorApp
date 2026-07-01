import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Set

from bs4 import BeautifulSoup

from services.auth_service import IPHAN_BASE_URL
from services.iphan._common import absolute_url, http_get
from utils.month_selector import MONTH_NAMES

SAIP_FILES_URL = f"{IPHAN_BASE_URL}/projects/licenciamento-ambiental/files"

_PF_PLANILHA_RE = re.compile(r"(?i)planilha\s+contagem\s+pf")
_YEAR_4_RE = re.compile(r"(20\d{2})")
_SPRINT_NUMBERS_RE = re.compile(r"sprints?\s*(\d+)", re.IGNORECASE)

_MONTH_PATTERNS: list[tuple[re.Pattern[str], int]] = []
for _idx, _name in enumerate(MONTH_NAMES, start=1):
    _ascii = (
        unicodedata.normalize("NFKD", _name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    _pattern = (
        rf"(?<![A-Za-z0-9]){re.escape(_name)}"
        rf"(?=\s*20\d{{2}}|\s|[^A-Za-z0-9]|$)"
    )
    if _ascii != _name:
        _pattern = (
            rf"(?:{_pattern}|"
            rf"(?<![A-Za-z0-9]){re.escape(_ascii)}"
            rf"(?=\s*20\d{{2}}|\s|[^A-Za-z0-9]|$))"
        )
    _MONTH_PATTERNS.append((re.compile(_pattern, re.IGNORECASE), _idx))


@dataclass
class SaipFileEntry:
    filename: str
    download_url: str
    created_on: str = ""


def fetch_saip_files_html(session) -> str:
    response = http_get(session, SAIP_FILES_URL)
    return response.text


def parse_saip_files_html(html: str) -> List[SaipFileEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[SaipFileEntry] = []

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
            SaipFileEntry(
                filename=filename,
                download_url=absolute_url(download_link["href"]),
                created_on=created_on,
            )
        )

    return entries


def is_pf_planilha(filename: str) -> bool:
    return bool(_PF_PLANILHA_RE.search(filename or ""))


def month_from_filename(filename: str) -> Optional[int]:
    if not filename:
        return None
    for pattern, month_num in _MONTH_PATTERNS:
        if pattern.search(filename):
            return month_num
    return None


def years_from_filename(filename: str) -> Set[int]:
    if not filename:
        return set()
    return {int(match.group(1)) for match in _YEAR_4_RE.finditer(filename)}


def sprint_numbers_from_filename(filename: str) -> Set[int]:
    numbers: Set[int] = set()
    for match in _SPRINT_NUMBERS_RE.finditer(filename or ""):
        numbers.add(int(match.group(1)))
    for match in re.finditer(r"(?i)(\d+)\s*e\s*(\d+)", filename or ""):
        numbers.add(int(match.group(1)))
        numbers.add(int(match.group(2)))
    return numbers


def matches_pf_planilha(filename: str, year: int, month: int) -> bool:
    if not is_pf_planilha(filename):
        return False
    file_month = month_from_filename(filename)
    if file_month != month:
        return False
    file_years = years_from_filename(filename)
    if not file_years:
        return False
    return year in file_years


def _sprint_overlap_score(filename: str, sprint_numbers: Set[int]) -> int:
    if not sprint_numbers:
        return 0
    file_sprints = sprint_numbers_from_filename(filename)
    return len(file_sprints & sprint_numbers)


def find_best_pf_planilha(
    entries: List[SaipFileEntry],
    year: int,
    month: int,
    sprint_numbers: Optional[Set[int]] = None,
) -> Optional[SaipFileEntry]:
    matched = [
        entry
        for entry in entries
        if matches_pf_planilha(entry.filename, year, month)
    ]
    if not matched:
        return None

    sprint_numbers = sprint_numbers or set()

    def sort_key(entry: SaipFileEntry) -> tuple:
        saip20 = 1 if re.search(r"(?i)saip\s*20", entry.filename) else 0
        overlap = _sprint_overlap_score(entry.filename, sprint_numbers)
        return (saip20, overlap, entry.filename)

    matched.sort(key=sort_key, reverse=True)
    return matched[0]
