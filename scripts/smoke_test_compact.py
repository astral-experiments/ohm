"""Exercise compact artifacts with an installed, compact-capable Linux release."""

import json
import os
import pathlib
import subprocess
import sys


def compact_members(path):
    data = pathlib.Path(path).read_bytes()
    if not data.startswith(b"!<arch>\n"):
        raise ValueError(f"expected a self-contained ar archive: {path}")
    offset = 8
    count = 0
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:60] != b"`\n":
            raise ValueError(f"invalid ar member header: {path}")
        size = int(header[48:58])
        start = offset + 60
        end = start + size
        if size < 0 or end > len(data):
            raise ValueError(f"invalid ar member size: {path}")
        # BSD archives store an extended filename before the member bytes.
        if header.startswith(b"#1/"):
            start += int(header[3:16])
            if start > end:
                raise ValueError(f"invalid ar member name: {path}")
        count += data[start:end].startswith(b"RCOBJ001")
        offset = end + size % 2
    return count


def smoke(manifest, target, toolchain, crate, root):
    wild = manifest.get("bundled_tools", {}).get("wild")
    if target != "x86_64-unknown-linux-gnu" or wild is None:
        return
    marker = toolchain / "lib/rustlib" / target / "bin/wild-ld/compact-artifacts-v2"
    if not marker.exists() and "source" not in wild:
        return
    if not marker.is_file() or marker.read_bytes() != b"RCOBJ001\n":
        raise ValueError("source-built Wild is missing its compact capability marker")
    if not compact_members(root / "defaults-target/debug/libohm_smoke.rlib"):
        raise ValueError("Ohm defaults produced no compact archive members")
    if compact_members(root / "disabled-target/debug/libohm_smoke.rlib"):
        raise ValueError("compact objects appeared with Ohm defaults disabled")

    environment = os.environ.copy()
    for name in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "RUSTFLAGS",
                 "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS"):
        environment.pop(name, None)
    environment.update(
        RUSTC=str(toolchain / "bin/rustc"),
        RUSTDOC=str(toolchain / "bin/rustdoc"),
        CARGO_TARGET_DIR=str(root / "compact-target"),
        CARGO_BUILD_BUILD_DIR=str(root / "compact-build"),
    )
    opt_out = environment | {
        "CARGO_TARGET_DIR": str(root / "compact-opt-out-target"),
        "CARGO_BUILD_BUILD_DIR": str(root / "compact-opt-out-build"),
    }
    subprocess.run(
        [str(toolchain / "bin/cargo"), "-Zohm-compact-artifacts=no", "run",
         "--manifest-path", str(crate / "Cargo.toml")],
        env=opt_out, check=True,
    )
    if compact_members(root / "compact-opt-out-target/debug/libohm_smoke.rlib"):
        raise ValueError("compact objects appeared with the explicit opt-out")
    subprocess.run(
        [str(toolchain / "bin/cargo"), "-Zohm-compact-artifacts=yes", "run",
         "--manifest-path", str(crate / "Cargo.toml")],
        env=environment, check=True,
    )
    if not compact_members(root / "compact-target/debug/libohm_smoke.rlib"):
        raise ValueError("explicit compact selection produced no compact archive members")
    linked = subprocess.run(
        ["readelf", "--string-dump=.comment", str(root / "compact-target/debug/ohm-smoke")],
        check=True, capture_output=True, text=True,
    )
    if "Wild" not in linked.stdout:
        raise ValueError("compact smoke executable was not linked by Wild")


if __name__ == "__main__":
    manifest, target, toolchain, crate, root = sys.argv[1:]
    smoke(json.loads(pathlib.Path(manifest).read_text()), target,
          pathlib.Path(toolchain), pathlib.Path(crate), pathlib.Path(root))
