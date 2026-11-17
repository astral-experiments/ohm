"""Check Cargo 1.100's known warnings for the frozen ty #29327 workspace."""

from collections import Counter
import hashlib
from pathlib import Path
import re
import sys


def check(text):
    lines = re.sub(r"\x1b\[[0-9;]*m", "", text).splitlines()
    entries = []
    counts = Counter()
    for index, line in enumerate(lines):
        if not line.startswith("warning: "):
            continue
        if re.fullmatch(r"warning: .+ \(manifest\) generated \d+ warnings?", line):
            continue
        if line.startswith("warning: `package.homepage` is redundant with "):
            counts["redundant_homepage"] += 1
        elif line == "warning: missing `[lints]` to inherit `[workspace.lints]`":
            counts["missing_lints_inheritance"] += 1
        else:
            raise ValueError(f"unexpected Cargo or compiler warning: {line}")
        location = next(
            (s.strip()[4:] for s in lines[index + 1 : index + 4] if s.strip().startswith("--> ")),
            "",
        )
        if not re.fullmatch(r"crates/[\w-]+/Cargo\.toml(?::\d+:\d+)?", location):
            raise ValueError(f"unexpected manifest location: {location!r}")
        entries.append(f"{line}\t{location}")
    encoded = ("\n".join(sorted(entries)) + "\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    reference = Path(__file__).with_name("cargo-1.100-manifest-warnings.txt").read_bytes()
    if encoded != reference:
        expected = Counter(reference.decode().splitlines())
        observed = Counter(entries)
        raise ValueError(f"manifest warnings differ: missing {dict(expected - observed)}, added {dict(observed - expected)}")
    return {"counts": dict(counts), "sha256": digest}


if __name__ == "__main__":
    import json

    print(json.dumps(check(Path(sys.argv[1]).read_text()), sort_keys=True))
