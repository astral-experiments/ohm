"""Use the existing process-tree instruction counter and a separate physical PTRACE_EXEC replay."""

import json
import mmap
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import subprocess
import tempfile

from kits import HOST, WILD, need, sha, write
from state import BAD, GEN, digest, env, identity_env, output, payload


def calibrated(row):
    return (
        row["event_errno"] == 0
        and row["instructions"] > 0
        and row["enabled"] == row["running"]
        and row["running"] > 0
    )


def tools(root, packaging):
    build = root / "observers"
    build.mkdir()
    expect = {
        "watch.c": "ee82d0f9f0410861f3680c7ebf7f26547cd3a73833290d7272e83b4e29e0d903",
        "calibrate.c": "dacd1dd7fef85cacb44a236e0c4191d95db036a623b2a01ae3a5d76d2f3d0b0e",
        "observe.c": "b36f563ba76ae952c9e09eb532491e4b525502d4953dd1964fb236744abb0d18",
    }
    for n in expect:
        path = (
            packaging
            / ("physical/scripts/ron-check-share" if n == "observe.c" else "pmu/scripts/ohm-gnu-syscall")
            / n
        )
        need(sha(path) == expect[n], "changed observer " + n)
        subprocess.run(
            [
                "cc",
                "-O2",
                "-Wall",
                "-Werror",
                *(["-pthread"] if n == "calibrate.c" else []),
                path,
                "-o",
                build / n[:-2],
            ],
            check=True,
        )
    shutil.copy("/usr/bin/false", build / "never-selected")
    need(
        not (build / "never-selected").samefile("/usr/bin/false"),
        "physical sentinel reused a system tool inode",
    )
    base = root / "receipts/calibration"
    base.mkdir()
    rows = {}
    n = 80000000
    for i, (mode, copies) in enumerate(
        (("0", 1), ("1", 1), ("2", 1), ("2", 2), ("exec", 1), ("thread", 1), ("thread", 2))
    ):
        vals = []
        for j, iterations in enumerate([0, n, 0, n]):
            loc = base / f"{i}-{j}.json"
            subprocess.run(
                [build / "watch", loc, build / "calibrate", mode, str(iterations), str(copies)], check=True
            )
            row = json.loads(loc.read_text())
            need(calibrated(row) and row["code"] == 0, "invalid underlying PMU")
            vals.append(row["instructions"])
        off = statistics.median(vals[1::2]) - statistics.median(vals[::2])
        need(abs(off / (2 * n * copies) - 1) < 0.02, "PMU failed " + mode)
        rows[str(i)] = (mode, copies, vals, off)
    write(base / "results.json", rows)


def metadata_stamp(p):
    with p.open("rb") as f:
        head = f.read(1024)
    need(head[:8] == b"rust\0\0\0\n", "unrecognized Rust metadata " + str(p))
    size = 0
    for i, b in enumerate(head[16:22]):
        size |= (b & 127) << (7 * i)
        if b < 128:
            end = 17 + i + size
            need(0 < size < 900 and end <= len(head), "invalid rustc metadata header")
            return head[17 + i : end].decode()
    raise ValueError("invalid rustc metadata header")


def issuer(root, title):
    out = root / "receipts" / title
    code = out / "issuer.rs"
    code.write_text("pub fn current() -> u8 { 17 }\n")
    meta = out / "issuer.rmeta"
    subprocess.run(
        ["rustc", "+ohm", code, "--crate-type=lib", "--emit=metadata", "-o", meta],
        cwd=root / "ruff",
        env=identity_env(root, title),
        check=True,
    )
    stamp = metadata_stamp(meta)
    write(out / "issuer.json", {"metadata_stamp": stamp, "sha256": sha(meta)})
    return stamp


