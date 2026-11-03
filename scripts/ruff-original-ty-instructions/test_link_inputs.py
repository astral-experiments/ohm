"""Copy final Ruff test-link input files while the authenticated Wild exec is stopped."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys


def archive(path, storage):
    with path.open("rb", buffering=0) as source:
        before = os.fstat(source.fileno())
        assert stat.S_ISREG(before.st_mode) and 0 < before.st_size < 2 * 2**30
        key = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        header = source.read(16)
        source.seek(0)
        dest = storage / (key + ".zst")
        if not dest.exists():
            with dest.open("xb") as out:
                subprocess.run(["zstd", "-q", "-2", "-c"], stdin=source, stdout=out, check=True)
        after = os.fstat(source.fileno())
        assert (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    return dict(path=str(path), real=str(path.resolve()), dev=before.st_dev, ino=before.st_ino, bytes=before.st_size, sha256=key, header=header.hex())


def capture(directory, tid, image):
    proof = directory.parent.parent
    storage = proof / "native-operands"
    storage.mkdir(exist_ok=True)
    raw = image.read_bytes().split(b"\0")
    assert raw[-1] == b"" and raw[0] == str(tid).encode()
    process = Path("/proc") / str(tid)
    assert (process / "exe").samefile(os.fsdecode(raw[3]))
    cwd = (process / "cwd").resolve(strict=True)
    argv = list(map(os.fsdecode, raw[4:-1]))
    args, response = [], []
    for arg in argv[1:]:
        if arg.startswith("@"):
            path = cwd / arg[1:]
            response.append(path)
            args.extend(shlex.split(path.read_text()))
        else:
            args.append(arg)
    assert args.count("-o") == 1
    output = cwd / args[args.index("-o") + 1]
    if not re.fullmatch(r"ruff_linter(?:-[0-9a-f]+)?", output.name):
        return
    explicit = list(response)
    search, library_names = [], []
    item = iter(args)
    for arg in item:
        if arg == "-o":
            next(item)
        elif arg == "-L" or arg.startswith("-L"):
            search.append(cwd / (next(item) if arg == "-L" else arg[2:]))
        elif arg == "-l" or arg.startswith("-l"):
            library_names.append(next(item) if arg == "-l" else arg[2:])
        elif arg in ("-plugin", "-dynamic-linker"):
            explicit.append(cwd / next(item))
        elif arg.startswith(("--sysroot=", "--version-script=")):
            target = cwd / arg.split("=", 1)[1]
            if target.is_file():
                explicit.append(target)
        elif not arg.startswith("-"):
            path = cwd / arg
            if path.is_file():
                explicit.append(path)
            else:
                assert not path.is_absolute() or not Path(arg).suffix in (".rlib", ".a", ".o", ".so"), path
    # The -l candidates are catalogued as candidates, not claimed as selected.
    candidates = {str(p): [str(d / n) for d in search for n in ([p[1:]] if p.startswith(":") else ["lib" + p + ".so", "lib" + p + ".a"]) if (d / n).is_file()] for p in library_names}
    chosen = sorted(set(explicit), key=str)
    assert len(chosen) > 30 and any(p.suffix == ".rlib" for p in chosen) and any(p.suffix == ".o" for p in chosen)
    records = [archive(p, storage) for p in sorted(set(chosen + [Path(q) for group in candidates.values() for q in group]), key=str)]
    ledger = dict(tid=tid, raw_exec=image.name, cwd=str(cwd), output=str(output), explicit=[str(x) for x in chosen], search=list(map(str, search)), options=library_names, named_library_candidates=candidates, files=records)
    (directory / (image.stem + ".wild.json")).write_text(json.dumps(ledger, indent=1) + "\n")


if __name__ == "__main__":
    capture(Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]))
