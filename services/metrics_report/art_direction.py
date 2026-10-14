"""One Claude call for palette, headlines, and wordless SVG decorations.

Numbers on the PDF are never taken from this response. A failed call returns
the fixed sage-and-gold palette and no headlines.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from services.ai_api_request import (
    ANTHROPIC_VERSION,
    CLAUDE_BASE_URL,
    _extract_json_from_response,
    _extract_text_from_message,
    _get_headers,
)
from services.metrics_report.aggregate import ReportBundle

ART_MODEL = "claude-sonnet-5"

FALLBACK_PALETTE = {
    "page": "#E7EFE4",
    "card": "#FFFFFF",
    "ink": "#1C241C",
    "muted": "#5E6A5E",
    "gold": "#E8C56B",
    "green": "#6AAA6A",
    "amber": "#E6C36A",
    "track": "#F4F7F2",
    "line": "#D5DDD4",
    "donut": ["#E05A4F", "#E6C36A", "#6AAA6A", "#8FA36A", "#7AA0B8", "#C4B07A"],
}

_PALETTE_KEYS = ("page", "card", "ink", "muted", "gold", "green", "amber", "track", "line")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_MONTH_KEY_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
_BAD_SVG_RE = re.compile(
    r"<\s*(?:text|script|image|foreignObject)\b|href\s*=|xlink:|javascript:|https?:|url\s*\(",
    re.IGNORECASE,
)
_SVG_NS_RE = re.compile(
    r"""xmlns(?::[A-Za-z0-9]+)?\s*=\s*["']http://www\.w3\.org/2000/svg["']""",
    re.IGNORECASE,
)
_ICON_KEYS = ("commits", "tarefas", "sem_evidencia")

_SYSTEM_PROMPT = """You are a visual designer for an executive PDF metrics report.
Return ONLY a JSON object. No markdown fences and no commentary.
Another program draws every number, date, label, and chart. You only choose color and decoration.
Headlines are exactly one Portuguese sentence each. Every digit you write must already appear in the input JSON. Do not invent totals.
SVG must be wordless geometry: no text, no letters, no digits, no images, no scripts, no links, no gradients that use url().
Keep each SVG under 1500 characters, with xmlns and a viewBox.
header_svg viewBox "0 0 320 48". corner_svg and each icon viewBox "0 0 64 64".
Prefer a calm CTO palette: warm paper, deep ink, one gold accent, green and amber series.
"""


@dataclass(frozen=True)
class ArtDirection:
    palette: dict
    year_headlines: dict[str, str]
    month_headlines: dict[str, str]
    header_svg: str | None
    corner_svg: str | None
    icon_svgs: dict[str, str]
    used_fallback: bool

    def headline_for_year(self, year: int) -> str:
        return self.year_headlines.get(str(year)) or self.year_headlines.get("*") or ""

    def headline_for_month(self, key: str) -> str:
        return self.month_headlines.get(key) or ""


def fallback_direction() -> ArtDirection:
    return ArtDirection(
        palette=_copy_palette(FALLBACK_PALETTE),
        year_headlines={},
        month_headlines={},
        header_svg=None,
        corner_svg=None,
        icon_svgs={},
        used_fallback=True,
    )


def compact_totals(bundle: ReportBundle, project_name: str) -> dict:
    return {
        "project": project_name,
        "years": [
            {
                "year": year.year,
                "hours": year.total_hours,
                "tasks": year.task_count,
                "commits": year.commit_count,
                "percent_with_commits": year.percent_complete,
                "categories": [
                    {"name": name, "hours": hours}
                    for name, hours in year.hours_by_category
                ],
                "months": [
                    {
                        "key": month.key,
                        "hours": month.total_hours,
                        "tasks": month.task_count,
                        "commits": month.commit_count,
                        "percent_with_commits": month.percent_complete,
                        "tasks_without_commits": month.tasks_without_commits,
                    }
                    for month in year.months
                ],
            }
            for year in bundle.years
        ],
    }


def collect_allowed_numbers(payload: dict) -> set[str]:
    found: set[str] = set()

    def add(token: str) -> None:
        text = token.strip()
        if not text:
            return
        found.add(text)
        if "." in text:
            found.add(text.replace(".", ","))
        if "," in text:
            found.add(text.replace(",", "."))

    def walk(node) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            add(str(node))
            return
        if isinstance(node, float):
            add(f"{node:g}")
            if node == int(node):
                add(str(int(node)))
            else:
                add(f"{node:.2f}".rstrip("0").rstrip("."))
            return
        if isinstance(node, str):
            for token in _NUM_RE.findall(node):
                add(token)
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(payload)
    return found


def headline_ok(text: str, allowed: set[str]) -> bool:
    collapsed = " ".join(str(text).split())
    if not collapsed or len(collapsed) > 180:
        return False
    if len(re.findall(r"[.!?]", collapsed)) > 1:
        return False
    for token in _NUM_RE.findall(collapsed):
        variants = {token, token.replace(",", "."), token.replace(".", ",")}
        if not variants & allowed:
            return False
    return True


