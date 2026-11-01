"""Check exact stored bytes, member names, and failure on incomplete native inputs."""

import gzip
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from physical import assert_empty, keep, module, stage
from reader import members


def refused(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError("accepted corrupt or stale native input")


def exercise():
    with tempfile.TemporaryDirectory(prefix="ohm-cgu-files-") as tmp:
        root = Path(tmp)
        work = root / "work"
        target = work / "target/nested/out"
        target.mkdir(parents=True)
        (work / "build").mkdir()
        store = root / "originals"
        store.mkdir()
        owner = "ruff_workspace"
        stem = owner + "-0123456789abcdef." + "a" * 25 + ".1234567.rcgu."
        object_path = target / (stem + "o")
        src = root / "native.c"
        src.write_text("int original(void) { return 29; }\n")
        subprocess.run(["cc", "-g", "-c", src, "-o", object_path], check=True)
        # This is an ar/storage fixture. Only signed rustc supplies study inputs.
        for name in ("lib.rmeta", "lib.rmeta-link"):
            (target / name).write_bytes(object_path.read_bytes())
        lib = target / "libruff_workspace.rlib"
        subprocess.run(
            ["ar", "crs", lib.name, "lib.rmeta", "lib.rmeta-link", object_path.name], cwd=target, check=True
        )
        receipt = keep(lib, store, b"!<arch>\n")
        with gzip.open(store / (receipt["sha256"] + ".gz"), "rb") as raw:
            archive = raw.read()
        assert archive == lib.read_bytes() and keep(lib, store, b"!<arch>\n") == receipt
        items, metadata = members(archive, owner)
        key = module(object_path.name, owner, "o")
        expected = hashlib.sha256(object_path.read_bytes()).hexdigest()
        assert items == {key: expected} and metadata == {"lib.rmeta": expected, "lib.rmeta-link": expected}
        refused(lambda: members(archive[:-1], owner))
        refused(lambda: members(archive, "ruff_linter"))
        assert_empty(work)
        bc = target / (stem + "no-opt.bc")
        bc.write_bytes(b"BC\xc0\xde" + b"controlled-reader-fixture" * 2)
        refused(lambda: assert_empty(work))
        (saved,) = stage(owner, target, root / "moved")
        assert saved["unit"] == key and saved["before"][:4] == saved["after"][:4] and not bc.exists()
        moved = root / "moved" / bc.name
        item = keep(moved, store, b"BC\xc0\xde")
        assert (
            item["stat"] == saved["after"]
            and item["sha256"] == hashlib.sha256(moved.read_bytes()).hexdigest()
        )
        refused(lambda: keep(moved, store, b"!<arch>\n"))
        assert len(list(store.iterdir())) == 2
        assert_empty(work)
    print("Exact ELF/ar and optional-file receipts, stale inputs and malformed inputs passed.")


if __name__ == "__main__":
    exercise()
