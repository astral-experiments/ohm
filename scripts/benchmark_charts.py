"""Draw the plots in the README from the published benchmark measurements."""

import math
from html import escape
from itertools import groupby

# The same palette is used on light and dark pages. Only stock Rust uses the gray bars.
STYLE = """<style>
.paper { fill: #25172c }
.grid { stroke: #49364e; stroke-width: 1 }
.zero { stroke: #66546d; stroke-width: 1 }
.rust { fill: #beb8c8 }
.ohm { fill: #d7fa79 }
text { fill: #faf5fb; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased }
.head, .tick, .value, .key { font-family: Menlo, Consolas, "Liberation Mono", monospace }
.head, .tick, .key { fill: #c6b8cb }
.head, .tick { font-size: 16px }
.key { font-size: 14px }
.name { font-weight: 500; font-size: 30px }
.command { font-size: 24px }
.value { font-size: 21px; font-variant-numeric: tabular-nums }
.stat { fill: #d7fa79; font-weight: 500; font-size: 29px }
.slower { fill: #faf5fb }
.compact .head, .compact .tick { font-size: 10px }
.compact .key { font-size: 11px }
.compact .name { font-size: 17px }
.compact .command, .compact .value { font-size: 13px }
.compact .stat { font-size: 16px }
</style>"""


def clock(seconds, fractional=False):
    if fractional and seconds < 60:
        tenths = round(seconds * 10)
        return f"{tenths // 600}:{(tenths % 600) / 10:04.1f}"
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def scale(maximum, *, minutes=False):
    """Choose about four labeled divisions and leave space after the longest bar."""
    unit = 60 if minutes and maximum >= 180 else 1
    target = maximum / (4 * unit)
    magnitude = 10 ** math.floor(math.log10(target))
    step = min((n * magnitude for n in (1, 2, 3, 5, 10)), key=lambda n: abs(n - target)) * unit
    end = math.ceil(4 * maximum / step) * step / 4
    return end, [i * step for i in range(1 + math.floor(end / step))]


class Figure:
    def __init__(self, title, description, compact):
        self.title = title
        self.description = description
        self.compact = compact
        self.width = 430 if compact else 1000
        self.pad = 13 if compact else 30
        self.marks = []

    def text(self, x, y, label, style, anchor="start"):
        self.marks.append(
            f'<text x="{x:.2f}" y="{y}" class="{style}" text-anchor="{anchor}">'
            f'{escape(label)}</text>'
        )

    def rect(self, x, y, width, height, style):
        self.marks.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height}" class="{style}"/>'
        )

    def axis(self, left, width, top, bottom, end, ticks, tick_label):
        for tick in ticks:
            x = left + width * tick / end
            css = "grid" if tick else "zero"
            self.marks.append(f'<path d="M{x:.2f} {top}V{bottom}" class="{css}"/>')
            self.text(x, bottom + (17 if self.compact else 28), tick_label(tick), "tick", "middle")

    def key(self, x, y):
        for name, offset in (("Rust", 0), ("Ohm", 59 if self.compact else 80)):
            self.rect(x + offset, y - 8, 13 if self.compact else 16, 7, name.lower())
            self.text(x + offset + (18 if self.compact else 22), y, name, "key")

    def bar(self, left, center, length, label, css):
        height = 8 if self.compact else 14
        self.rect(left, center - height / 2, length, height, css)
        self.text(left + length + (4 if self.compact else 9), center + (4 if self.compact else 7),
                  label, "value")

    def svg(self, height):
        variant = "compact" if self.compact else "wide"
        return "\n".join([
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{height}" '
            f'viewBox="0 0 {self.width} {height}" class="{variant}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(self.title)}</title>',
            f'<desc id="desc">{escape(self.description)}</desc>',
            STYLE, '<rect width="100%" height="100%" class="paper"/>', *self.marks, "</svg>", "",
        ])


