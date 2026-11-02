"""The workflow and local preflight use the same recursive manifest checker."""

from pathlib import Path
import hashlib
import re
import subprocess
import sys


def check(root, complete):
    assert (root / "SHA256SUMS").is_file()
    expected = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        h, name = line.split("  ", 1)
        assert (
            re.fullmatch("[0-9a-f]{64}", h)
            and not name.startswith("/")
            and ".." not in Path(name).parts
        )
        assert (
            name not in expected
            and (root / name).is_file()
            and not (root / name).is_symlink()
        )
        expected[name] = h
    if complete:
        present = {
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and p != root / "SHA256SUMS" and "__pycache__" not in p.parts
        }
        assert set(expected) == present, (root, sorted(set(expected) ^ present))
    # Preserve the native coreutils parsing/checking command and its exact failure status.
    subprocess.run(
        ["sha256sum", "--strict", "--check", "SHA256SUMS"],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return dict(
        files=len(expected),
        manifest=hashlib.sha256((root / "SHA256SUMS").read_bytes()).hexdigest(),
    )


def main():
    root = Path(__file__).resolve().parent
    print(check(root.parent / "handwritten-panel", True))
    print(check(root.parent / "uv-callables-21041", True))
    print(check(root, True))


if __name__ == "__main__":
    main()
