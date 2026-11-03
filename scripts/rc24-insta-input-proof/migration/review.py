import collections
import ctypes
import hashlib
import json
import subprocess
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path

import tomllib


def decode(data):
    import io

    f = io.BytesIO(data)

    def get(n):
        b = f.read(n)
        assert len(b) == n
        return b

    def integer(n):
        return int.from_bytes(get(n), "little")

    def blob():
        return get(integer(4))

    assert get(5) == b"\1\0\0\0\xff"
    version = integer(1)
    assert version in (2, 5, 6)
    files = {}
    for _ in range(integer(4)):
        kind = integer(1)
        name = blob().decode()
        has = integer(1)
        assert kind in (0, 1, 2, 3) and has in (0, 1) and name not in files
        files[name] = (kind, integer(8), blob().decode()) if has else (kind, None, None)
    assert integer(4) == 0 and f.read() == b""
    return version, files


def sha(b):
    return hashlib.sha256(b).hexdigest()


def review(raw, plan, source_archive, reader_archive, fixture, *, require_kernel=True):
    lock = tomllib.loads((fixture / "Cargo.lock").read_text())
    (spec,) = [p for p in lock["package"] if p["name"] == "insta"]
    assert (
        spec["version"] == "1.48.0"
        and sha(source_archive.read_bytes()) == spec["checksum"]
    )
    with tarfile.open(source_archive, "r:gz") as ar:
        code = {
            m.name.removeprefix("insta-1.48.0/"): ar.extractfile(m).read()
            for m in ar
            if m.isfile()
        }
    base = b'snapshot_path: "snapshots".into(),'
    change = b'snapshot_path: "snapsh0ts".into(),'
    bad = (
        b"snapshot_path: false"
        + b" " * (len(base) - len(b"snapshot_path: false,"))
        + b","
    )
    old = code["src/settings.rs"]
    assert old.count(base) == 1 and len(base) == len(change) == len(bad)
    edits = {
        form: old.replace(base, v)
        for form, v in [("old", base), ("good", change), ("invalid", bad)]
    }
    with (
        zipfile.ZipFile(raw) as z,
        tempfile.TemporaryDirectory() as td,
        tarfile.open(reader_archive, "r:gz") as ar,
    ):
        assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
        td = Path(td)
        ns = [
            "blake3.c",
            "blake3.h",
            "blake3_impl.h",
            "blake3_dispatch.c",
            "blake3_portable.c",
        ]
        for name in ns:
            (td / name).write_bytes(ar.extractfile("blake3/" + name).read())
        so = td / "hash.so"
        subprocess.run(
            [
                "cc",
                "-O2",
                "-fPIC",
                "-shared",
                "-DBLAKE3_NO_AVX512",
                "-DBLAKE3_NO_AVX2",
                "-DBLAKE3_NO_SSE41",
                "-DBLAKE3_NO_SSE2",
                "-DBLAKE3_USE_NEON=0",
                *[str(td / n) for n in ns if n.endswith(".c")],
                "-o",
                str(so),
            ],
            check=True,
        )
        lib = ctypes.CDLL(str(so))

        def bb(b):
            st = ctypes.create_string_buffer(4096)
            out = ctypes.create_string_buffer(32)
            lib.blake3_hasher_init(st)
            lib.blake3_hasher_update(
                st,
                (ctypes.c_ubyte * len(b)).from_buffer_copy(b),
                ctypes.c_size_t(len(b)),
            )
            lib.blake3_hasher_finalize(st, out, ctypes.c_size_t(32))
            return "blake3=" + out.raw.hex()

        init = json.loads(z.read("registration.json"))
        terminal = json.loads(z.read("complete.json"))
        assert init["seeds"] == terminal["roles"] == plan["cargo"]
        phases = [
            "parent-old",
            "parent-unchanged",
            "upgrade-valid",
            "candidate-settled",
            "invalid",
            "invalid-repeated",
            "candidate-repair",
            "downgrade",
            "second-upgrade",
            "second-settled",
            "empty-repair",
        ]
        assert init["order"] == phases == [x["label"] for x in terminal["rows"]]
        oldelf, goodelf = terminal["native"]
        assert oldelf != goodelf
        bodies = {}
        for h in (oldelf, goodelf):
            body = zlib.decompress(z.read("native/" + h + ".z"))
            assert sha(body) == h and body.startswith(b"\x7fELF")
            bodies[h] = len(body)
        pts = set()
        identities = set()
        ph = []
        for label, v in zip(phases, terminal["rows"], strict=True):
            assert v == json.loads(z.read(label + "/result.json"))
            codes = [
                json.loads(l)
                for l in z.read(label + "/stdout.jsonl").splitlines()
                if l.startswith(b"{")
            ]
            invalid = label in ("invalid", "invalid-repeated")
            former = label in ("upgrade-valid", "candidate-settled") or invalid
            assert codes[-1] == {
                "reason": "build-finished",
                "success": not invalid,
            } and v["exit"] == (101 if invalid else 0)
            if invalid:
                assert any(
                    m["reason"] == "compiler-message"
                    and (m["message"].get("code") or {}).get("code") == "E0308"
                    and any(
                        x["is_primary"]
                        and x["file_name"].endswith("/insta-1.48.0/src/settings.rs")
                        for x in m["message"]["spans"]
                    )
                    for m in codes
                )
            assert (
                v["elf"] == (goodelf if former else oldelf)
                and v["bytes"] == bodies[v["elf"]]
                and v["display"] == ("snapsh0ts" if former else "snapshots")
            )
            if label not in ("parent-old", "parent-unchanged"):
                assert v["same_stat"] == terminal["source_stat"] and v[
                    "source_sha256"
                ] == sha(edits["invalid" if invalid else "good" if former else "old"])
            wire = z.read(label + "/translated-dep-info")
            ver, files = decode(wire)
            assert (
                sha(wire) == v["translated_sha256"]
                and len(wire) == v["translated_bytes"]
                and ver == v["translated_version"]
            )
            pts.add(v["translated_path"])
            actual = []
            for f in [
                n
                for n in z.namelist()
                if n.startswith(label + "/tasks/") and n.endswith(".nul")
            ]:
                argv = z.read(f).split(b"\0")
                args = argv[4:-1]
                assert argv[-1] == b""
                if argv[3].endswith(b"/bin/rustc") and b"--crate-name" in args:
                    owner = args[args.index(b"--crate-name") + 1].decode()
                    identities.add(tuple(argv[1:4]))
                    actual.append(owner)
            if require_kernel:
                assert "physical_rustcs" in v and collections.Counter(
                    actual
                ) == collections.Counter(v["physical_rustcs"])
                if label in (
                    "upgrade-valid",
                    "candidate-repair",
                    "downgrade",
                    "second-upgrade",
                ):
                    assert "insta" in actual
            else:
                assert not actual and "physical_rustcs" not in v
            if v["role"] == "parent":
                assert ver == 2 and not files and len(wire) == 14
            else:
                assert ver == 6 and len(files) > 0 and "src/settings.rs" in files
                for name, (kind, size, checksum) in files.items():
                    b = (
                        edits["good" if former else "old"]
                        if name == "src/settings.rs"
                        else code[name]
                    )
                    assert kind == 2 and size == len(b) and checksum == bb(b), (
                        label,
                        name,
                    )
            ph.append(
                {
                    "label": label,
                    "role": v["role"],
                    "status": v["exit"],
                    "wire_version": ver,
                    "wire_bytes": len(wire),
                    "files": len(files),
                    "actual_rustcs": actual,
                    "elf": v["elf"],
                }
            )
        assert len(pts) == 1 and len(identities) == int(require_kernel)
        return {
            "kernel_required": require_kernel,
            "fixed_translated_path": pts.pop(),
            "compiler_identity": [v.decode() for v in identities.pop()]
            if require_kernel
            else None,
            "native": terminal["native"],
            "phases": ph,
        }