def toolchains(title, rows, *, rust, ohm, kind, compact):
    """Plot each Rust/Ohm pair on one shared scale."""
    fig = Figure(title, f"Rust {rust} and Ohm {ohm}. All bars share a linear scale starting at zero.", compact)
    category, metric, statistic = {
        "sessions": ("SESSION", "MEAN REPLAY TIME", "SPEEDUP"),
        "commands": ("COMMAND", "TOTAL REPLAY TIME", "TIME VS. RUST"),
        "disk": ("PROJECT", "RETAINED SPACE", "SPACE SAVED"),
    }[kind]
    timed = kind != "disk"
    row_size = 47 if compact else 77
    top = 64 if compact else 61
    bottom = top + row_size * len(rows)
    if kind == "commands":
        left, end_x = (121, 278) if compact else (239, 738)
    else:
        left, end_x = (80, 311) if compact else (188, 765)
    maximum = max(max(pair) for _, pair, _ in rows)
    end, ticks = scale(maximum, minutes=timed)

    header = 43 if compact else 37
    if compact:
        fig.key(left, 19)
    else:
        fig.key(553, header)
    fig.text(fig.pad, header, category, "head")
    unit = "MIN:SEC" if timed else "GiB"
    if compact:
        metric = "TIME" if timed else "SPACE"
    fig.text(left, header, f"{metric} ({unit})", "head")
    fig.text(fig.width - fig.pad, header, statistic, "head", "end")

    def tick_label(value):
        if value == 0 or not timed:
            return f"{value:g}"
        return f"{value / 60:g}m" if value >= 60 and value % 60 == 0 else f"{value:g}s"

    fig.axis(left, end_x - left, top - 1, bottom, end, ticks, tick_label)
    for i, (name, pair, change) in enumerate(rows):
        center = top + (i + 0.5) * row_size
        name_style = "command" if kind == "commands" else "name"
        fig.text(fig.pad, center + (5 if compact else 9), name, name_style)
        for value, dy, css in zip(pair, (-1, 1), ("rust", "ohm"), strict=True):
            label = clock(value, fractional=kind == "commands") if timed else f"{value:.2f}"
            fig.bar(left, center + dy * (7 if compact else 11), (end_x - left) * value / end, label, css)
        fig.text(fig.width - fig.pad, center + (5 if compact else 9), change,
                 "stat slower" if pair[1] > pair[0] else "stat", "end")
    return fig.svg(bottom + (29 if compact else 49))


def edit_speedups(edits, *, compact):
    fig = Figure("Ohm speedup over stock Rust after one edit",
                 "Both columns show Ohm speedups over stock Rust on the same linear scale.", compact)
    lefts = (142, 280) if compact else (318, 655)
    chart_width = 83 if compact else 202
    maximum = max(max(pair) for pair in edits.values())
    end, ticks = scale(maximum)
    header, step, group_height = (26, 29, 27) if compact else (37, 49, 43)
    top = header + (16 if compact else 25)
    bottom = top + step * len(edits) + group_height * len({project for project, _ in edits})
    fig.text(fig.pad, header, "COMMAND", "head")
    for x, label in zip(lefts, ("DIRECT EDIT", "DEPENDENCY EDIT"), strict=True):
        fig.text(x, header, label, "head")
        fig.axis(x, chart_width, top, bottom, end, ticks[::2] if compact else ticks, lambda n: f"{n:g}×")

    y = top
    for project, entries in groupby(edits.items(), key=lambda item: item[0][0]):
        y += group_height
        fig.text(fig.pad, y - (6 if compact else 9), project, "name")
        for (_, command), pair in entries:
            center = y + step / 2
            fig.text(fig.pad, center + (4 if compact else 8), command, "command")
            for x, ratio in zip(lefts, pair, strict=True):
                fig.bar(x, center, chart_width * ratio / end, f"{ratio:.2f}×", "ohm")
            y += step
    return fig.svg(bottom + (29 if compact else 49))
