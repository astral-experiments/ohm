"""Verify genuine Cargo wire records and complete native programs for the registry-source guard."""

import argparse
import ctypes
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import zlib
from pathlib import Path

import tomllib

HERE = Path(__file__).resolve().parent
ORIGINAL = "eae0421727e3f13524a6c3710a5da281fa7bc44081003172726b0decad42aa4a"
REFERENCE = "6cd4366705a364ab503544070e57c20ecb399c6a58662590f3d62071f89e4961"
SOURCE_PARENT = "b05c0f1a01f8cae3ccb7446647fcb7d9b5a36c3dfabc340a78a8b189561036b6"
CANDIDATE = "32df98560d4ac57c4c959c762095a3afe6a3bbe62b44d8fc6e6bf8071f53a53e"
SHIPPED23 = "f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee"
SHIPPED24 = "a4faa288657042d02767a38812c7498218dfcafc945abfe3b4a44c07323a1a24"
SEED = ("old-parent", "settled-parent")
LEGACY = (
    "old-reader-real-edit",
    "old-reader-unchanged",
    "upgrade-without-new-prerequisite",
    "new-reader-after-prerequisite",
    "new-reader-independent-empty",
)
NINE = ("published-reader-empty-at-original-edit", "new-reader-empty-at-original-edit")
FIX = (
    "upgraded-real-edit",
    "settled-candidate",
    "first-invalid",
    "second-invalid",
    "repaired-candidate",
    "empty-candidate",
)
CLEAN = (
    "prerequisite-alone",
    "settled-prerequisite-alone",
    "pristine-independent-empty",
)
PREVIOUS = (
    "predecessor-first-edit",
    "predecessor-unchanged",
    "predecessor-independent-empty",
)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def blake3(suite, destination):
    archive = suite / "evidence/same-stamp-elf/originals.tar.gz"
    assert sha(archive.read_bytes()) == REFERENCE
    names = (
        "blake3.c",
        "blake3.h",
        "blake3_impl.h",
        "blake3_dispatch.c",
        "blake3_portable.c",
    )
    with tarfile.open(archive, "r:gz") as source:
        for name in names:
            (destination / name).write_bytes(
                source.extractfile("blake3/" + name).read()
            )
    libfile = destination / "blake3.so"
    subprocess.run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-O2",
            "-DBLAKE3_NO_AVX512",
            "-DBLAKE3_NO_AVX2",
            "-DBLAKE3_NO_SSE41",
            "-DBLAKE3_NO_SSE2",
            "-DBLAKE3_USE_NEON=0",
            *(str(destination / n) for n in names if n.endswith(".c")),
            "-o",
            libfile,
        ],
        check=True,
    )
    lib = ctypes.CDLL(str(libfile))

    def checksum(body):
        state = ctypes.create_string_buffer(4096)
        out = ctypes.create_string_buffer(32)
        lib.blake3_hasher_init(state)
        lib.blake3_hasher_update(
            state,
            (ctypes.c_ubyte * len(body)).from_buffer_copy(body),
            ctypes.c_size_t(len(body)),
        )
        lib.blake3_hasher_finalize(state, out, ctypes.c_size_t(32))
        return "blake3=" + out.raw.hex()

    assert (
        checksum(b"")
        == "blake3=af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
    )
    return checksum


