"""Reopen the actual completed smoke's wasm, native executables, docs and sharing logs."""

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import locations, need, save, sha


def main():
    _, target = locations()
    s, receipt = map(Path, sys.argv[1:])
    wasm = s / "defaults-target/wasm32-unknown-unknown/debug/ohm-smoke.wasm"
    with wasm.open("rb") as f:
        need(f.read(8) == b"\0asm\1\0\0\0", "invalid final wasm")
    fpaths = {
        "wasm": wasm,
        "native": s / "defaults-target/debug/ohm-smoke",
        "disabled_native": s / "disabled-target/debug/ohm-smoke",
        "documentation": s / "crate/target/doc/ohm_smoke/index.html",
        "shared_registry_cli": s / "registry-sibling-target/debug/ohm-registry-smoke",
    }
    for key in ("native", "disabled_native"):
        subprocess.run([fpaths[key]], check=True)
    need(
        subprocess.check_output([fpaths["shared_registry_cli"]]).strip() == b"42",
        "wrong shared-registry sibling",
    )
    need(
        (s / "defaults-rustc-args").read_text().splitlines() == ["enabled"]
        and (s / "disabled-rustc-args").read_text().splitlines() == ["disabled"],
        "defaults wrapper results",
    )
    for n in ("registry-sibling.log", "registry-check.log"):
        log = (s / n).read_text()
        need(
            "Fresh itoa v1.0.15" in log and "Compiling itoa " not in log and "Checking itoa " not in log,
            "shared registry was not fresh",
        )
    paths = {
        "sha256": {k: sha(f) for k, f in fpaths.items()},
        "bytes": {k: f.stat().st_size for k, f in fpaths.items()},
    }
    if target.startswith("x86_64"):
        f = s / "linker-target/debug/ohm-smoke"
        for n, p in [("default", fpaths["native"]), ("last_explicit", f)]:
            note = subprocess.check_output(["readelf", "--string-dump=.comment", p], text=True)
            need("wild" in note.lower(), "missing actual Wild section")
            paths[n + "_elf_comment"] = note
    save(receipt / "payloads.json", paths)


if __name__ == "__main__":
    main()