def clean_svg(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) < 20 or len(text) > 20000:
        return None
    lowered = text.lower()
    if lowered.count("<svg") != 1 or "</svg>" not in lowered:
        return None
    if "<!doctype" in lowered or "<!entity" in lowered:
        return None
    if _BAD_SVG_RE.search(_SVG_NS_RE.sub("", text)):
        return None
    return text


def sanitize_art_direction(raw: dict, totals: dict) -> ArtDirection:
    if not isinstance(raw, dict):
        return fallback_direction()

    allowed = collect_allowed_numbers(totals)
    month_keys = _month_keys(totals)
    year_keys = _year_keys(totals)
    palette = _palette_or_fallback(raw.get("palette"))

    year_headlines: dict[str, str] = {}
    incoming_years = raw.get("year_headlines")
    if isinstance(incoming_years, dict):
        for key, value in incoming_years.items():
            year_key = str(key).strip()
            if year_key not in year_keys or not isinstance(value, str):
                continue
            if headline_ok(value, allowed):
                year_headlines[year_key] = " ".join(value.split())

    single = raw.get("year_headline")
    if isinstance(single, str) and headline_ok(single, allowed):
        year_headlines.setdefault("*", " ".join(single.split()))

    month_headlines: dict[str, str] = {}
    incoming_months = raw.get("month_headlines")
    if isinstance(incoming_months, dict):
        for key, value in incoming_months.items():
            month_key = _normalize_month_key(str(key))
            if month_key is None or month_key not in month_keys or not isinstance(value, str):
                continue
            if headline_ok(value, allowed):
                month_headlines[month_key] = " ".join(value.split())

    icons: dict[str, str] = {}
    incoming_icons = raw.get("icon_svgs")
    if isinstance(incoming_icons, dict):
        for key in _ICON_KEYS:
            cleaned = clean_svg(incoming_icons.get(key))
            if cleaned:
                icons[key] = cleaned

    return ArtDirection(
        palette=palette,
        year_headlines=year_headlines,
        month_headlines=month_headlines,
        header_svg=clean_svg(raw.get("header_svg")),
        corner_svg=clean_svg(raw.get("corner_svg")),
        icon_svgs=icons,
        used_fallback=False,
    )


def fetch_art_direction(bundle: ReportBundle, project_name: str) -> ArtDirection:
    totals = compact_totals(bundle, project_name)
    try:
        raw = _call_claude(totals)
        return sanitize_art_direction(raw, totals)
    except Exception:
        return fallback_direction()


def _call_claude(totals: dict) -> dict:
    user_content = (
        "Design the report from these totals. Return JSON with keys "
        "palette, year_headline, month_headlines, header_svg, corner_svg, icon_svgs.\n"
        "palette keys: page, card, ink, muted, gold, green, amber, track, line, "
        "and donut as six hex colors.\n"
        "month_headlines keys are the month key values from the input.\n"
        f"{json.dumps(totals, ensure_ascii=False)}"
    )
    response = requests.post(
        f"{CLAUDE_BASE_URL}/messages",
        headers={
            **_get_headers(),
            "anthropic-version": ANTHROPIC_VERSION,
        },
        json={
            "model": ART_MODEL,
            "max_tokens": 8192,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=90,
    )
    response.raise_for_status()
    return _extract_json_from_response(_extract_text_from_message(response.json()))


def _copy_palette(source: dict) -> dict:
    copied = dict(source)
    copied["donut"] = list(source["donut"])
    return copied


def _valid_hex(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _HEX_RE.fullmatch(text):
        return text.upper()
    return None


def _palette_or_fallback(raw) -> dict:
    if not isinstance(raw, dict):
        return _copy_palette(FALLBACK_PALETTE)
    palette = {}
    for key in _PALETTE_KEYS:
        color = _valid_hex(raw.get(key))
        if color is None:
            return _copy_palette(FALLBACK_PALETTE)
        palette[key] = color
    donut = raw.get("donut")
    if not isinstance(donut, list) or len(donut) < 6:
        return _copy_palette(FALLBACK_PALETTE)
    colors = []
    for item in donut[:6]:
        color = _valid_hex(item)
        if color is None:
            return _copy_palette(FALLBACK_PALETTE)
        colors.append(color)
    palette["donut"] = colors
    return palette


def _normalize_month_key(raw: str) -> str | None:
    match = _MONTH_KEY_RE.fullmatch(raw.strip())
    if not match:
        return None
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{int(match.group(1)):04d}-{month:02d}"


def _month_keys(totals: dict) -> set[str]:
    keys: set[str] = set()
    for year in totals.get("years") or []:
        if not isinstance(year, dict):
            continue
        for month in year.get("months") or []:
            if isinstance(month, dict) and month.get("key"):
                normalized = _normalize_month_key(str(month["key"]))
                if normalized:
                    keys.add(normalized)
    return keys


def _year_keys(totals: dict) -> set[str]:
    keys: set[str] = set()
    for year in totals.get("years") or []:
        if isinstance(year, dict) and isinstance(year.get("year"), int):
            keys.add(str(year["year"]))
    return keys
