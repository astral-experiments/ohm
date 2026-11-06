"""Draw the README's benchmark figures as standalone SVGs."""

from html import escape
from itertools import groupby

WIDTH = 640
STYLE = """<style>
text { font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #26232b }
.heading { font-size: 16px; font-weight: 550 }
.label { fill: #625f67 }
.value, .change { font-size: 13px; font-variant-numeric: tabular-nums }
.change { fill: #625f67 }
.rust { fill: #b8b8bd }
.ohm { fill: #7546a8 }
@media (prefers-color-scheme: dark) {
  text { fill: #ece9ef }
  .label, .change { fill: #c2bec6 }
  .rust { fill: #88888e }
  .ohm { fill: #c49aeb }
}
</style>"""


def elapsed(seconds):
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}m {seconds:02d}s"


class Figure:
    def __init__(self, title, description):
        self.title = title
        self.description = description
        self.marks = []

    def text(self, x, y, label, style, *, anchor="start"):
        self.marks.append(
            f'<text x="{x:.1f}" y="{y}" class="{style}" text-anchor="{anchor}">'
            f'{escape(label)}</text>'
        )

    def bar(self, x, y, length, label, series):
        self.marks.append(
            f'<rect x="{x}" y="{y - 8}" width="{length:.2f}" height="8" class="{series}"/>'
        )
        self.text(x + length + 6, y, label, "value ohm" if series == "ohm" else "value")

    def svg(self, height):
        return "\n".join([
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
            f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(self.title)}</title>',
            f'<desc id="desc">{escape(self.description)}</desc>',
            STYLE, *self.marks, "</svg>", "",
        ])


def toolchains(title, rows, *, rust, ohm, value_label):
    """Plot the two toolchains for each workload on one shared linear scale."""
    fig = Figure(title, f"Rust {rust} and Ohm {ohm}. All bars share a linear scale starting at zero.")
    maximum = max(max(pair) for _, pair, _ in rows)
    for i, (workload, (stock, optimized), change) in enumerate(rows):
        x = 2 + i % 2 * 328
        y = 18 + i // 2 * 87
        fig.text(x, y, workload, "heading")
        fig.text(x + 298, y, change, "change", anchor="end")
        for dy, name, value in ((23, "Rust", stock), (43, "Ohm", optimized)):
            fig.text(x, y + dy, name, "label")
            fig.bar(x + 44, y + dy, 183 * value / maximum, value_label(value), name.lower())
    return fig.svg((len(rows) + 1) // 2 * 87 - 14)


def edit_speedups(edits):
    """Compare Ohm speedups for the two edit types on the same scale."""
    fig = Figure("Ohm speedup over stock Rust after one edit",
                 "Direct and dependency edits use the same linear scale. A speedup of 1× is parity.")
    columns = (185, 419)
    for x, label in zip(columns, ("Direct edit", "Dependency edit"), strict=True):
        fig.text(x, 18, label, "heading")
    maximum = max(max(pair) for pair in edits.values())
    y = 26
    for project, entries in groupby(edits.items(), key=lambda item: item[0][0]):
        y += 22
        fig.text(2, y, project, "heading")
        for (_, command), pair in entries:
            y += 24
            fig.text(2, y, command, "label")
            for x, ratio in zip(columns, pair, strict=True):
                fig.bar(x, y, 150 * ratio / maximum, f"{ratio:.2f}×", "ohm")
    return fig.svg(y + 9)
