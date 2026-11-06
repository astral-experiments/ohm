"""Draw the README's benchmark figures as standalone SVGs."""

from html import escape


def elapsed(seconds):
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}m {seconds:02d}s"


def bars(title, rows, *, legend, value_label, left, column=""):
    """Draw one or two bars per row on a shared linear scale."""
    width = 680
    end = 478 if column else 596
    row_height = 42 if legend else 32
    top = 34 if legend else 26
    height = top + row_height * len(rows)
    values = [value for _, series, _ in rows for value in series]
    low, high = min(0, *values), max(0, *values)
    scale = (end - left) / (high - low or 1)
    zero = left - low * scale

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">',
        f'<title id="title">{escape(title)}</title>',
        """<style>
text { font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #24292f }
.number, .key { font-size: 13px; font-variant-numeric: tabular-nums }
.key { fill: #59636e }
.stock { fill: #9aa4af }
.ohm { fill: #298365 }
.axis { stroke: #d1d9e0 }
@media (prefers-color-scheme: dark) {
  text { fill: #e6edf3 }
  .key { fill: #a4adb7 }
  .stock { fill: #788390 }
  .ohm { fill: #6dc2a1 }
  .axis { stroke: #3d444d }
}
</style>""",
    ]

    def text(x, y, label, cls="", anchor="start"):
        svg.append(f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">{escape(label)}</text>')

    def rect(x, y, w, h, cls):
        svg.append(f'<rect x="{x:.2f}" y="{y:.1f}" width="{w:.2f}" height="{h}" class="{cls}"/>')

    for i, label in enumerate(legend):
        x = left + i * 146
        rect(x, 8, 14, 7, ("stock", "ohm")[i])
        text(x + 20, 16, label, "key")
    if column:
        text(width - 3, 16, column, "key", "end")
    svg.append(f'<path d="M{zero:.2f} {top - 3}V{height - 4}" class="axis"/>')
    for i, (label, series, comparison) in enumerate(rows):
        center = top + (i + 0.5) * row_height
        text(2, center + 4, label)
        for j, value in enumerate(series):
            y = center + (j - 0.5) * 14 if len(series) == 2 else center
            tip = zero + value * scale
            color = "stock" if (len(series) == 2 and j == 0) or value < 0 else "ohm"
            rect(min(tip, zero), y - 4, abs(tip - zero), 8, color)
            text(max(tip, zero) + 6, y + 4, value_label(value), "number")
        if comparison:
            text(width - 3, center + 4, comparison, "number", "end")
    return "\n".join([*svg, "</svg>", ""])
