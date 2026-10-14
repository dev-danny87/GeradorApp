"""Landscape metrics PDF. Every metric is drawn here, on top of the chart images."""

from __future__ import annotations

import calendar
import os
import tempfile
from dataclasses import dataclass
from io import BytesIO

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from services.metrics_report.aggregate import (
    MonthSlice,
    ProgressCallback,
    ReportBundle,
    YearSlice,
    aggregate_tasks,
    tasks_for_timeline,
)
from services.metrics_report.art_direction import ArtDirection, fetch_art_direction
from services.metrics_report.charts import (
    magnitude_bar,
    month_bar,
    render_donut,
    render_hbars,
    render_timeline,
    render_vbars,
    vbar_centers,
)
from utils.month_selector import MONTH_NAMES
from utils.pdf_merger import merge_documents

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 22
FOOTER = "Fonte: banco de horas (leitura). Nenhuma hora foi consumida."
DEFAULT_SUBTITLE = "Leitura do banco de horas para métricas. Nenhuma hora foi consumida."
MONTH_SHORT = (
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
)

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
_FONTS_READY = False


@dataclass
class _Line:
    text: str
    font: str
    size: float
    leading: float
    color_key: str


def write_metrics_pdf(
        dest_path: str,
        tasks: list[dict],
        project_name: str,
        *,
        art: ArtDirection | None = None,
        cover_pdf: str | None = None,
        close_pdf: str | None = None,
        on_progress: ProgressCallback | None = None,
        body: str = "all",
) -> ArtDirection:
    """Write the merged report. Cover and close are optional PDFs around the body."""
    log = on_progress or (lambda _message: None)
    abs_dest = os.path.abspath(dest_path)
    log(f"Início: projeto={project_name}, {len(tasks)} tarefa(s), destino={abs_dest}")

    log("Etapa 1/4 — preparando tarefas uma a uma")
    bundle = aggregate_tasks(tasks, on_progress=log)

    log("Etapa 2/4 — direção visual")
    if art is not None:
        direction = art
        log("Visual: usando direção fornecida")
    else:
        log("Visual: consultando Claude (ou fallback)")
        direction = fetch_art_direction(bundle, project_name)
        if direction.used_fallback:
            log("Visual: palette padrão (Claude indisponível ou inválido)")
        else:
            log("Visual: Claude respondeu com palette e decorações")

    descriptor, body_path = tempfile.mkstemp(suffix=".pdf")
    os.close(descriptor)
    body_saved = False
    try:
        log("Etapa 3/4 — desenhando páginas do PDF")
        render_body_pdf(
            body_path, bundle, project_name, direction, on_progress=log, body=body,
        )
        body_saved = True

        log("Etapa 4/4 — unindo capa, corpo e encerramento")
        parts = []
        if cover_pdf:
            log(f"Capa: {cover_pdf}")
            parts.append(cover_pdf)
        parts.append(body_path)
        if close_pdf:
            log(f"Encerramento: {close_pdf}")
            parts.append(close_pdf)
        merge_documents(parts, dest_path)
        log(
            f"Concluído: {abs_dest} — "
            f"{bundle.prepared_count} incluída(s), {bundle.failed_count} falha(s)"
        )
    except Exception:
        if not body_saved and os.path.isfile(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        raise
    finally:
        try:
            os.remove(body_path)
        except OSError:
            pass
    return direction


def render_body_pdf(
        path: str,
        bundle: ReportBundle,
        project_name: str,
        art: ArtDirection,
        *,
        on_progress: ProgressCallback | None = None,
        body: str = "all",
) -> None:
    """body is 'all' (months then year), 'months', or 'year'."""
    log = on_progress or (lambda _message: None)
    ensure_fonts()
    pdf = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))
    pdf.setTitle(f"Relatório de métricas — {project_name}")
    pdf.setAuthor("GeradorApp")
    year_total = len(bundle.years)
    draw_months = body in {"all", "months"}
    draw_year = body in {"all", "year"}
    for year_index, year in enumerate(bundle.years, start=1):
        if draw_months:
            month_total = len(year.months)
            for month_index, month in enumerate(year.months, start=1):
                month_label = f"{MONTH_NAMES[month.month - 1]} {month.year}"
                log(f"Dashboard mensal {month_index}/{month_total}: {month_label}")
                _draw_dashboard(pdf, _month_spec(month, project_name, art), art)
                pdf.showPage()
                log(
                    f"Detalhamento {month_index}/{month_total}: {month_label} "
                    f"({month.task_count} tarefa(s))"
                )
                _draw_details(pdf, month, project_name, art, on_progress=log)
        if draw_year:
            log(f"Página anual {year_index}/{year_total}: {year.year}")
            _draw_dashboard(pdf, _year_spec(year, project_name, art), art)
            pdf.showPage()
    pdf.save()
    log("Corpo do PDF gravado")


