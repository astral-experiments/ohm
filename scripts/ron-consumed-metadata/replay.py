"""Replay the original signed Ron role and the two independent bad-input controls."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import consumer
from mapped import run_child


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def safe_relative(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(name)
    return p


def materialize(role, root):
    root.mkdir()
    archive = HERE / "inputs/role-files.tar.zst"
    assert digest(archive) == role["input_archive_sha256"]
    raw = subprocess.check_output(["zstd", "-dcq", str(archive)])
    assert len(raw) < 96 * 2**20
    objects = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for member in tar:
            if member.isdir():
                continue
            name = safe_relative(member.name).name
            assert (
                re.fullmatch("[a-f0-9]{64}", name)
                and member.isfile()
                and member.size < 20 * 2**20
            )
            body = tar.extractfile(member).read()
            assert hashlib.sha256(body).hexdigest() == name and name not in objects
            objects[name] = body
    assert set(role["member_sha256"].values()) == set(objects) and len(objects) == 36
    registry = root / "cargo-home/registry/src/index.crates.io-1949cf8c6b5b557f"
    source_members = 0
    for name, oid in role["member_sha256"].items():
        file = root / safe_relative(name)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(objects[oid])
        if file.suffix != ".crate":
            continue
        with tarfile.open(file, "r:gz") as crate:
            for member in crate:
                if member.isdir():
                    continue
                rel = safe_relative(member.name)
                assert (
                    rel.parts[0] == file.stem
                    and member.isfile()
                    and member.size < 5 * 2**20
                )
                path = registry / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(crate.extractfile(member).read())
                source_members += 1
    assert source_members == role["source_members"]
    assert all(
        digest(root / name) == row["physical_sha"]
        for name, row in role["foreign_source"].items()
    )


def physical_sdk(sdk):
    files = read(HERE / "inputs/signed-sdk-files.json")
    assert len(files) == 79
    for path, (mode, size, sha) in files.items():
        file = sdk / safe_relative(path)
        assert file.is_file() and not file.is_symlink(), path
        assert (
            file.stat().st_size,
            stat.S_IMODE(file.stat().st_mode),
            digest(file),
        ) == (size, mode, sha), path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work", type=Path, required=True, help="An entirely new private directory"
    )
    parser.add_argument(
        "--sdk",
        type=Path,
        required=True,
        help="The extracted signed Ohm -23 Linux x86_64 SDK",
    )
    parser.add_argument("--b3sum", default="b3sum")
    parser.add_argument(
        "--stock-rustup-home",
        type=Path,
        help="Optional official Rust 1.99.0 registered as ohm",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Also strace the exact regular compiler command; requires child tracing",
    )
    args = parser.parse_args()
    sdk = args.sdk.resolve(strict=True)
    output = args.work.resolve()
    if output.exists():
        raise SystemExit("--work must name a new directory")
    output.mkdir(parents=True)
    for name in ("phases", "output", "tmp", "rustup/toolchains"):
        (output / name).mkdir(parents=True)
    (output / "rustup/toolchains/ohm").symlink_to(sdk, target_is_directory=True)
    physical_sdk(sdk)
    role = read(HERE / "inputs/invocation.json")
    inputs = output / "input"
    materialize(role, inputs)

    def local(value):
        return value.replace("$ROLE", str(inputs))

    command = [local(arg) for arg in role["argv"]]
    current = output / "output"
    command[command.index("--out-dir") + 1] = str(current)
    env = {
        k: os.environ[k] for k in ("HOME", "PATH", "USER", "LANG") if k in os.environ
    }
    env.update({k: local(v) for k, v in role["compiler_env"].items()})
    env.update(RUSTUP_HOME=str(output / "rustup"), TMPDIR=str(output / "tmp"))
    cwd = Path(local(role["cwd"]))
    assert (
        subprocess.check_output(["rustc", "+ohm", "-vV"], cwd=cwd, env=env, text=True)
        == role["signed"]["rustc"]
    )
    core = next((inputs / "shared").rglob("libserde_core-*.rmeta"))
    original = core.read_bytes()
    malformed = b"R" + original[1:]
    stamp = core.stat()

    def install(new_bytes):
        # Fresh inode on the same device, private to this run.
        temporary = output / "prepared-rmeta"
        temporary.write_bytes(new_bytes)
        temporary.chmod(stamp.st_mode)
        os.utime(temporary, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        os.replace(temporary, core)

    def b3(data):
        return subprocess.check_output([args.b3sum], input=data).decode().split()[0]

    hashes = {"valid": b3(original), "malformed": b3(malformed)}
    rows = {}
    phases = output / "phases"
    optional = ["-Zbinary-dep-depinfo", "-Zchecksum-hash-algorithm=blake3"]

    def phase(name, *, flags=(), mode=None, tracing=False):
        assert not list(current.iterdir())
        label = phases / name
        label.mkdir()
        argv = command + list(flags)
        if mode:
            row = run_child(
                argv, cwd, env, core, sdk / "bin/rustc", current, label, mode
            )
        else:
            if tracing:
                argv = [
                    "strace",
                    "-ff",
                    "-qq",
                    "-yy",
                    "-ttt",
                    "-v",
                    "-s",
                    "256",
                    "-o",
                    str(label / "sys"),
                    "-e",
                    "trace=%file,read,pread64,readv,mmap,getdents64,close,execve,execveat",
                    "--",
                    *argv,
                ]
            with (label / "stdout").open("xb") as so, (label / "stderr").open(
                "xb"
            ) as se:
                rc = subprocess.run(
                    argv, cwd=cwd, env=env, stdout=so, stderr=se, timeout=150
                ).returncode
            row = {"rc": rc}
        row["errors"] = [
            e["code"]["code"]
            for line in (label / "stderr").read_bytes().splitlines()
            if line.startswith(b"{") and (e := json.loads(line)).get("code")
        ]
        row["outputs"] = {}
        row["core_checksum"] = []
        for f in sorted(current.iterdir()):
            assert f.is_file()
            row["outputs"][f.name] = digest(f)
            if f.suffix == ".d":
                row["core_checksum"] = [
                    line
                    for line in f.read_text().splitlines()
                    if line.startswith("# checksum:") and line.endswith(" " + str(core))
                ]
            f.rename(label / f.name)
        rows[name] = row
        save(label / "result.json", row)
        print(name, row["rc"], row["errors"][:2], flush=True)
        return row

    phase("regular")
    if args.trace:
        phase("same-argv-trace", tracing=True)
        logs = [p.read_text() for p in (phases / "same-argv-trace").glob("sys.*")]
        assert any(
            any(
                "mmap(" in line and str(core) + ">" in line for line in log.splitlines()
            )
            for log in logs
        )
    # Separate actual E0782 control from the genuine signed macro image.
    macro = next((inputs / "target").rglob("libserde_derive-*.so"))
    native = macro.read_bytes()
    mutation = read(HERE / "inputs/macro-mutation.json")
    assert hashlib.sha256(native).hexdigest() == mutation["normal"]
    changed = bytearray(native)
    for offset in mutation["offsets"]:
        word = b"serialize_newtype_struct"
        assert changed[offset : offset + len(word)] == word
        changed[offset + len(word) - 1] = ord("x")
    assert hashlib.sha256(changed).hexdigest() == mutation["malformed"]
    macro.write_bytes(changed)
    damaged = phase("wrong-macro")
    assert damaged["rc"] != 0 and damaged["errors"] == ["E0782", "E0782"]
    macro.write_bytes(native)
    phase("macro-repair")
    before = core.stat()
    with core.open("r+b", buffering=0) as dst:
        assert os.pwrite(dst.fileno(), b"R", 0) == 1
        os.fsync(dst.fileno())
    os.utime(core, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = core.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    broken = phase("static-transitive-malformed")
    assert (
        broken["rc"] != 0
        and "E0463" in broken["errors"]
        and not any(k.endswith((".rlib", ".rmeta")) for k in broken["outputs"])
    )
    install(original)
    phase("static-repair")
    phase("optional-clean", flags=optional)
    for mode in ("sham", "rename", "inplace_restore", "inplace"):
        row = phase(mode, flags=optional, mode=mode)
        expected = hashes[
            "valid" if mode in ("sham", "inplace_restore") else "malformed"
        ]
        assert (
            row["rc"] == 0
            and len(row["core_checksum"]) == 1
            and expected in row["core_checksum"][0]
        )
        install(original)
    # Only independent frozen objects seed the second installation. Keep paths identical.
    inputs.rename(output / "first-history")
    materialize(role, inputs)
    assert (
        core.stat().st_ino
        != (output / "first-history" / core.relative_to(inputs)).stat().st_ino
    )
    install(malformed)
    broken_empty = phase("independent-empty-malformed", flags=optional)
    assert broken_empty["rc"] != 0 and "E0463" in broken_empty["errors"]
    install(original)
    phase("independent-empty-valid", flags=optional)
    native_inputs = {k: phases / k for k, val in rows.items() if val["rc"] == 0}
    want = {
        "regular",
        "macro-repair",
        "static-repair",
        "optional-clean",
        "sham",
        "rename",
        "inplace_restore",
        "inplace",
        "independent-empty-valid",
    }
    if args.trace:
        want.add("same-argv-trace")
    assert set(native_inputs) == want
    paths = [
        v for i, a in enumerate(command) if a == "-L" for v in ("-L", command[i + 1])
    ]
    verdict = consumer.run(output / "consumer", env, paths, native_inputs)
    assert len({val["ELF"] for val in verdict["physical_artifacts"].values()}) == 1
    unflagged = {"regular", "macro-repair", "static-repair", "same-argv-trace"}
    for group in (set(native_inputs) & unflagged, set(native_inputs) - unflagged):
        assert len({verdict["physical_artifacts"][k]["rlib"] for k in group}) == 1
    archives = [
        next((phases / k).glob("*.rlib")) for k in ("regular", "optional-clean")
    ]
    names = [
        subprocess.check_output(["ar", "t", a], text=True).splitlines()
        for a in archives
    ]
    assert names[0] == names[1] and len(names[0]) == 12
    different = {}
    for name in names[0]:
        old, new = [subprocess.check_output(["ar", "p", a, name]) for a in archives]
        if old != new:
            assert name == "lib.rmeta" and len(old) == len(new) == 736
            offsets = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
            assert set(offsets).issubset(range(213, 229))
            different[name] = offsets
    result = {
        "signed": role["signed"],
        "expected_checksums": hashes,
        "native": rows,
        "consumer": verdict,
        "cross_flag_archive_comparison": {
            "members": names[0],
            "changed_offsets": different,
        },
    }
    if args.stock_rustup_home:
        import upstream_optional

        result["official_reduced"] = upstream_optional.exercise(
            output / "official-optional", args.stock_rustup_home.resolve(strict=True)
        )
    save(output / "result.json", result)
    print(output / "result.json", flush=True)


if __name__ == "__main__":
    main()
