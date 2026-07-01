import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Set

from bs4 import BeautifulSoup

from services.auth_service import IPHAN_BASE_URL
from services.iphan._common import absolute_url, http_get
from utils.month_selector import MONTH_NAMES

SUSTENTACAO_FILES_URL = f"{IPHAN_BASE_URL}/projects/sustentacao_sistemas_diversos/files"

_PERIOD_START_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
_DATE_RE = re.compile(r"\d{2}-\d{2}-(20\d{2})")
_YEAR_4_RE = re.compile(r"(20\d{2})")
_SUFFIX_YY_RE = re.compile(r"_(\d{2})(?=\.pdf$)", re.IGNORECASE)
_DELIVERY_REPORT_RE = re.compile(
    r"(?i)(relat[oó]rio.*entrega|relatorio_sustentacao)"
)
_DETALHADO_RE = re.compile(r"(?i)detalhado")

_MONTH_PATTERNS: list[tuple[re.Pattern[str], int]] = []
for _idx, _name in enumerate(MONTH_NAMES, start=1):
    _ascii = (
        unicodedata.normalize("NFKD", _name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    _pattern = rf"(?<![A-Za-z0-9]){re.escape(_name)}(?![A-Za-z0-9])"
    if _ascii != _name:
        _pattern = rf"(?:{_pattern}|(?<![A-Za-z0-9]){re.escape(_ascii)}(?![A-Za-z0-9]))"
    _MONTH_PATTERNS.append((re.compile(_pattern, re.IGNORECASE), _idx))


@dataclass
class SustentacaoFileEntry:
    filename: str
    download_url: str
    created_on: str = ""


def fetch_sustentacao_files_html(session) -> str:
    response = http_get(session, SUSTENTACAO_FILES_URL)
    return response.text


def parse_sustentacao_files_html(html: str) -> List[SustentacaoFileEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[SustentacaoFileEntry] = []

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
            SustentacaoFileEntry(
                filename=filename,
                download_url=absolute_url(download_link["href"]),
                created_on=created_on,
            )
        )

    return entries


def month_from_filename(filename: str) -> Optional[int]:
    if not filename:
        return None

    period_match = _PERIOD_START_RE.search(filename)
    if period_match:
        return int(period_match.group(2))

    for pattern, month_num in _MONTH_PATTERNS:
        if pattern.search(filename):
            return month_num

    return None


def years_from_filename(filename: str) -> Set[int]:
    if not filename:
        return set()

    years: Set[int] = set()

    for match in _DATE_RE.finditer(filename):
        years.add(int(match.group(1)))

    for match in _YEAR_4_RE.finditer(filename):
        years.add(int(match.group(1)))

    suffix_match = _SUFFIX_YY_RE.search(filename)
    if suffix_match:
        years.add(2000 + int(suffix_match.group(1)))

    return years


def acceptable_years(selected_year: int, selected_month: int) -> Set[int]:
    years = {selected_year}
    if selected_month == 12:
        years.add(selected_year + 1)
    return years


def is_delivery_report(filename: str) -> bool:
    return bool(_DELIVERY_REPORT_RE.search(filename or ""))


def is_detalhado(filename: str) -> bool:
    return bool(_DETALHADO_RE.search(filename or ""))


def matches_delivery_report(filename: str, year: int, month: int) -> bool:
    if not is_delivery_report(filename):
        return False

    file_month = month_from_filename(filename)
    if file_month != month:
        return False

    file_years = years_from_filename(filename)
    if not file_years:
        return True

    return bool(file_years & acceptable_years(year, month))


def find_best_delivery_report(
    entries: List[SustentacaoFileEntry],
    year: int,
    month: int,
) -> Optional[SustentacaoFileEntry]:
    matched = [
        entry
        for entry in entries
        if matches_delivery_report(entry.filename, year, month)
    ]
    if not matched:
        return None

    standard = [entry for entry in matched if not is_detalhado(entry.filename)]
    pool = standard or matched
    pool.sort(key=lambda entry: entry.filename, reverse=True)
    return pool[0]