def review(path, suite, run_native):
    assert sha(path.read_bytes()) == ORIGINAL
    spec = importlib.util.spec_from_file_location(
        "registry_wire", suite / "migration/review.py"
    )
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    cases = {
        "matched-fixed": (SOURCE_PARENT, CANDIDATE, FIX),
        "matched-legacy": (SOURCE_PARENT, CANDIDATE, LEGACY),
        "signed-fixed": (SHIPPED24, CANDIDATE, FIX),
        "signed-fixed-both-oracles": (
            SHIPPED24,
            CANDIDATE,
            FIX + ("empty-first-candidate",),
        ),
        "signed-legacy": (SHIPPED24, CANDIDATE, LEGACY + NINE),
        "signed-pristine": (SHIPPED24, CANDIDATE, CLEAN),
        "predecessor": (SHIPPED23, SHIPPED23, PREVIOUS),
        "predecessor-same-rust": (SHIPPED23, SHIPPED23, PREVIOUS),
        "downgrade": (SHIPPED24, SHIPPED23, PREVIOUS),
    }
    output = {}
    seen = {}
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(path, "r:xz") as ar:
        tmp = Path(tmp)
        checksum = blake3(suite, tmp)
        assert all(m.isfile() for m in ar.getmembers())
        assert len(ar.getnames()) == len(set(ar.getnames()))
        data = {m.name: ar.extractfile(m).read() for m in ar.getmembers()}
        for case, (parent, child, phases) in cases.items():
            prefix = case + "/"

            def get(name, local=prefix):
                return data[local + name]

            init = json.loads(get("registration.json"))
            assert init["cargo"] == {"parent": parent, "candidate": child}
            package = get("v5consumer.crate")
            lock = tomllib.loads(get("application/Cargo.lock").decode())
            (lib,) = [p for p in lock["package"] if p["name"] == "v5consumer"]
            assert (
                sha(package)
                == lib["checksum"]
                == init["package_archive"]
                == json.loads(get("registry/v5/co/v5consumer"))["cksum"]
            )
            with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as tar:
                source = tar.extractfile("v5consumer-0.1.0/src/lib.rs").read()
                build = tar.extractfile("v5consumer-0.1.0/build.rs").read()
            generated = b"pub const GENERATED: u8 = 83;"
            assert (
                source.count(b"17u8") == 1
                and b'include!(concat!(env!("OUT_DIR")' in source
                and generated in build
            )
            assert any(
                n.startswith(prefix + "rustc-dep-info/")
                and b"generated.rs" in d
                and b"v5consumer-0.1.0/src/lib.rs" in d
                for n, d in data.items()
            )
            records = json.loads(get("complete.json"))["rows"]
            assert tuple(r["name"] for r in records) == SEED + phases
            stats = records[0]["source_stat"]
            summary = {}
            for row in records:
                name = row["name"]

                def fetch(file, opened=get, phase=name):
                    return opened(phase + "/" + file)

                assert (
                    row == json.loads(fetch("result.json"))
                    and row["source_stat"] == stats
                )
                msgs = [
                    json.loads(line)
                    for line in fetch("stdout.jsonl").splitlines()
                    if line
                ]
                invalid = name in ("first-invalid", "second-invalid")
                assert row["exit"] == (101 if invalid else 0) and msgs[-1] == {
                    "reason": "build-finished",
                    "success": not invalid,
                }
                codes = [
                    m["message"].get("code")
                    for m in msgs
                    if m["reason"] == "compiler-message"
                ]
                assert any(c and c["code"] == "E0308" for c in codes) == invalid
                assert row["nominal"] == [
                    m["target"]["name"]
                    for m in msgs
                    if m["reason"] == "compiler-artifact" and not m["fresh"]
                ]
                if name in SEED:
                    values, token = "7 17 83", b"17u8"
                elif name in CLEAN:
                    values, token = "9 17 83", b"17u8"
                elif name in LEGACY[:3] or name in PREVIOUS[:2] and case != "downgrade":
                    values, token = "9 17 83", b"29u8"
                elif name in LEGACY[3:]:
                    values, token = "8 29 83", b"29u8"
                elif name in FIX[4:]:
                    values, token = "8 17 83", b"17u8"
                else:
                    values, token = "9 29 83", b"true" if invalid else b"29u8"
                body = source.replace(b"17u8", token)
                assert (
                    sha(body) == row["source_sha256"]
                    and len(body) == stats[2]
                    and row["display"] == values
                )
                native = row["elf"]
                elf = zlib.decompress(get("native/" + native + ".z"))
                assert (
                    sha(elf) == native
                    and elf[:6] == b"\x7fELF\x02\x01"
                    and int.from_bytes(elf[18:20], "little") == 62
                )
                if run_native and native not in seen:
                    program = tmp / native
                    program.write_bytes(elf)
                    program.chmod(0o700)
                    p = subprocess.run(
                        [program],
                        cwd=tmp,
                        env={"PATH": os.defpath, "HOME": str(tmp), "LC_ALL": "C"},
                        check=True,
                        capture_output=True,
                    )
                    assert not p.stderr
                    seen[native] = p.stdout.decode().strip()
                if run_native:
                    assert seen[native] == values
                wire = fetch("translated.bin")
                version, files = reader.decode(wire)
                assert sha(wire) == row["wire_sha256"] and row["wire"] == {
                    "version": version,
                    "files": {p: list(x) for p, x in files.items()},
                    "env": {},
                }
                selected = init["cargo"][row["role"]]
                expected_version = (
                    2
                    if selected == SHIPPED23
                    else (
                        6
                        if selected == CANDIDATE
                        and name != "upgrade-without-new-prerequisite"
                        else 5
                    )
                )
                assert version == expected_version
                (gen,) = [x for p, x in files.items() if p.endswith("/generated.rs")]
                assert gen == (
                    (1, None, None)
                    if version == 2
                    else (1, len(generated), checksum(generated))
                )
                assert len(files) == (2 if version == 6 else 1)
                if version == 6:
                    last_good = source.replace(b"17u8", b"29u8" if invalid else token)
                    assert files["src/lib.rs"] == (
                        2,
                        len(last_good),
                        checksum(last_good),
                    )
                for owner, fields in row["products"].items():
                    for kind, detail in fields.items():
                        raw = fetch(owner + "." + kind)
                        assert (
                            len(raw) == detail["bytes"] and sha(raw) == detail["sha256"]
                        )
                        if kind == "public":
                            assert json.loads(raw) == detail["value"]
                summary[name] = {
                    "runtime": values,
                    "exit": row["exit"],
                    "elf": native,
                    "wire_version": version,
                    "wire_inputs": len(files),
                    "source_sha256": sha(body),
                    "provider_public": row["products"]["guardprovider"]["public"][
                        "value"
                    ]["value"],
                    "consumer_rmeta": row["products"]["v5consumer"]
                    .get("rmeta", {})
                    .get("sha256"),
                }
            assert len({r["provider_public"] for r in summary.values()}) == 1

            def same(first, second, items=summary):
                return items[first]["elf"] == items[second]["elf"]

            if phases[: len(FIX)] == FIX:
                if phases != FIX:
                    assert same(FIX[0], "empty-first-candidate")
                    assert (
                        summary[FIX[0]]["consumer_rmeta"]
                        == summary["empty-first-candidate"]["consumer_rmeta"]
                    )
                assert (
                    same(FIX[0], FIX[1])
                    and same(FIX[0], FIX[2])
                    and same(FIX[0], FIX[3])
                    and same(FIX[4], FIX[5])
                )
            elif phases == CLEAN:
                assert all(same(CLEAN[0], n) for n in CLEAN)
            elif phases == PREVIOUS:
                assert same(PREVIOUS[0], PREVIOUS[1]) and same(
                    PREVIOUS[0], PREVIOUS[2]
                ) == (case == "downgrade")
            else:
                assert (
                    same(LEGACY[0], LEGACY[1])
                    and same(LEGACY[0], LEGACY[2])
                    and same(LEGACY[3], LEGACY[4])
                )
                if case == "signed-legacy":
                    assert same(NINE[0], NINE[1]) and not same(NINE[0], LEGACY[0])
                    assert (
                        summary[SEED[0]]["consumer_rmeta"]
                        == summary[LEGACY[0]]["consumer_rmeta"]
                        != summary[NINE[0]]["consumer_rmeta"]
                    )
            output[case] = {"cargo": init["cargo"], "phases": summary}
    return {
        "originals_sha256": ORIGINAL,
        "histories": output,
        "commands": sum(len(v["phases"]) for v in output.values()),
        "reexecuted_unique_native_bodies": len(seen),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", type=Path, default=HERE.parents[1])
    ap.add_argument("--run-native", action="store_true")
    args = ap.parse_args()
    print(
        json.dumps(
            review(HERE / "originals.tar.xz", args.suite, args.run_native),
            indent=2,
            sort_keys=True,
        )
    )
