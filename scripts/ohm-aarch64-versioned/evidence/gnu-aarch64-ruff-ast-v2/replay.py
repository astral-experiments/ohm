"""Run one independently warmed native Ruff history on a supplied, previously authenticated cross SDK."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sys


HERE = Path(__file__).resolve().parent
ROLE_HARD = {"A": {"ruff_python_ast", "compact_str", "zmij"}, "N": {"ruff_python_ast", "compact_str"}, "M": set()}
FORBIDDEN = {"CI", "CARGO_INCREMENTAL", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER"}


def hash_file(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def copy_sdk(source, dest, role):
    table = json.loads((HERE / "source/sdk-members.json").read_bytes())
    expected = table["common"] | {table["driver_path"]: table["roles"][role]["driver"]}
    assert len(expected) == 119
    for name, (digest, length, mode) in expected.items():
        old = source / name
        assert old.is_file() and old.stat().st_size == length and old.stat().st_mode & 0o777 == mode
        assert hash_file(old) == digest, name
        new = dest / name
        new.parent.mkdir(parents=True, exist_ok=True)
        assert not new.exists()
        shutil.copyfile(old, new)
        new.chmod(mode)
        assert hash_file(new) == digest and new.stat().st_size == length
    return table["roles"][role]["source"]


class Files:
    """Expose on-disk phase records to the unchanged zip-member reader."""

    def __init__(self, folder):
        self.folder = folder

    def read(self, name):
        return (self.folder / name).read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("A", "N", "V"), help="public #276, GNU prerequisite, or final versioned compiler")
    parser.add_argument("sdk", type=Path, help="source-matched SDK including the companion Cargo and AArch64 std")
    parser.add_argument("fresh_directory", type=Path, help="must be absent; all acquired inputs, outputs and receipts stay here")
    args = parser.parse_args()
    role = "M" if args.role == "V" else args.role
    sdk = args.sdk.resolve(strict=True)
    work = args.fresh_directory.resolve()
    assert not work.exists() and sdk != work and sdk not in work.parents
    assert work.parent.is_dir() and shutil.disk_usage(work.parent).free > 12 * 2**30
    for tool in ("cargo", "rustc", "rustup", "git", "strace", "qemu-aarch64", "aarch64-linux-gnu-gcc"):
        assert shutil.which(tool), tool
    for tool in ("cargo", "rustc"):
        assert os.path.samefile(shutil.which(tool), shutil.which("rustup")), "use the genuine rustup proxies"

    work.mkdir(mode=0o700)
    private_home = work / "home"
    private_home.mkdir()
    proxy = Path(shutil.which("rustup")).resolve(strict=True)
    shim = private_home / ".cargo/bin"
    shim.mkdir(parents=True)
    for tool in ("rustup", "rustc", "cargo"):
        (shim / tool).symlink_to(proxy)
    os.environ.update(QA_ROOT=os.fspath(work), HOME=os.fspath(private_home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                      PATH=os.fspath(shim) + os.pathsep + os.environ["PATH"])
    for key in FORBIDDEN:
        os.environ.pop(key, None)
    sys.path.insert(0, str(HERE / "replay/ohm-aarch64-linux"))
    import qualify as q

    rt = q.rt
    rt.room()
    rt.LOG.mkdir()
    source = copy_sdk(sdk, rt.SDK, role)
    q.prepare_graph()
    state = q.source_values(rt.RUFF)
    home = rt.environment()
    proof = runpy.run_path(str(HERE / "replay/ohm-aarch64-confirm/complete-native-roster.py"))["inspect"]
    root = rt.LOG / "review-history"
    root.mkdir()
    searches = []
    phases = {}
    active = "old"
    crates = {}

    def visit(label, classification):
        nonlocal active
        if active != classification:
            q.change_source(rt.RUFF, state, classification)
            active = classification
        row = q.visit(root, label, classification, home, searches)
        native = q.load(root / label / "native.json")
        kernel = proof(Files(root), label, native)
        assert kernel["cargo"] == kernel["rustup-dispatch"] == 1
        for process in native["rustcs"]:
            if process["crate"] in ROLE_HARD["A"] and process["terminal"] == [0]:
                crates[process["crate"]] = process["argv"]
        if label in ("edit", "unchanged-1", "unchanged-2"):
            wanted = set(ROLE_HARD[role])
            if label == "edit":
                wanted.add("ruff_python_ast")
            assert sorted(row["crates"]) == sorted(wanted)
            assert set(kernel) <= {"rustcs", "cargo", "rustup-dispatch"}
            assert kernel.get("rustcs", 0) == len(wanted)
        if classification != "invalid":
            assert len(row["typed"]) == 39 and len(row["archive"]["objects"]) == 95
            assert set(crates) == ROLE_HARD["A"]
            for name, argv in crates.items():
                out = Path(argv[argv.index("--out-dir") + 1])
                suffix, = [v.partition("=")[2] for v in argv if v.startswith("extra-filename=")]
                rules = (out / (name + suffix + ".d")).read_bytes().splitlines()
                hard = b"/dev/null/ohm-untracked-relink-inputs:"
                original = b"/dev/null/ohm-recheck-dependent-links:"
                versioned = b"/dev/null/ohm-recheck-dependent-links-v2:"
                want = hard if name in ROLE_HARD[role] else versioned if role == "M" else original
                assert [value for value in (hard, original, versioned) if value in rules] == [want]
        phases[label] = (row, kernel)

    q.acquire(root, rt.ROOT / "seed")
    visit("old-empty", "old")
    visit("edit", "new")
    visit("unchanged-1", "new")
    visit("unchanged-2", "new")
    visit("invalid", "invalid")
    visit("repair", "new")
    q.park("review-warm")
    q.acquire(root / "clean", rt.ROOT / "seed")
    searches.clear()
    crates.clear()
    visit("empty-edited", "new")
    reference = q.semantic(phases["empty-edited"][0])
    for label in ("edit", "unchanged-1", "unchanged-2", "repair"):
        assert q.semantic(phases[label][0]) == reference and phases[label][0]["typed"] == phases["empty-edited"][0]["typed"]
    assert phases["old-empty"][0]["reader"] != reference["reader"]

    results = {
        "source": source,
        "role": args.role,
        "lock": q.LOCK,
        "driver_and_cargo": {p.name: hash_file(p) for p in [*rt.SDK.glob("lib/librustc_driver-*.so"), rt.SDK / "bin/cargo"]},
        "phases": {
            label: {"actual": events, "rustcs": row["crates"], "reader": row.get("reader"), "value": row.get("value")}
            for label, (row, events) in phases.items()
        },
    }
    q.save(rt.LOG / "reviewed-native.json", results)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
