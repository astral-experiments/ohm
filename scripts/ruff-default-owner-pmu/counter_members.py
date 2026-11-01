"""Extract the counter kit and require the four intentionally empty untraced exec tables."""
from pathlib import Path

EMPTY = {f"calibration/nested-plain-{n}/exec.tsv" for n in range(4)}
PREFIXES = ("calibration/", "counter-programs/", "attributed/A/trace/")


def bounded_files(z, target):
    seen = set()
    total = 0
    count = 0
    for name in z.namelist():
        if not name.startswith(PREFIXES) or name.endswith("/"):
            continue
        leaf = Path(name)
        if leaf.is_absolute() or ".." in leaf.parts or str(leaf) != name:
            raise ValueError(("unsafe counter member", name))
        with z.open(name) as src:
            data = src.read((4 << 20) + 1)
        if (not data) != (name in EMPTY) or len(data) > 4 << 20:
            raise ValueError(("incorrect raw counter length", name, len(data)))
        if not data:
            seen.add(name)
        count += 1
        total += len(data)
        if count > 1800 or total > 32 << 20:
            raise ValueError("counter evidence bound")
        dst = target / leaf
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("xb") as f:
            f.write(data)
    if seen != EMPTY:
        raise ValueError("missing untraced calibration exec tables")