def physical(d, sdk, cli, executable):
    def identity(p):
        st = p.stat()
        return [st.st_dev, st.st_ino]

    rust = identity(sdk / "bin/rustc")
    cargo = identity(sdk / "bin/cargo")
    wild = identity(sdk / WILD)
    events = []
    compilers = []
    links = []
    others = []
    generators = []
    cargo_calls = []
    for line in (d / "exec.tsv").read_text().splitlines():
        counter, pid, device, inode, selected, image = line.split("\t")
        pid = int(pid)
        ident = [int(device), int(inode)]
        argv = (d / f"args-{int(counter):04d}").read_bytes()
        need(argv[-1:] == b"\0", "truncated kernel argv")
        args = [os.fsdecode(a) for a in argv[:-1].split(b"\0")]
        events.append([pid, ident, image, args])
        img = Path(image)
        if ident == cargo and args[1:] == cli[2:]:
            cargo_calls.append(pid)
        if (
            ident == rust
            and "--crate-name" in args
            and "--out-dir" in args
            and not any(a.startswith("--print") for a in args)
        ):
            name = args[args.index("--crate-name") + 1]
            emission = [a for a in args if a.startswith("--emit=")]
            mode = (
                "link-only"
                if any(a.removeprefix("-Z").split("=", 1)[0] == "link-only" for a in args)
                else "full"
            )
            codegen = {}
            unstable = {}
            for i, item in enumerate(args):
                table = codegen if item.startswith("-C") else (unstable if item.startswith("-Z") else None)
                if table is not None:
                    opt = args[i + 1] if len(item) == 2 and i + 1 < len(args) else item[2:]
                    key, _, value = opt.partition("=")
                    table[key] = value
            compilers.append(
                [
                    pid,
                    name,
                    mode,
                    emission,
                    {
                        "opt_level": codegen.get("opt-level", "0"),
                        "codegen": {
                            k: codegen[k]
                            for k in ("debuginfo", "debug-assertions", "overflow-checks", "panic")
                            if k in codegen
                        },
                        "unstable": {
                            k: unstable[k] for k in ("share-generics", "ub-checks") if k in unstable
                        },
                    },
                ]
            )
        if "--crate-name" in args and "--out-dir" in args and img.name == "rustc" and ident != rust:
            raise RuntimeError("actual compilation used a different compiler binary")
        if (
            img.name in ("ld", "ld.bfd", "ld.gold", "ld.lld", "rust-lld", "lld", "wild", "wild-ld")
            and "-o" in args
        ):
            outputs = [v for k, v in zip(args, args[1:]) if k == "-o"]
            need(len(outputs) == 1, "ambiguous native output")
            p = Path(outputs[0])
            entry = {
                "pid": pid,
                "image": str(img),
                "identity": ident,
                "output": str(p),
                "same_returned_e2e": bool(executable and p.is_file() and p.samefile(executable)),
            }
            if ident == wild:
                links.append(entry)
            else:
                others.append(entry)
        if "unicode_names2" in image and img.name.startswith(("build-script", "build_script")):
            generators.append([pid, image])
    cc = {
        a[0]: list(map(int, a[1:]))
        for line in (d / "counts.tsv").read_text().splitlines()
        if (a := line.split("\t"))
    }
    need(
        len(cargo_calls) == 1 and cc["hits"][0] == 0,
        "missing actual strict Cargo or unexpected selected tracer process",
    )
    return events, {
        "cargo": cargo_calls,
        "compilers": compilers,
        "wild": links,
        "other_links": others,
        "generators": generators,
        "counters": cc,
    }