def ensure_fonts() -> None:
    global FONT, FONT_BOLD, _FONTS_READY
    if _FONTS_READY:
        return
    pairs = (
        (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    )
    for regular, bold in pairs:
        if os.path.isfile(regular) and os.path.isfile(bold):
            pdfmetrics.registerFont(TTFont("ReportSans", regular))
            pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold))
            FONT = "ReportSans"
            FONT_BOLD = "ReportSans-Bold"
            break
    _FONTS_READY = True


def _year_spec(year: YearSlice, project: str, art: ArtDirection) -> dict:
    max_hours = max((year.hours_of_month(month) for month in range(1, 13)), default=0)
    spans = []
    labels = []
    for month in range(1, 13):
        hours = year.hours_of_month(month)
        start, end = magnitude_bar(hours, max_hours)
        spans.append((start, end, art.palette["green"]))
        labels.append(MONTH_NAMES[month - 1])
    axis = [(0.0, "0h")]
    if max_hours > 0:
        axis.append((1.0, f"{_fmt_hours(max_hours)}h"))
    return {
        "bookmark_key": f"year-{year.year}",
        "bookmark_title": f"Resumo anual {year.year}",
        "bookmark_level": 0,
        "title": "Painel anual do relatório de status do projeto",
        "subtitle": art.headline_for_year(year.year) or DEFAULT_SUBTITLE,
        "kpis": _kpis(project, f"31/12/{year.year}", year.percent_complete, year.commit_count),
        "timeline_title": "Linha do tempo",
        "timeline_note": "",
        "timeline_labels": labels,
        "timeline_spans": spans,
        "axis": axis,
        "grid": [0.5] if max_hours > 0 else [],
        "categories": year.hours_by_category,
        "evidence": (
            ("Com evidência", year.hours_with_commits),
            ("Sem evidência", year.hours_without_commits),
        ),
        "hours_mode": "months",
        "hours_values": [year.hours_of_month(month) for month in range(1, 13)],
        "pending": (
            ("Commits", year.commit_count),
            ("Tarefas", year.task_count),
            ("Sem evidência", year.tasks_without_commits),
        ),
        "center_category": f"{_fmt_hours(year.total_hours)}h",
        "center_evidence": f"{year.percent_complete}%",
    }


