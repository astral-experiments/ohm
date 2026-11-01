"""Exercise a real rustc cache loader with independent same-path sessions and native outputs."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

END = b"rust-end-file"
A = 'fn main() { let unused = 1; println!("17"); }\n'
B = A.replace("17", "83")
INVALID = 'fn main() { let _: u32 = "wrong"; }\n'
WARN = "corrupt incremental compilation artifact"


def need(test, message):
    if not test:
        raise ValueError(message)


def digest(b):
    return hashlib.sha256(b).hexdigest()


def graph_row(data, pos):
    flags, index = struct.unpack_from("<HI", data, pos)
    width = 1 + ((flags >> 9) & 3)
    count = flags >> 11
    cursor = pos + 38
    if count:
        edges = count - 1
    else:
        edges = 0
        shift = 0
        while True:
            value = data[cursor]
            cursor += 1
            edges |= (value & 127) << shift
            if value < 128:
                break
            shift += 7
            need(shift <= 63, "unbounded edge count")
    return index, cursor + width * edges


def rewrite(path, raw):
    path.unlink()
    path.write_bytes(raw)


def one(root, name):
    paths = list(root.rglob(name))
    need(len(paths) == 1, (root, name, paths))
    return paths[0]


def damage(path, how):
    old = path.read_bytes()
    buf = bytearray(old)
    need(buf.startswith(b"RSIC") and buf.endswith(END), "invalid base artifact")
    start = 7 + buf[6] + 8
    before = None
    if how == "trailer":
        buf[-1] ^= 1
    elif how == "cache-footer":
        buf[-len(END) - 8 : -len(END)] = b"\xff" * 8
    else:
        space = struct.unpack_from("<Q", buf, len(buf) - len(END) - 24)[0]
        idx, p = graph_row(buf, start)
        later, q = graph_row(buf, p)
        before = [idx, later]
        if how == "reordered":
            need(
                {idx, later} == {0, 1} and buf[-len(END) - 32 : -len(END) - 24] != b"OHMIDX01",
                "control requires both reserved rows adjacent and no seek map",
            )
            buf[start:q] = old[p:q] + old[start:p]
            need(graph_row(buf, start)[0] == later, "control did not exchange complete records")
        elif how == "null":
            struct.pack_into("<H", buf, start, 0)
        elif how == "duplicate":
            struct.pack_into("<I", buf, start + 2, int(idx == 0))
        elif how == "range":
            need(space < 0x3FFF_FFFF, "recorded bound exceeded by fixture")
            struct.pack_into("<I", buf, start + 2, 0x3FFF_FFFF)
        else:
            raise ValueError(how)
    need(buf != old, "damage unchanged")
    rewrite(path, buf)
    return {
        "path": path.name,
        "cause": how,
        "before": digest(old),
        "after": digest(buf),
        "first_physical_indices": before,
        "bytes": len(buf),
    }


def main(a):
    root, out = a.work.resolve(), a.out.resolve()
    root.mkdir()
    out.mkdir()
    env = {
        **os.environ,
        "TMPDIR": str(root),
        "LC_ALL": "C",
        "RUST_BACKTRACE": "0",
        "LLVM_PROFILE_FILE": str(root / "diagnostic-%m.profraw"),
    }

    def file_sha(p):
        with p.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    def tools(sdk, compiler, commit):
        lib = Path(sdk).resolve(strict=True)
        (driver,) = [p for p in (lib / "lib").glob("*rustc_driver*") if p.is_file()]
        command = [str(compiler), *a.prefix]
        vv = subprocess.check_output([*command, "-vV"], env=env).decode()
        need(f"commit-hash: {commit}\n" in vv, "wrong compiler revision")
        sysroot = Path(
            subprocess.check_output([*command, "--print", "sysroot"], env=env, text=True).strip()
        ).resolve()
        need(sysroot == lib, "compiler resolved a different SDK")
        need(a.prefix == ["+ohm"] or Path(compiler).samefile(lib / "bin/rustc"), "foreign compiler")
        return command, {
            "rustc": str((lib / "bin/rustc").resolve()),
            "vV": vv,
            "command": command,
            "sysroot": str(sysroot),
            "rustc_sha256": file_sha(lib / "bin/rustc"),
            "driver": str(driver),
            "driver_sha256": file_sha(driver),
        }

    rustc, target_tools = tools(a.sdk, a.compiler, a.commit)
    need((a.producer_sdk is None) == (a.producer_commit is None), "incomplete producer enrollment")
    producer, producer_tools = rustc, target_tools
    if a.producer_sdk:
        need(a.mode == "candidate" and not a.prefix, "mixed run requires physical candidate tools")
        producer, producer_tools = tools(
            a.producer_sdk, Path(a.producer_sdk) / "bin/rustc", a.producer_commit
        )
        need(target_tools["driver_sha256"] != producer_tools["driver_sha256"], "same driver in both roles")
        # rustc-perf uses this matching stamp on its incremental compiler invocations.
        env.update(
            RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER="rustc-perf", RUSTC_FORCE_RUSTC_VERSION="rustc-perf"
        )
    meta = {
        "mode": a.mode,
        "consumer": target_tools,
        "producer": producer_tools,
        "forced_collector_stamp": bool(a.producer_sdk),
        "sources": {"A": A, "B": B, "invalid": INVALID},
        "steps": [],
    }
    visible = root / "mixed-sysroot"
    previous_role = None

    def sysroot_for(old):
        nonlocal previous_role
        if not a.producer_sdk or previous_role == old:
            return
        visible.mkdir(exist_ok=True)
        # Use one actual directory for search-path fingerprinting. Each compiler must still
        # read its own standard library, including the embedded producer-version metadata.
        for name in visible.rglob("*"):
            if name.is_symlink():
                name.unlink()
        physical = Path(a.producer_sdk if old else a.sdk).resolve(strict=True)
        files = 0
        for source in sorted(physical.rglob("*")):
            path = source.relative_to(physical)
            if path.parts[:3] == ("lib", "rustlib", "src"):
                continue
            dest = visible / path
            if source.is_dir():
                dest.mkdir(exist_ok=True)
            elif source.is_file():
                dest.symlink_to(source.resolve(strict=True))
                need(dest.samefile(source), "mixed sysroot points at a different file")
                files += 1
        need(files > 20, "missing native sysroot")
        meta.setdefault("role_changes", []).append(
            {
                "producer": old,
                "physical": str(physical),
                "aliased_files": files,
                "path": str(visible),
                "device": visible.stat().st_dev,
                "inode": visible.stat().st_ino,
            }
        )
        previous_role = old

    def write():
        (out / "native.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")

    work = root / "inc"
    work.mkdir()
    saved = root / "saved"
    saved.mkdir()

    def reset(seed=None):
        need(work == root / "inc" and work.is_dir() and not work.is_symlink(), "unowned intervention path")
        shutil.rmtree(work)
        if seed:
            shutil.copytree(saved / seed, work)
        else:
            work.mkdir()

    def snapshot(name):
        shutil.copytree(work, saved / name)
        for p in work.rglob("*.bin"):
            copy = saved / name / p.relative_to(work)
            need(not p.samefile(copy) and file_sha(p) == file_sha(copy), "dependent cache clone")

    bodies = out / "bodies"
    bodies.mkdir()

    def retain(data):
        p = bodies / (digest(data) + ".gz")
        if not p.exists():
            p.write_bytes(gzip.compress(data, compresslevel=6, mtime=0))
        need(gzip.decompress(p.read_bytes()) == data, "retained cache bytes changed")

    def mutate(p, label):
        retain(p.read_bytes())
        result = damage(p, label)
        retain(p.read_bytes())
        return result

    def visit(name, source, state, *, stage=False, emit="link", outcome="ok", target=None, write_old=False):
        (root / "input.rs").write_text(source)
        exe = root / "slot_probe"
        exe.unlink(missing_ok=True)
        args = [
            *(producer if write_old else rustc),
            "--crate-name",
            "slot_probe",
            str(root / "input.rs"),
            "-Cstrip=symbols",
            "--out-dir",
            str(root),
            "-Cincremental=" + str(work),
            "--emit=" + emit,
            "-Zassert-incr-state=" + state,
            "-Zincremental-verify-ich",
        ]
        if a.producer_sdk:
            sysroot_for(write_old)
            args += ["--sysroot", str(visible)]
        if stage:
            args += ["-Zohm-shared-stages"]
        proc = subprocess.run(args, cwd=root, env=env, capture_output=True, timeout=60)
        err = proc.stderr.decode(errors="replace")
        (out / (name + ".stderr")).write_bytes(proc.stderr)
        (out / (name + ".stdout")).write_bytes(proc.stdout)
        row = {
            "name": name,
            "argv": args,
            "code": proc.returncode,
            "stderr_sha256": digest(proc.stderr),
            "stdout_sha256": digest(proc.stdout),
            "source_sha256": digest(source.encode()),
            "outcome": outcome,
            "corrupt_warnings": err.count(WARN),
        }
        meta["steps"].append(row)
        write()
        if outcome == "ok":
            need(proc.returncode == 0 and "unused variable: `unused`" in err, (name, err))
            if emit == "link":
                native = subprocess.run([str(exe)], capture_output=True, timeout=5)
                need(
                    native.returncode == 0 and native.stdout == target and not native.stderr, (name, native)
                )
                sha = file_sha(exe)
                row.update(elf=sha, native=native.stdout.decode(), bytes=exe.stat().st_size)
                product = out / (sha + ".native")
                if not product.exists():
                    shutil.copy2(exe, product)
                need(file_sha(product) == sha, "duplicate native blob differs")
        elif outcome == "unloaded":
            need(
                proc.returncode == 1
                and "should be successfully loaded, but it was not" in err
                and "internal compiler error" not in err
                and not exe.exists(),
                (name, err),
            )
        elif outcome == "type":
            need(
                proc.returncode == 1
                and "error[E0308]" in err
                and "internal compiler error" not in err
                and not exe.exists(),
                (name, err),
            )
        else:
            wanted = "serialized.rs:382" if outcome == "ice-slot" else "index out of bounds"
            need(
                proc.returncode == 101
                and wanted in err
                and "the compiler unexpectedly panicked" in err
                and not exe.exists(),
                (name, err),
            )
            if outcome == "ice-range":
                need("serialized.rs:382" not in err, "masked out-of-bounds refusal")
        write()
        return row

    def poison_objects():
        objects = list(work.rglob("*.o"))
        need(objects, "no native work products on disk")
        rows = []
        for p in objects:
            rows.append([str(p.relative_to(work)), file_sha(p)])
            retain(p.read_bytes())
            rewrite(p, b"unusable native object")
        return rows

    cold = visit("cold-A", A, "not-loaded", target=b"17\n")
    if a.producer_sdk:
        reset()
        visit("producer-cold-A", A, "not-loaded", target=b"17\n", write_old=True)
    snapshot("A")
    reset()
    clean = visit("empty-B", B, "not-loaded", target=b"83\n")
    reset()
    error = visit("empty-invalid", INVALID, "not-loaded", outcome="type")
    reset("A")
    reordered = mutate(one(work, "dep-graph.bin"), "reordered")
    snapshot("reordered")
    valid = visit("loaded-reordered-A", A, "loaded", target=b"17\n")
    need(cold["elf"] == valid["elf"], "valid reordering changed native output")
    meta["reordered"] = reordered
    controls = {}
    for kind in ("null", "duplicate", "range", "trailer"):
        reset("reordered")
        mods = [
            mutate(one(work, "dep-graph.bin"), kind),
            mutate(one(work, "query-cache.bin"), "cache-footer"),
        ]
        obs = poison_objects()
        snapshot("bad-" + kind)
        native_parent_ice = a.mode == "parent" and kind != "trailer"
        if native_parent_ice:
            result = visit(
                kind + "-parent", B, "loaded", outcome="ice-range" if kind == "range" else "ice-slot"
            )
            controls[kind] = {
                "mutations": mods,
                "unusable_workproducts": obs,
                "parent_verdict": result["outcome"],
            }
            continue
        assertion = visit(kind + "-require-loaded", B, "loaded", outcome="unloaded")
        if kind != "trailer":
            need(assertion["corrupt_warnings"] >= 1, "absent targeted corruption warning")
        reset("bad-" + kind)
        wrong = visit(kind + "-invalid", INVALID, "not-loaded", outcome="type")
        raw = (out / (wrong["name"] + ".stderr")).read_text()

        def source_error(text):
            return text[text.index("error[E0308]") : text.index("\nerror: aborting due to")]

        need(
            source_error(raw) == source_error((out / (error["name"] + ".stderr")).read_text()),
            "different source diagnostic",
        )
        reset("bad-" + kind)
        fixed = visit(kind + "-repair-B", B, "not-loaded", target=b"83\n")
        warm = visit(kind + "-loaded-B", B, "loaded", target=b"83\n")
        need(
            fixed["elf"] == warm["elf"] == clean["elf"], "stale native work product or changed clean bytes"
        )
        controls[kind] = {"mutations": mods, "unusable_workproducts": obs, "recovery_elf": fixed["elf"]}
    meta["ordinary"] = controls
    reset()
    visit("stage-build-A", A, "not-loaded", stage=True, target=b"17\n", write_old=True)
    visit("stage-check-A", A, "loaded", stage=True, emit="metadata", write_old=True)
    snapshot("stage")
    cases = {}
    for label, bad_stage, bad_canonical in [
        ("stage-only", True, False),
        ("canonical-only", False, True),
        ("both", True, True),
    ]:
        reset("stage")
        changes = []
        if bad_stage:
            changes.append(
                mutate(
                    one(work, "ohm-build-dep-graph.bin"),
                    "duplicate" if a.mode == "candidate" else "trailer",
                )
            )
            changes.append(mutate(one(work, "ohm-build-query-cache.bin"), "cache-footer"))
        if bad_canonical:
            changes.append(
                mutate(
                    one(work, "dep-graph.bin"),
                    "null" if not bad_stage or a.mode == "candidate" else "trailer",
                )
            )
            canonical_cache = one(work, "query-cache.bin")
            changes.append({"removed": "query-cache.bin", "sha": file_sha(canonical_cache)})
            retain(canonical_cache.read_bytes())
            canonical_cache.unlink()
        cold = bad_stage and bad_canonical
        if cold:
            changes.append({"unusable_workproducts": poison_objects()})
        repaired = visit(
            label + "-repair-B", B, "not-loaded" if cold else "loaded", stage=True, target=b"83\n"
        )
        unchanged = visit(label + "-loaded-B", B, "loaded", stage=True, target=b"83\n")
        need(
            repaired["elf"] == unchanged["elf"] == clean["elf"], "shared-stage recovery differs from empty"
        )
        if a.mode == "candidate":
            need(repaired["corrupt_warnings"] == int(bad_stage) + int(cold), "wrong graph selected")
        cases[label] = changes
    meta["stage"] = cases
    meta["complete"] = True
    write()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("compiler", "sdk", "commit"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--producer-sdk")
    parser.add_argument("--producer-commit")
    parser.add_argument("--mode", choices=["parent", "candidate"], required=True)
    parser.add_argument("--prefix", action="append", default=[])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    main(parser.parse_args())