def elf(root, p):
    raw = sha(p)
    dest = root / "receipts/images"
    dest.mkdir(exist_ok=True)
    image = dest / (raw + ".json")
    if not image.exists():
        with p.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            need(
                m[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", m, 18)[0] == 62,
                "not native x86-64 ELF",
            )
            phoff, shoff = struct.unpack_from("<QQ", m, 32)
            pwidth, pn, swidth, sn, idx = struct.unpack_from("<5H", m, 54)
            need(pwidth == 56 and swidth == 64 and 0 < idx < sn, "invalid ELF tables")
            sections = [struct.unpack_from("<IIQQQQIIQQ", m, shoff + i * swidth) for i in range(sn)]
            strs = sections[idx]
            names = m[strs[4] : strs[4] + strs[5]]
            table = []
            for i, row in enumerate(sections):
                nm = names[row[0] : names.index(0, row[0])].decode(errors="replace")
                off, n = row[4:6]
                need(row[1] == 8 or off + n <= len(m), "ELF section out of range")
                table.append([i, nm, list(row), None if row[1] == 8 else digest(m[off : off + n])])
            segments = []
            for i in range(pn):
                row = struct.unpack_from("<IIQQQQQQ", m, phoff + i * pwidth)
                off, n = row[2], row[5]
                need(off + n <= len(m), "ELF segment out of range")
                segments.append([list(row), digest(m[off : off + n])])
            write(
                image,
                {
                    "sha256": raw,
                    "size": len(m),
                    "header": m[:64].hex(),
                    "sections": table,
                    "segments": segments,
                },
            )
        vault = root / "image-vault"
        vault.mkdir(exist_ok=True)
        # A distinct observer inode avoids turning a Cargo product into a shared writable hardlink.
        subprocess.run(["cp", "--reflink=auto", "--", p, vault / raw], check=True)
        need(sha(vault / raw) == raw, "ELF observation raced")
    return {
        "sha256": raw,
        "size": p.stat().st_size,
        "native_index": str(image.relative_to(root / "receipts")),
    }


def native_reader(root, label, p, mode):
    e = env(root) | {"INSTA_WORKSPACE_ROOT": str(root / "ruff"), "INSTA_UPDATE": "no"}
    loc = root / "receipts" / label
    cwd = root / "ruff/crates/ty_server"

    def run(name, args):
        v = subprocess.run([p, *args], env=e, cwd=cwd, capture_output=True, timeout=300)
        payload(loc / (name + ".stdout.gz"), v.stdout)
        payload(loc / (name + ".stderr.gz"), v.stderr)
        write(loc / (name + ".status.json"), v.returncode)
        return v.returncode, v.stdout

    rc_list, stdout = run("native-list", ["--list", "--format", "terse"])
    entries = [x[:-6] for x in stdout.decode(errors="replace").splitlines() if x.endswith(": test")]
    cases = [n for n in entries if n.endswith("::cells_after_cell_magic")]
    stable = [n for n in entries if n.endswith("::inlay_hints_range_past_end_of_cell")]
    valid_inventory = rc_list == 0 and len(set(entries)) == len(entries) > 100 and len(stable) == 1
    tests = {}
    for name in [*stable, *cases]:
        rc, value = run("native-" + name.split("::")[-1], ["--exact", name, "--test-threads=1"])
        ret = {
            "code": rc,
            "one_named": ("test " + name + " ... ok").encode() in value and b"1 passed; 0 failed" in value,
        }
        tests[name] = ret
    inventory = sorted(entries)
    write(loc / "actual-test-names.json", inventory)
    return {
        "list_sha": digest(stdout),
        "names": inventory,
        "new_cases": cases,
        "list_exit": rc_list,
        "valid_inventory": valid_inventory,
        "stable_cases": stable,
        "runtime": tests,
        "elf": elf(root, p),
    }


def workspace_product(root, raw, loc):
    slot = root / "slot"
    refs = {}
    paths = {}
    generators = {}
    workdir = str(root / "ruff/crates/")
    for row in raw:
        if row["reason"] == "build-script-executed" and "/crates/ruff_unicode_names2#" in row["package_id"]:
            out = Path(row["out_dir"])
            need(out.is_relative_to(slot), "generator output outside target/shared")
            for name in GEN:
                p = out / name
                if p.is_file():
                    h = sha(p)
                    generators[name] = h
                    directory = root / "receipts/generated"
                    directory.mkdir(exist_ok=True)
                    sample = directory / (h + ".gz")
                    if not sample.exists():
                        payload(sample, p.read_bytes())
        if row["reason"] != "compiler-artifact" or not row["target"]["src_path"].startswith(workdir):
            continue
        for name in row["filenames"]:
            p = Path(name)
            if p.suffix != ".rmeta" or not p.is_file():
                continue
            need(p.is_relative_to(slot), "returned metadata outside owned target/shared")
            key = json.dumps(
                [
                    str(Path(row["target"]["src_path"]).relative_to(root / "ruff")),
                    row["target"]["kind"],
                    row["profile"]["test"],
                    p.name,
                ],
                separators=(",", ":"),
            )
            paths[key] = p
            h = sha(p)
            size = p.stat().st_size
            refs[key] = {"stamp": metadata_stamp(p) if size else None, "size": size, "sha256": h}
            if size:
                with p.open("rb") as f:
                    prefix = f.read(1024)
                directory = root / "receipts/rmeta-headers"
                directory.mkdir(exist_ok=True)
                sample = directory / (h + ".bin")
                if not sample.exists():
                    sample.write_bytes(prefix)
                need(sample.read_bytes() == prefix, "metadata changed while retaining its envelope")
    write(loc / "workspace-rmeta.json", refs)
    return refs, generators, paths


def confirm_stale(root, label, refs, stale, paths):
    """Retain actual old metadata and let the installed rustc decide independently of Cargo."""
    chosen = sorted(
        stale, key=lambda k: (not ("crates/ty_project/" in k), not ("crates/ruff_unicode_names2/" in k), k)
    )[:2]
    directory = root / "receipts/stale-rmeta"
    directory.mkdir(exist_ok=True)
    out = {}
    for idx, k in enumerate(chosen):
        p = paths[k]
        h = refs[k]["sha256"]
        z = directory / (h + ".rmeta.zst")
        if not z.exists():
            subprocess.run(["zstd", "-q", "-T2", "-3", "-o", z, p], check=True)
        loc = root / "receipts" / label / ("installed-reader-" + str(idx))
        loc.mkdir()
        src = loc / "reader.rs"
        src.write_text("extern crate retained; pub fn read() {}\n")
        dest = loc / "reader.rmeta"
        argv = [
            "rustc",
            "+ohm",
            src,
            "--crate-type=lib",
            "--extern",
            "retained=" + str(p),
            "-Ldependency=" + str(p.parent),
            "--emit=metadata",
            "--error-format=json",
            "-o",
            dest,
        ]
        proc = subprocess.run(argv, cwd=loc, env=identity_env(root, label + "/retained"), capture_output=True)
        payload(loc / "stdout.gz", proc.stdout)
        payload(loc / "stderr.gz", proc.stderr)
        errors = [
            j
            for line in proc.stderr.splitlines()
            if line.startswith(b"{") and (j := json.loads(line)).get("level") == "error"
        ]
        codes = [j["code"]["code"] for j in errors if j.get("code")]
        out[k] = {
            "sha256": h,
            "argv": list(map(str, argv)),
            "status": proc.returncode,
            "written": dest.exists(),
            "diagnostics": codes,
        }
        write(loc / "verdict.json", out[k])
    return out