def _month_spec(month: MonthSlice, project: str, art: ArtDirection) -> dict:
    shown = tasks_for_timeline(month.tasks)
    days = calendar.monthrange(month.year, month.month)[1]
    dated = [task for task in shown if task.day_known]
    spans = []
    if shown and len(dated) == len(shown):
        for task in shown:
            start, end = month_bar(task.spent_on.day, task.hours, days)
            color = art.palette["green"] if task.commit_links else art.palette["amber"]
            spans.append((start, end, color))
        ticks = []
        seen = set()
        for day in (1, 8, 15, 22, days):
            if day in seen or day > days:
                continue
            seen.add(day)
            ticks.append(((day - 1) / days, f"{day:02d}/{month.month:02d}"))
        grid = [frac for frac, _label in ticks]
    else:
        max_hours = max((task.hours for task in shown), default=0)
        for task in shown:
            start, end = magnitude_bar(task.hours, max_hours)
            color = art.palette["green"] if task.commit_links else art.palette["amber"]
            spans.append((start, end, color))
        ticks = [(0.0, "0h")]
        if max_hours > 0:
            ticks.append((1.0, f"{_fmt_hours(max_hours)}h"))
        grid = [0.5] if max_hours > 0 else []
    note = ""
    if shown and len(dated) != len(shown):
        note = "Período mensal, sem dia de commit. "
    if len(shown) < len(month.tasks):
        note += (
            f"{len(shown)} de {len(month.tasks)} tarefas com mais horas. "
            "As demais estão no detalhamento."
        )
    last = calendar.monthrange(month.year, month.month)[1]
    return {
        "bookmark_key": f"month-{month.key}",
        "bookmark_title": f"{MONTH_NAMES[month.month - 1]} {month.year}",
        "bookmark_level": 0,
        "title": "Painel mensal do relatório de status do projeto",
        "subtitle": art.headline_for_month(month.key) or DEFAULT_SUBTITLE,
        "kpis": _kpis(
            project,
            f"{last:02d}/{month.month:02d}/{month.year}",
            month.percent_complete,
            month.commit_count,
        ),
        "timeline_title": "Linha do tempo",
        "timeline_note": note,
        "timeline_labels": [task.title for task in shown],
        "timeline_spans": spans,
        "axis": ticks,
        "grid": grid,
        "categories": month.hours_by_category,
        "evidence": (
            ("Com evidência", month.hours_with_commits),
            ("Sem evidência", month.hours_without_commits),
        ),
        "hours_mode": "split",
        "hours_values": [month.hours_with_commits, month.hours_without_commits],
        "pending": (
            ("Commits", month.commit_count),
            ("Tarefas", month.task_count),
            ("Sem evidência", month.tasks_without_commits),
        ),
        "center_category": f"{_fmt_hours(month.total_hours)}h",
        "center_evidence": f"{month.percent_complete}%",
    }


def _kpis(project: str, when: str, percent: int, commits: int) -> list[tuple[str, str]]:
    return [
        ("Projeto", project),
        ("Data", when),
        ("Status", "Registrado"),
        ("% completo", f"{percent}%"),
        ("Commits", str(commits)),
    ]


def _draw_dashboard(pdf: canvas.Canvas, spec: dict, art: ArtDirection) -> None:
    palette = art.palette
    _paint_background(pdf, palette)
    pdf.bookmarkPage(spec["bookmark_key"])
    pdf.addOutlineEntry(spec["bookmark_title"], spec["bookmark_key"], level=spec["bookmark_level"], closed=0)

    content_w = PAGE_W - 2 * MARGIN
    title_y = PAGE_H - 32
    _text(pdf, MARGIN, title_y, spec["title"], FONT_BOLD, 15, palette["ink"])
    _draw_svg(pdf, art.header_svg, PAGE_W - MARGIN - 150, title_y - 4, 146, 22)
    pdf.setFillColor(_hex(palette["gold"]))
    pdf.roundRect(MARGIN, title_y - 8, 42, 3.2, 1.5, fill=1, stroke=0)
    _text(
        pdf,
        MARGIN,
        title_y - 22,
        _fit(spec["subtitle"], FONT, 8, content_w),
        FONT,
        8,
        palette["muted"],
    )

    kpi_top = title_y - 32
    kpi_h = 36
    gap = 8
    pill_w = (content_w - gap * 4) / 5
    for index, (label, value) in enumerate(spec["kpis"]):
        _draw_pill(
            pdf,
            MARGIN + index * (pill_w + gap),
            kpi_top - kpi_h,
            pill_w,
            kpi_h,
            label,
            value,
            palette,
        )

    charts_bottom = 36
    charts_h = 186
    charts_top = charts_bottom + charts_h
    timeline_bottom = charts_top + 8
    timeline_top = kpi_top - kpi_h - 8
    _draw_timeline_card(pdf, spec, art, MARGIN, timeline_bottom, content_w, timeline_top - timeline_bottom)

    card_gap = 8
    card_w = (content_w - 2 * card_gap) / 3
    _draw_donut_card(
        pdf,
        "Categoria %",
        list(spec["categories"]),
        spec["center_category"],
        palette["donut"],
        palette,
        MARGIN,
        charts_bottom,
        card_w,
        charts_h,
    )
    _draw_donut_card(
        pdf,
        "Evidência %",
        list(spec["evidence"]),
        spec["center_evidence"],
        [palette["green"], palette["amber"]],
        palette,
        MARGIN + card_w + card_gap,
        charts_bottom,
        card_w,
        charts_h,
    )
    _draw_hours_card(
        pdf,
        spec,
        art,
        MARGIN + 2 * (card_w + card_gap),
        charts_bottom,
        card_w,
        charts_h,
    )
    _draw_footer(pdf, art)


