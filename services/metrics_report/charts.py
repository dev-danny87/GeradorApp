"""Chart images. Labels and numbers are drawn later by the PDF, not burned in here."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw


def month_bar(day: int, hours: float, days_in_month: int) -> tuple[float, float]:
    """Calendar span for one task. 8 hours reads as one day. The label stays the real hours."""
    days = max(int(days_in_month), 1)
    day_index = min(max(int(day), 1), days) - 1
    start = day_index / days
    if hours <= 0:
        return start, start
    span_days = max(hours / 8.0, 0.45)
    end = min(1.0, (day_index + span_days) / days)
    if end - start < 0.015:
        end = min(1.0, start + 0.015)
    return start, end


def magnitude_bar(hours: float, max_hours: float) -> tuple[float, float]:
    if hours <= 0 or max_hours <= 0:
        return 0.0, 0.0
    return 0.0, max(0.02, min(1.0, hours / max_hours))


def render_donut(weights: list[tuple[float, str]], size: int = 360) -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = 8
    box = (pad, pad, size - pad - 1, size - pad - 1)
    usable = [(weight, color) for weight, color in weights if weight > 0]
    total = sum(weight for weight, _color in usable)
    if total <= 0:
        draw.ellipse(box, fill=(232, 236, 230, 255))
    elif len(usable) == 1:
        draw.ellipse(box, fill=_rgb(usable[0][1]))
    else:
        start = -90.0
        gap = 2.2
        for weight, color in usable:
            extent = 360.0 * weight / total
            draw.pieslice(box, start, start + max(0.4, extent - gap), fill=_rgb(color))
            start += extent
    _punch_hole(image, size / 2, (size - 2 * pad) / 2 * 0.62)
    return _png(image)


def render_timeline(
        spans: list[tuple[float, float, str]],
        *,
        track: str,
        grid: list[float] | None = None,
        width: int = 1600,
        row_h: int = 48,
) -> bytes:
    count = max(len(spans), 1)
    height = count * row_h
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for frac in grid or []:
        x = int(round(min(max(frac, 0.0), 1.0) * (width - 1)))
        draw.line((x, 0, x, height), fill=(120, 132, 120, 70), width=1)
    for index, (start, end, color) in enumerate(spans):
        top = index * row_h
        bar_h = max(8, int(row_h * 0.46))
        y0 = top + (row_h - bar_h) / 2
        y1 = y0 + bar_h
        _round_rect(draw, (1, y0, width - 2, y1), _rgb(track), radius=6)
        if end <= start:
            continue
        x0 = int(round(start * (width - 1)))
        x1 = int(round(end * (width - 1)))
        if x1 < x0 + 4:
            x1 = min(width - 1, x0 + 4)
        _round_rect(draw, (x0, y0, x1, y1), _rgb(color), radius=6)
    return _png(image)


def render_hbars(
        values: list[float],
        colors: list[str],
        *,
        track: str,
        width: int = 800,
        row_h: int = 48,
) -> bytes:
    count = max(len(values), 1)
    height = count * row_h
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    peak = max(values) if values else 0
    for index, value in enumerate(values):
        top = index * row_h
        bar_h = max(8, int(row_h * 0.52))
        y0 = top + (row_h - bar_h) / 2
        y1 = y0 + bar_h
        _round_rect(draw, (0, y0, width - 1, y1), _rgb(track), radius=6)
        if peak <= 0 or value <= 0:
            continue
        fill = colors[index] if index < len(colors) else colors[-1]
        x1 = max(4, int(round((width - 1) * (value / peak))))
        _round_rect(draw, (0, y0, x1, y1), _rgb(fill), radius=6)
    return _png(image)


def render_vbars(
        values: list[float],
        color: str,
        *,
        width: int = 800,
        height: int = 280,
) -> bytes:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line((0, height - 2, width, height - 2), fill=(198, 206, 198, 255), width=2)
    count = max(len(values), 1)
    peak = max(values) if values else 0
    gutter = 0.012
    usable = 1 - gutter * (count + 1)
    bar_w = usable / count
    for index, value in enumerate(values):
        if peak <= 0 or value <= 0:
            continue
        x_frac = gutter + index * (bar_w + gutter)
        x0 = int(round(x_frac * width))
        x1 = int(round((x_frac + bar_w) * width))
        bar_h = max(2, int(round((height - 8) * (value / peak))))
        y0 = height - 3 - bar_h
        _round_rect(draw, (x0, y0, max(x0 + 2, x1), height - 3), _rgb(color), radius=4)
    return _png(image)


def vbar_centers(count: int) -> list[float]:
    """Horizontal center of each bar, as a fraction of the image width."""
    count = max(count, 1)
    gutter = 0.012
    usable = 1 - gutter * (count + 1)
    bar_w = usable / count
    return [gutter + index * (bar_w + gutter) + bar_w / 2 for index in range(count)]


def _punch_hole(image: Image.Image, center: float, radius: float) -> None:
    alpha = image.getchannel("A")
    mask = ImageDraw.Draw(alpha)
    mask.ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        fill=0,
    )
    image.putalpha(alpha)


def _round_rect(draw: ImageDraw.ImageDraw, box, color, radius: float = 5) -> None:
    x0, y0, x1, y1 = box
    if x1 - x0 < 2 or y1 - y0 < 2:
        draw.rectangle((x0, y0, x1, y1), fill=color)
        return
    limit = min((x1 - x0) / 2, (y1 - y0) / 2, radius)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=limit, fill=color)


def _rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