def _draw_timeline_card(pdf, spec, art, x, y, width, height) -> None:
    palette = art.palette
    _card(pdf, x, y, width, height, palette)
    _text(pdf, x + 12, y + height - 18, spec["timeline_title"], FONT_BOLD, 11, palette["ink"])
    if spec["timeline_note"]:
        _text(
            pdf,
            x + 130,
            y + height - 17,
            _fit(spec["timeline_note"], FONT, 7.5, width - 150),
            FONT,
            7.5,
            palette["muted"],
        )

    labels = spec["timeline_labels"]
    spans = spec["timeline_spans"]
    count = max(len(labels), 1)
    axis_top = y + height - 28
    image_bottom = y + 12
    area_h = max(20, axis_top - 14 - image_bottom)
    row_pt = min(24, area_h / count)
    display_h = row_pt * count
    label_w = 118
    image_x = x + 12 + label_w
    image_w = width - label_w - 24
    image_top = axis_top - 12
    image_y = image_top - display_h

    for frac, label in spec["axis"]:
        _axis_label(pdf, image_x, image_w, image_top + 2, frac, label, palette["muted"])

    png = render_timeline(spans, track=palette["track"], grid=spec["grid"])
    _draw_png(pdf, png, image_x, image_y, image_w, display_h)
    for index, label in enumerate(labels):
        cy = image_top - (index + 0.5) * row_pt
        _text(
            pdf,
            x + 10,
            cy - 3,
            _fit(label, FONT, 7.5, label_w - 6),
            FONT,
            7.5,
            palette["ink"],
        )


def _draw_donut_card(pdf, title, slices, center, colors, palette, x, y, width, height) -> None:
    _card(pdf, x, y, width, height, palette)
    _text(pdf, x + 12, y + height - 18, title, FONT_BOLD, 11, palette["ink"])
    usable = [(name, value) for name, value in slices if value > 0]
    if not usable:
        _text(pdf, x + 12, y + height / 2, "Sem horas", FONT, 9, palette["muted"])
        return

    size = 112
    image_x = x + 12
    image_y = y + (height - 28 - size) / 2
    weights = []
    for index, (_name, value) in enumerate(usable):
        weights.append((value, colors[index % len(colors)]))
    _draw_png(pdf, render_donut(weights), image_x, image_y, size, size)
    _text(pdf, image_x + size / 2 - _width(center, FONT_BOLD, 9) / 2, image_y + size / 2 - 4, center, FONT_BOLD, 9, palette["ink"])

    total = sum(value for _name, value in usable) or 1
    legend_x = image_x + size + 8
    legend_w = x + width - 12 - legend_x
    row_h = min(16, (height - 40) / max(len(usable), 1))
    legend_top = y + height - 36
    for index, (name, value) in enumerate(usable):
        row_y = legend_top - index * row_h
        pdf.setFillColor(_hex(colors[index % len(colors)]))
        pdf.roundRect(legend_x, row_y - 2, 8, 8, 2, fill=1, stroke=0)
        percent = int(round(100.0 * value / total))
        label = f"{name}  {percent}%  {_fmt_hours(value)}h"
        _text(pdf, legend_x + 12, row_y - 1, _fit(label, FONT, 7.5, legend_w - 12), FONT, 7.5, palette["ink"])


def _draw_hours_card(pdf, spec, art, x, y, width, height) -> None:
    palette = art.palette
    _card(pdf, x, y, width, height, palette)
    _text(pdf, x + 12, y + height - 18, "Horas", FONT_BOLD, 11, palette["ink"])
    chart_y = y + height - 78
    if spec["hours_mode"] == "months":
        _draw_month_bars(pdf, spec["hours_values"], palette, x + 12, chart_y, width - 24, 54)
    else:
        _draw_labeled_hbars(
            pdf,
            [("Com evidência", spec["hours_values"][0], palette["green"]),
             ("Sem evidência", spec["hours_values"][1], palette["amber"])],
            palette,
            x + 12,
            chart_y,
            width - 24,
            54,
            hours=True,
        )
    _text(pdf, x + 12, y + 80, "Pendências", FONT_BOLD, 11, palette["ink"])
    pending_colors = {
        "Commits": palette["gold"],
        "Tarefas": palette["green"],
        "Sem evidência": palette["amber"],
    }
    icons = {
        "Commits": "commits",
        "Tarefas": "tarefas",
        "Sem evidência": "sem_evidencia",
    }
    rows = [
        (label, float(value), pending_colors[label], art.icon_svgs.get(icons[label]))
        for label, value in spec["pending"]
    ]
    _draw_labeled_hbars(pdf, rows, palette, x + 12, y + 10, width - 24, 64, hours=False)


def _draw_month_bars(pdf, values, palette, x, y, width, height) -> None:
    png = render_vbars(values, palette["green"], width=900, height=320)
    label_h = 12
    _draw_png(pdf, png, x, y + label_h, width, height - label_h)
    for center, label in zip(vbar_centers(len(values)), MONTH_SHORT):
        _text(
            pdf,
            x + center * width - _width(label, FONT, 6) / 2,
            y + 1,
            label,
            FONT,
            6,
            palette["muted"],
        )


def _draw_labeled_hbars(pdf, rows, palette, x, y, width, height, *, hours: bool) -> None:
    count = max(len(rows), 1)
    label_w = 78
    value_w = 36
    image_w = max(20, width - label_w - value_w)
    values = [item[1] for item in rows]
    colors = [item[2] for item in rows]
    png = render_hbars(values, colors, track=palette["track"], width=700, row_h=48)
    image_x = x + label_w
    _draw_png(pdf, png, image_x, y, image_w, height)
    row_h = height / count
    for index, item in enumerate(rows):
        label = item[0]
        value = item[1]
        icon = item[3] if len(item) > 3 else None
        cy = y + height - (index + 0.5) * row_h
        text_x = x
        if icon:
            _draw_svg(pdf, icon, x, cy - 5, 11, 11)
            text_x = x + 13
        _text(pdf, text_x, cy - 3, _fit(label, FONT, 7, label_w - (13 if icon else 0)), FONT, 7, palette["ink"])
        shown = f"{_fmt_hours(value)}h" if hours else _fmt_hours(value)
        _text(
            pdf,
            image_x + image_w + 4,
            cy - 3,
            _fit(shown, FONT, 7, value_w - 2),
            FONT,
            7,
            palette["muted"],
        )


def _draw_details(
        pdf: canvas.Canvas,
        month: MonthSlice,
        project: str,
        art: ArtDirection,
        *,
        on_progress: ProgressCallback | None = None,
) -> None:
    if not month.tasks:
        return
    log = on_progress or (lambda _message: None)
    palette = art.palette
    content_w = PAGE_W - 2 * MARGIN
    inner_w = content_w - 28
    opened = False
    cursor = 0.0
    task_total = len(month.tasks)

    def open_page() -> float:
        nonlocal opened
        if opened:
            pdf.showPage()
        _paint_background(pdf, palette)
        _text(pdf, PAGE_W - MARGIN, PAGE_H - 28, project, FONT, 8, palette["muted"], align="right")
        _text(
            pdf,
            MARGIN,
            PAGE_H - 36,
            f"{MONTH_NAMES[month.month - 1]} {month.year}",
            FONT_BOLD,
            14,
            palette["ink"],
        )
        _text(pdf, MARGIN, PAGE_H - 52, "Detalhamento das tarefas", FONT, 9, palette["muted"])
        _draw_footer(pdf, art)
        opened = True
        return PAGE_H - 68

    for task_index, task in enumerate(month.tasks, start=1):
        try:
            log(f"Detalhe {task_index}/{task_total} — {task.title}")
            lines = _task_lines(task, inner_w)
            index = 0
            first = True
            while index < len(lines):
                if not opened or cursor < 56:
                    cursor = open_page()
                room = cursor - 40
                continuation = 0 if first else 12
                taken = []
                used = 16 + continuation
                while index < len(lines):
                    line = lines[index]
                    if taken and used + line.leading > room:
                        break
                    if not taken and line.leading + used > room:
                        break
                    taken.append(line)
                    used += line.leading
                    index += 1
                if not taken:
                    if room > 80:
                        taken = [lines[index]]
                        used = 16 + continuation + taken[0].leading
                        index += 1
                    else:
                        cursor = open_page()
                        continue
                top = cursor
                bottom = cursor - used
                _card(pdf, MARGIN, bottom, content_w, used, palette)
                pdf.setFillColor(_hex(palette["green"] if task.commit_links else palette["amber"]))
                pdf.rect(MARGIN, bottom, 3.5, used, fill=1, stroke=0)
                text_y = top - 14
                if not first:
                    _text(pdf, MARGIN + 14, text_y, "Continuação", FONT, 8, palette["muted"])
                    text_y -= 12
                for line in taken:
                    _text(pdf, MARGIN + 14, text_y, line.text, line.font, line.size, palette[line.color_key])
                    text_y -= line.leading
                cursor = bottom - 8
                first = False
        except Exception as err:
            log(f"Erro no detalhe {task_index}/{task_total} — {task.title}: {err}")
            cursor = 0.0
            continue
    if opened:
        pdf.showPage()


def _when_label(task) -> str:
    if getattr(task, "day_known", True):
        return task.spent_on.strftime("%d/%m/%Y")
    return f"{MONTH_NAMES[task.spent_on.month - 1]} {task.spent_on.year}"


def _task_lines(task, width: float) -> list[_Line]:
    lines = [
        *_wrap(task.title, FONT_BOLD, 11, 14, width, "ink"),
        _Line(
            _fit(
                f"{_when_label(task)}   ·   {_fmt_hours(task.hours)}h"
                f"   ·   {task.category}   ·   {len(task.commit_links)} commits",
                FONT,
                8,
                width,
            ),
            FONT,
            8,
            12,
            "muted",
        ),
        _Line("", FONT, 8, 6, "muted"),
    ]
    for kind, text in _note_blocks(task.notes):
        if kind == "gap":
            lines.append(_Line("", FONT, 8, 6, "muted"))
        elif kind == "h":
            lines.extend(_wrap(text, FONT_BOLD, 9, 13, width, "ink"))
        else:
            lines.extend(_wrap(text, FONT, 8, 11, width, "muted"))
    return lines


def _note_blocks(notes: str) -> list[tuple[str, str]]:
    blocks = []
    for raw in (notes or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            blocks.append(("gap", ""))
        elif stripped.startswith("#"):
            blocks.append(("h", stripped.lstrip("#").strip()))
        else:
            blocks.append(("p", stripped))
    return blocks


def _wrap(text: str, font: str, size: float, leading: float, width: float, color_key: str) -> list[_Line]:
    words = []
    for piece in str(text).split(" "):
        if not piece:
            continue
        if _width(piece, font, size) <= width:
            words.append(piece)
            continue
        chunk = ""
        for char in piece:
            trial = chunk + char
            if chunk and _width(trial, font, size) > width:
                words.append(chunk)
                chunk = char
            else:
                chunk = trial
        if chunk:
            words.append(chunk)
    if not words:
        return [_Line("", font, size, leading, color_key)]
    lines = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if current and _width(trial, font, size) > width:
            lines.append(_Line(current, font, size, leading, color_key))
            current = word
        else:
            current = trial
    if current:
        lines.append(_Line(current, font, size, leading, color_key))
    return lines


def _draw_pill(pdf, x, y, width, height, label, value, palette) -> None:
    pdf.setFillColor(_hex(palette["card"]))
    pdf.setStrokeColor(_hex(palette["line"]))
    pdf.setLineWidth(0.6)
    pdf.roundRect(x, y, width, height, 6, fill=1, stroke=1)
    value_w = min(width * 0.48, max(36, _width(value, FONT_BOLD, 9) + 14))
    pdf.setFillColor(_hex(palette["gold"]))
    pdf.roundRect(x + width - value_w - 4, y + 5, value_w, height - 10, 4, fill=1, stroke=0)
    _text(pdf, x + 8, y + 14, _fit(label, FONT, 7, width - value_w - 16), FONT, 7, palette["muted"])
    value_text = _fit(value, FONT_BOLD, 8.5, value_w - 8)
    value_x = x + width - value_w - 4 + (value_w - _width(value_text, FONT_BOLD, 8.5)) / 2
    _text(pdf, value_x, y + 14, value_text, FONT_BOLD, 8.5, palette["ink"])


def _card(pdf, x, y, width, height, palette) -> None:
    pdf.setFillColor(_hex(palette["card"]))
    pdf.setStrokeColor(_hex(palette["line"]))
    pdf.setLineWidth(0.7)
    pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)


def _paint_background(pdf, palette) -> None:
    pdf.setFillColor(_hex(palette["page"]))
    pdf.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)


def _draw_footer(pdf, art: ArtDirection) -> None:
    footer_x = MARGIN
    if art.corner_svg:
        _draw_svg(pdf, art.corner_svg, MARGIN, 24, 16, 16)
        footer_x = MARGIN + 20
    _text(pdf, footer_x, 14, FOOTER, FONT, 7.5, art.palette["muted"])
    page = str(pdf.getPageNumber())
    _text(pdf, PAGE_W - MARGIN, 14, page, FONT, 8, art.palette["muted"], align="right")


def _axis_label(pdf, x, width, y, frac: float, label: str, color: str) -> None:
    if frac <= 0.02:
        _text(pdf, x, y, label, FONT, 6.5, color)
    elif frac >= 0.98:
        _text(pdf, x + width, y, label, FONT, 6.5, color, align="right")
    else:
        _text(pdf, x + frac * width, y, label, FONT, 6.5, color, align="center")


def _draw_png(pdf, payload: bytes, x, y, width, height) -> None:
    pdf.drawImage(
        ImageReader(BytesIO(payload)),
        x,
        y,
        width=width,
        height=height,
        mask="auto",
        preserveAspectRatio=False,
    )


def _draw_svg(pdf, svg: str | None, x, y, max_w, max_h) -> None:
    if not svg:
        return
    path = None
    try:
        from reportlab.graphics import renderPDF
        from svglib.svglib import svg2rlg

        descriptor, path = tempfile.mkstemp(suffix=".svg")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(svg)
        drawing = svg2rlg(path)
        if drawing is None or not drawing.width or not drawing.height:
            return
        scale = min(max_w / float(drawing.width), max_h / float(drawing.height))
        if scale <= 0:
            return
        drawing.width *= scale
        drawing.height *= scale
        drawing.scale(scale, scale)
        renderPDF.draw(drawing, pdf, x, y)
    except Exception:
        return
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


def _text(pdf, x, y, text, font, size, color, *, align: str = "left") -> None:
    pdf.setFillColor(_hex(color))
    pdf.setFont(font, size)
    if align == "right":
        pdf.drawRightString(x, y, text)
    elif align == "center":
        pdf.drawCentredString(x, y, text)
    else:
        pdf.drawString(x, y, text)


def _fit(text: str, font: str, size: float, max_width: float) -> str:
    value = " ".join(str(text or "").split())
    if _width(value, font, size) <= max_width:
        return value
    ellipsis = "..."
    while value and _width(value + ellipsis, font, size) > max_width:
        value = value[:-1]
    return (value.rstrip() + ellipsis) if value else ellipsis


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text or "", font, size)


def _fmt_hours(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _hex(value: str) -> Color:
    text = value.lstrip("#")
    return Color(int(text[0:2], 16) / 255, int(text[2:4], 16) / 255, int(text[4:6], 16) / 255)
