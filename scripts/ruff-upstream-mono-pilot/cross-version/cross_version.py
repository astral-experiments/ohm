"""Exercise a real incremental RSIC donor across two matched compiler versions on Linux."""
import argparse
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
GIB = 1 << 30
RSIC = ("dep-graph.bin", "work-products.bin", "query-cache.bin")
CASES = (("base", 17), ("changed", 29), ("invalid", None), ("repair", 41))
ACTIVE_DRIVER = None

def need(value, reason):
    if not value:
        raise RuntimeError(reason)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")

def fresh(path):
    if path.exists():
        need(path.is_dir() and not path.is_symlink() and not any(path.iterdir()), f"need empty private directory: {path}")
    else:
        path.mkdir(parents=True)

def spare():
    physical = int(next(l for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemAvailable:")).split()[1]) * 1024
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        group, controller, rel = line.split(":", 2)
        if group == "0" and not controller:
            root = Path("/sys/fs/cgroup")
            limit, usage = "memory.max", "memory.current"
        elif "memory" in controller.split(","):
            root = Path("/sys/fs/cgroup/memory")
            limit, usage = "memory.limit_in_bytes", "memory.usage_in_bytes"
        else:
            continue
        current = (root / rel.lstrip("/")).resolve()
        for p in (current, *current.parents):
            if p != root and root not in p.parents:
                continue
            if (p / limit).is_file() and (p / usage).is_file():
                cap = (p / limit).read_text().strip()
                if cap != "max":
                    physical = min(physical, int(cap) - int((p / usage).read_text().strip()))
    return physical

def elf_build_id(path):
    """Return the file offset and exact immutable GNU build-ID note from ELF64."""
    notes = []
    with path.open("rb") as f:
        head = f.read(64)
        need(head[:6] == b"\x7fELF\x02\x01", "expected little-endian ELF64 driver")
        phoff = struct.unpack_from("<Q", head, 32)[0]
        stride, count = struct.unpack_from("<HH", head, 54)
        need(stride == 56 and 0 < count < 256, "invalid ELF program header table")
        f.seek(phoff)
        headers = f.read(stride * count)
        for i in range(count):
            kind, _, offset, _, _, size, _, _ = struct.unpack_from("<IIQQQQQQ", headers, i*stride)
            if kind != 4:
                continue
            need(size < 1 << 20, "oversized ELF notes")
            f.seek(offset)
            data, pos = f.read(size), 0
            while pos + 12 <= len(data):
                n, d, typ = struct.unpack_from("<III", data, pos)
                pos += 12
                label = data[pos:pos+n]
                pos += (n+3) & ~3
                need(pos+d <= len(data), "truncated ELF note")
                if label == b"GNU\0" and typ == 3:
                    need(8 <= d <= 64, "invalid GNU build ID")
                    notes.append({"offset": offset+pos, "hex": data[pos:pos+d].hex()})
                pos += (d+3) & ~3
    need(len(notes) == 1, "expected exactly one loadable driver build ID")
    return notes[0]


class DriverRefusal(RuntimeError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = {"error": message, **evidence}


def verify_mapping(proc, rows, active):
    # Only path-backed driver DSOs are executable identities. Anonymous BSS and debug sidecars
    # may include the same file name. On a layered filesystem /proc/maps can name a backing inode.
    candidates = {}
    ignored = []
    for row in rows:
        c = row.split(None, 5)
        if len(c) != 6 or b"librustc_driver" not in c[5].split(b"/")[-1]:
            continue
        name = os.fsdecode(c[5])
        part = name.removesuffix(" (deleted)").rsplit("/", 1)[-1]
        if not name.startswith("/") or int(c[4]) == 0 or not re.fullmatch(r"librustc_driver[^/]*\.so(?:\.\d+)*", part):
            ignored.append(name)
            continue
        major, minor = (int(v, 16) for v in c[3].split(b":"))
        file_id = os.makedev(major, minor), int(c[4])
        lo, hi = (int(v,16) for v in c[0].split(b"-"))
        candidates.setdefault((name, file_id), []).append((lo, hi, int(c[2],16), c[1]))
    if not candidates:
        return None
    evidence = {"pid": int(proc.name), "registered_sha256": active["sha256"], "registered_path": active["path"], "registered_inode": list(active["inode"]), "expected_build_id": active["note"], "ignored_side_mappings": sorted(set(ignored)), "file_mappings": []}
    def refuse(message):
        raise DriverRefusal(message, evidence)
    note = active["note"]
    expected = bytes.fromhex(note["hex"])
    seen = False
    for (name, reported), mappings in candidates.items():
        contact = {"path": name, "maps_inode": list(reported)}
        evidence["file_mappings"].append(contact)
        if name.endswith(" (deleted)"):
            refuse("rustc mapped a deleted compiler driver")
        st = (proc / "root" / name.lstrip("/")).stat()
        physical = st.st_dev, st.st_ino
        contact["resolved_inode"] = list(physical)
        if physical != active["inode"]:
            refuse("mapped compiler driver path resolves to a different file")
        note_address = next((lo + note["offset"] - off for lo, hi, off, perms in mappings if perms.startswith(b"r") and off <= note["offset"] and note["offset"]+len(expected) <= off+hi-lo), None)
        if note_address is None:
            return None
        try:
            fd = os.open(proc/"mem", os.O_RDONLY | os.O_CLOEXEC)
            try:
                actual = os.pread(fd, len(expected), note_address)
            finally:
                os.close(fd)
        except PermissionError as error:
            contact["memory_errno"] = error.errno
            if reported != active["inode"]:
                refuse("cannot establish the backing-file identity without its mapped ELF note")
            contact["method"] = "kernel-file-id-and-resolved-file"
        else:
            if len(actual) != len(expected):
                return None
            contact["mapped_build_id"] = actual.hex()
            if actual != expected:
                refuse("mapped compiler ELF build ID differs from the SHA-bound role")
            contact["method"] = "mapped-elf-build-id-and-resolved-file"
        seen = True
    return evidence if seen else None


def mapped_driver(pid):
    """Read the ELF identity of the launched rustc, without inspecting its environment."""
    pending, seen = [pid], set()
    while pending:
        child = pending.pop()
        if child in seen:
            continue
        seen.add(child)
        proc = Path("/proc") / str(child)
        try:
            pending.extend(int(p) for p in (proc / "task" / str(child) / "children").read_text().split())
            st = (proc / "exe").stat()
            if (st.st_dev, st.st_ino) != ACTIVE_DRIVER["executable"]:
                continue
            evidence = verify_mapping(proc, (proc/"maps").read_bytes().splitlines(), ACTIVE_DRIVER)
            if evidence:
                return evidence
        except (FileNotFoundError, ProcessLookupError):
            continue
    return None

def invoke(argv, env, cwd, receipt):
    deadline = time.monotonic() + 120
    while spare() < 8.5 * GIB:
        need(time.monotonic() < deadline, "insufficient compiler admission headroom")
        time.sleep(2)
    need(min(shutil.disk_usage(cwd).free, shutil.disk_usage(receipt).free) >= GIB, "less than 1 GiB spare disk")
    low = spare()
    mapped = None
    with (receipt / "stdout").open("wb") as o, (receipt / "stderr").open("wb") as e:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=o, stderr=e, start_new_session=True)
        t = time.monotonic()
        try:
            while p.poll() is None:
                if mapped is None:
                    try:
                        mapped = mapped_driver(p.pid)
                    except DriverRefusal as refusal:
                        save(receipt / "driver-mapping-refusal.json", refusal.evidence)
                        raise
                low = min(low, spare())
                need(low >= 8 * GIB and time.monotonic() - t < 120, "compiler crossed its private time/memory limit")
                time.sleep(.012 if mapped is None else .04)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
    return {"argv": argv, "returncode": p.returncode, "min_available_bytes": low, "mapped_driver": mapped}

def role_receipts(args):
    zipped = args.factory_receipts
    need(zipped.stat().st_size < 2 << 20 and file_sha(zipped) == args.expect_factory_sha256, "factory ZIP does not match the external registration")
    with zipfile.ZipFile(zipped) as z:
        names = ("P.json", "C.json", "registration.json", "rustcs.json")
        need(all(z.namelist().count(n) == 1 and z.getinfo(n).file_size < 1 << 20 for n in names), "invalid factory receipt inventory")
        raw = {n: z.read(n) for n in names}
    observed = {n: sha(b) for n, b in raw.items()}
    reg, builds = (json.loads(raw[n]) for n in ("registration.json", "rustcs.json"))
    need("rust.omit-git-hash=true" in reg["bootstrap_flags"], "these are not matched hash-omitted factory builds")
    result = {}
    for role, arm, sdk, commit, fmt in (("P", "normal", args.parent_sdk, args.parent_commit, args.parent_format), ("C", "defer", args.child_sdk, args.child_commit, args.child_format)):
        m = json.loads(raw[role + ".json"])
        need(m["role"] == role and m["commit"] == reg["roles"][role]["revision"] == commit and m["compiler_tree"] == reg["roles"][role]["compiler"], "factory role or compiler source mismatch")
        sdk = sdk.resolve(strict=True)
        name, = [n for n in m["files"] if n.startswith("lib/librustc_driver") and n.endswith(".so")]
        f = builds["arms"][arm]["files"]
        physical = {n: file_sha(sdk / n) for n in ("bin/rustc", "bin/cargo", name)}
        need(all(physical[n] == f[n] for n in physical) and physical[name] == m["files"][name][0] and (sdk / name).stat().st_size == m["files"][name][1], "installed factory driver does not match its role")
        need(physical["bin/rustc"] == m["files"]["bin/rustc"][0] and physical["bin/cargo"] == reg["signed_cargo"]["members"]["bin/cargo"][3], "installed SDK binary differs from factory receipt")
        result[role] = {"sdk": str(sdk), "commit": commit, "expected_format": fmt, "driver": physical[name], "binaries": physical, "factory_member_sha256": observed}
    need(result["P"]["driver"] != result["C"]["driver"], "cross-version test needs two distinct installed drivers")
    return result

class Watch:
    """Attach to the previous files' real inodes before launching the receiving rustc."""
    mask = 0x1 | 0x4 | 0x10 | 0x20 | 0x400 | 0x800
    def __init__(self, paths):
        libc = ctypes.CDLL(None, use_errno=True)
        self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        need(self.fd >= 0, f"inotify initialization failed: {ctypes.get_errno()}")
        self.names = {}
        for n, p in paths.items():
            wd = libc.inotify_add_watch(self.fd, os.fsencode(p), self.mask)
            need(wd >= 0, f"cannot watch {n}: {ctypes.get_errno()}")
            self.names.setdefault(wd, []).append(n)

    def finish(self):
        events = {n: [] for names in self.names.values() for n in names}
        try:
            while True:
                try:
                    data = os.read(self.fd, 65536)
                except BlockingIOError:
                    break
                pos = 0
                while pos < len(data):
                    wd, mask, _, length = struct.unpack_from("=iIII", data, pos)
                    need(wd in self.names and not mask & 0x4000, "unknown inotify source or queue overflow")
                    for n in self.names[wd]:
                        events[n].append(mask)
                    pos += 16 + length
                need(pos == len(data), "partial inotify event")
        finally:
            os.close(self.fd)
        return events

def header(path):
    with path.open("rb") as f:
        fixed = f.read(7)
        need(len(fixed) == 7 and fixed[:4] == b"RSIC", f"invalid RSIC magic: {path}")
        name = f.read(fixed[6])
        need(len(name) == fixed[6] and name, "truncated compiler identity")
    return {"format": int.from_bytes(fixed[4:6], "little"), "compiler_label": name.decode(), "raw_header_hex": (fixed + name).hex(), "bytes": path.stat().st_size, "sha256": file_sha(path), "inode": [path.stat().st_dev, path.stat().st_ino]}

def sessions(work):
    return {p.parent for p in (work / "inc/client").glob("cross_client-*/s-*/dep-graph.bin") if not p.parent.name.endswith("-working")}

def snapshot(session, out, expected, keep):
    values = {n: header(session / n) for n in RSIC}
    need(all(v["format"] == expected for v in values.values()) and len({v["compiler_label"] for v in values.values()}) == 1, "real RSIC file format differs from registration")
    if keep:
        raw = out / "raw-rsic"
        raw.mkdir()
        for n in RSIC:
            path = session / n
            need(path.stat().st_size < 32 << 20, "unexpected private incremental file size")
            (raw / (n + ".gz")).write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    native = {}
    witness = {"generic": [], "drop": []}
    for p in sorted(session.glob("*.o")):
        info = p.stat()
        native[p.name] = {"sha256": file_sha(p), "bytes": info.st_size, "inode": [info.st_dev, info.st_ino]}
        section = None
        for line in subprocess.check_output(["readelf", "-Wr", p], text=True).splitlines():
            if line.startswith("Relocation section '"):
                section = line.split("'", 2)[1]
                continue
            if not section or not section.startswith((".rela.text", ".rela.data.rel.ro")):
                continue
            fields = line.split()
            if len(fields) < 5 or not fields[2].startswith("R_"):
                continue
            symbol = fields[4]
            if not symbol.startswith("_R") or not all(k in symbol for k in ("cross_api", "cross_provider")):
                continue
            tag = "generic" if "measure" in symbol else "drop" if all(k in symbol for k in ("drop_glue","Envelope","Recorded")) else None
            if tag:
                witness[tag].append(dict(file=p.name, section=section, symbol=symbol, relocation=fields[2], offset=fields[0]))
    need(native and all(witness.values()), "missing genuine upstream generic/drop machine relocations")
    return {"crate_directory": session.parent.name, "session": session.name, "rsic": values, "native": native, "provider_relocations": witness}

def switch(work, env, role):
    global ACTIVE_DRIVER
    tool = work / "rustup/toolchains/ohm"
    new = tool.with_name("next-ohm")
    new.symlink_to(role["sdk"])
    new.replace(tool)
    path = subprocess.check_output(["rustup", "which", "--toolchain", "ohm", "rustc"], env=env, text=True).strip()
    need(Path(path).resolve() == (Path(role["sdk"]) / "bin/rustc").resolve(), "private toolchain switch failed")
    r = Path(role["sdk"])
    dso, = (r / "lib").glob("librustc_driver*.so")
    a, b = (r / "bin/rustc").stat(), dso.stat()
    ACTIVE_DRIVER = {"executable": (a.st_dev, a.st_ino), "inode": (b.st_dev, b.st_ino), "path": str(dso.resolve(strict=True)), "sha256": role["driver"], "note": role["elf_build_id"]}
    return subprocess.check_output(["rustc", "+ohm", "-vV"], env=env, text=True)

def reset(work):
    for name in ("inc", "deps", "bin", "tmp"):
        p = work / name
        need(not p.is_symlink(), "refusing nonprivate cache")
        if p.exists():
            shutil.rmtree(p)
        p.mkdir()

def compiler(work, crate):
    name = "cross_" + crate
    typ = "bin" if crate == "client" else "rlib"
    src = "main.rs" if crate == "client" else crate + ".rs"
    output = (work / "bin/cross_client") if crate == "client" else (work / "deps" / ("lib" + name + ".rlib"))
    args = ["rustc", "+ohm", "--edition=2021", "--crate-name", name, "--crate-type", typ, "--error-format=json", "-Copt-level=1", "-Cdebuginfo=line-tables-only", "-Cmetadata=ohm_crossover_01", "-Cincremental=" + str(work / "inc" / crate)]
    for dep in (("api", "provider") if crate == "client" else ("api",) if crate == "provider" else ()):
        args += ["--extern", "cross_" + dep + "=" + str(work / "deps" / ("libcross_" + dep + ".rlib"))]
    return args + ["-Ldependency=" + str(work / "deps"), str(work / "src" / src), "-o", str(output)]

def dependencies(env, work, out):
    for name in ("api", "provider"):
        d = out / name
        d.mkdir()
        result = invoke(compiler(work, name), env, work / "src", d)
        save(d / "command.json", result)
        need(result["returncode"] == 0, f"clean dependency {name} failed")
    return {p.name: file_sha(p) for p in sorted((work / "deps").glob("*.rlib"))}

def edit_source(work, number):
    s = (HERE / "main.rs").read_text()
    needle = "const REVISION: u32 = 17;"
    need(s.count(needle) == 1, "missing semantic edit location")
    replacement = 'const REVISION: u32 = "invalid";' if number is None else f"const REVISION: u32 = {number};"
    path = work / "src/main.rs"
    updated = s.replace(needle, replacement)
    if not path.exists() or path.read_text() != updated:
        path.write_text(updated)

def compile_client(env, work, out, role, number, previous=None, keep=False):
    edit_source(work, number)
    prior = sessions(work)
    watcher = Watch({n: previous / n for n in RSIC}) if previous else None
    try:
        run = invoke(compiler(work, "client"), env, work / "src", out)
    finally:
        events = watcher.finish() if watcher else None
    if events:
        save(out / "donor-inotify.json", events)
    raw = (out / "stderr").read_bytes()
    diagnostics = []
    for line in raw.splitlines():
        if line.startswith(b"{"):
            record = json.loads(line)
            if record.get("level") == "error" and record.get("code"):
                diagnostics.append(record["code"]["code"])
    opened = None if events is None else all(any(mask & 0x21 for mask in events[n]) for n in ("dep-graph.bin", "work-products.bin"))
    facts = {"run": run, "diagnostics": diagnostics, "source": file_sha(work / "src/main.rs"), "donor_events": events, "prior_graph_and_products_opened": opened}
    save(out / "command.json", facts)
    need(opened is not False, "no genuine donor graph/product open was observed")
    need(run["returncode"] >= 0 and not any(m in raw.lower() for m in (b"internal compiler error", b"the compiler unexpectedly panicked", b"thread 'rustc' panicked", b"segmentation fault")), "receiving compiler crashed")
    need(run["mapped_driver"] and run["mapped_driver"]["registered_sha256"] == role["driver"], "could not observe the real client compiler mapping")
    if number is None:
        need(run["returncode"] == 1 and diagnostics == ["E0308"], "invalid source did not produce E0308")
        leftover = work / "bin/cross_client"
        facts["old_output_still_present"] = file_sha(leftover) if leftover.is_file() else None
        save(out / "result.json", facts)
        return facts, None
    need(run["returncode"] == 0 and not diagnostics, "valid source failed")
    binary = work / "bin/cross_client"
    facts["output"] = {}
    for x in (2, 17):
        got = subprocess.check_output([binary, str(x)], env=env, timeout=10).decode().strip()
        need(got == f"{x*3+4+11+number} {x+1}", f"stale semantic verdict: {got}")
        facts["output"][str(x)] = got
    facts["executable_sha256"] = file_sha(binary)
    new = sessions(work) - prior
    need(len(new) == 1, "did not find one new finalized compiler session")
    session = new.pop()
    facts.update(snapshot(session, out, role["expected_format"], keep))
    if previous:
        need(session.parent == previous.parent, "receiving rustc selected a different crate cache")
    save(out / "result.json", facts)
    return facts, session

def carry(source, destination, old, work, env, out, mode):
    """Hold the actual old objects alive, so a recycled inode cannot look like reuse."""
    desc = [os.open(old / n, os.O_RDONLY | os.O_CLOEXEC) for n in source["native"]]
    try:
        current, session = compile_client(env, work, out, destination, 29, previous=old, keep=True)
        original_inodes = {tuple(v["inode"]) for v in source["native"].values()}
        reused = [n for n, v in current["native"].items() if tuple(v["inode"]) in original_inodes]
        need(source["rsic"]["dep-graph.bin"]["compiler_label"] == current["rsic"]["dep-graph.bin"]["compiler_label"], "different embedded RSIC compiler labels would mask the format test")
        current["previous_native_inodes_still_used"] = reused
        save(out / "result.json", current)
        if mode == "different-format":
            need(not reused, "an old-format native work product survived generation change")
        return current, session
    finally:
        for fd in desc:
            os.close(fd)

def compare(a, b):
    if a["diagnostics"] or b["diagnostics"]:
        return a["source"] == b["source"] and a["diagnostics"] == b["diagnostics"] == ["E0308"]
    return (a["source"], a["output"], a["executable_sha256"], {n: v["sha256"] for n,v in a["native"].items()}) == (b["source"], b["output"], b["executable_sha256"], {n: v["sha256"] for n,v in b["native"].items()})

def direction(source, dest, work, env, out, mode):
    reset(work)
    switch(work, env, source)
    (out / "donor-deps").mkdir()
    deps = dependencies(env, work, out / "donor-deps")
    (out / "base").mkdir()
    base, previous = compile_client(env, work, out / "base", source, 17, keep=True)
    (out / "unchanged").mkdir()
    unchanged, donor = compile_client(env, work, out / "unchanged", source, 17, previous=previous, keep=True)
    need(compare(base, unchanged), "same-compiler unmodified native or executable differs")
    switch(work, env, dest)
    need(deps == {p.name: file_sha(p) for p in sorted((work / "deps").glob("*.rlib"))}, "the donors changed before receiver startup")
    warm, errors = {}, {}
    for case, number in CASES[1:]:
        p = out / case
        p.mkdir()
        try:
            if case == "changed":
                warm[case], _ = carry(unchanged, dest, donor, work, env, p, mode)
            else:
                warm[case], _ = compile_client(env, work, p, dest, number)
        except Exception as failure:
            errors["warm-" + case] = str(failure)
            save(p / "failure.json", {"error": str(failure)})
    # Independently expose metadata incompatibility by retaining only the donor-built rlibs.
    inc = work / "inc/client"
    need(not inc.is_symlink() and (work / ".cross-version-owned").is_file(), "unexpected client cache")
    if inc.exists():
        shutil.rmtree(inc)
    (work / "bin/cross_client").unlink(missing_ok=True)
    empty = out / "donor-rlibs-empty-client"
    empty.mkdir()
    clean_client = None
    try:
        need(deps == {p.name: file_sha(p) for p in (work / "deps").glob("*.rlib")}, "prior-role dependency rlibs changed")
        clean_client, _ = compile_client(env, work, empty, dest, 29)
    except Exception as failure:
        errors["donor-rlibs-empty-client"] = str(failure)
        save(empty / "failure.json", {"error": str(failure)})
    clean = {}
    for case, number in CASES[1:]:
        reset(work)
        d = out / ("clean-" + case)
        d.mkdir()
        try:
            clean_deps = dependencies(env, work, d)
            clean[case], _ = compile_client(env, work, d, dest, number)
            if case in warm:
                need(compare(warm[case], clean[case]), f"receiving {case} differs from independent fully clean destination including dependencies")
            if case == "changed" and clean_client:
                need(compare(clean_client, clean[case]), "donor rlibs alone differ from fully clean destination")
            save(d / "dependency-hashes.json", {"prior_role": deps, "destination_clean": clean_deps})
        except Exception as failure:
            errors["clean-" + case] = str(failure)
            save(d / "failure.json", {"error": str(failure)})
    result = {"source": source["commit"], "dest": dest["commit"], "source_format": source["expected_format"], "dest_format": dest["expected_format"], "mode": mode, "errors": errors, "donor_rlibs_empty_client_sha256": file_sha(empty / "result.json") if clean_client else None, "warm_sha256": {n:file_sha(out / n / "result.json") for n in warm}, "independent_clean_sha256": {n:file_sha(out / ("clean-" + n) / "result.json") for n in clean}, "base_sha256": file_sha(out / "base/result.json"), "unchanged_sha256": file_sha(out / "unchanged/result.json"), "success": not errors}
    save(out / "terminal.json", result)
    return result

def run(a):
    work, out = a.work.resolve(), a.out.resolve()
    if a.self_sdk:
        need(a.factory_receipts is None and a.self_commit and a.self_driver_sha256 and a.self_format is not None and not a.equal_header_diagnostic, "incomplete same-SDK control registration")
        sdk = a.self_sdk.resolve(strict=True)
        ds = list((sdk / "lib").glob("librustc_driver*.so"))
        need(len(ds) == 1 and file_sha(ds[0]) == a.self_driver_sha256, "unexpected signed control driver")
        r = {"sdk": str(sdk), "commit": a.self_commit, "driver": a.self_driver_sha256, "expected_format": a.self_format}
        roles = {"P": r, "C": r.copy()}; mode = "same-sdk-control"
    else:
        need(all(v is not None for v in (a.factory_receipts, a.expect_factory_sha256, a.parent_sdk, a.parent_commit, a.parent_format, a.child_sdk, a.child_commit, a.child_format)), "incomplete two-role factory registration")
        need(a.parent_commit != a.child_commit and (a.parent_format == a.child_format) == a.equal_header_diagnostic, "equal formats may only be explicitly enrolled as diagnostic")
        roles = role_receipts(a)
        mode = "equal-format-diagnostic" if a.equal_header_diagnostic else "different-format"
    for role in roles.values():
        driver, = (Path(role["sdk"]) / "lib").glob("librustc_driver*.so")
        role["elf_build_id"] = elf_build_id(driver)
    if not a.self_sdk:
        need(roles["P"]["elf_build_id"]["hex"] != roles["C"]["elf_build_id"]["hex"], "source-built roles share the same ELF build ID")
    for r in roles.values():
        need(re.fullmatch("[0-9a-f]{40}", r["commit"]) and 0 <= r["expected_format"] <= 65535, "unregistered compiler revision or format")
    for path in (HERE, Path(roles["P"]["sdk"]), Path(roles["C"]["sdk"]), out):
        need(path != work and work not in path.parents and path not in work.parents, "scratch aliases a source, SDK, or result path")
    for path in (HERE, Path(roles["P"]["sdk"]), Path(roles["C"]["sdk"])):
        need(out != path and out not in path.parents and path not in out.parents, "results alias actual source or SDK")
    fresh(work); fresh(out)
    nonce = os.urandom(16).hex(); marker = work / ".cross-version-owned"; marker.write_text(nonce)
    (work / "rustup/toolchains").mkdir(parents=True); (work / "src").mkdir(); (work / "home").mkdir()
    for n in ("api.rs", "provider.rs", "main.rs"):
        shutil.copyfile(HERE / n, work / "src" / n)
    rustup = shutil.which("rustup"); need(rustup, "rustup absent")
    env = dict(HOME=str(work / "home"), RUSTUP_HOME=str(work / "rustup"), RUSTUP_AUTO_INSTALL="0", TMPDIR=str(work/"tmp"), LC_ALL="C", PATH=str(Path(rustup).parent)+":/usr/local/bin:/usr/bin:/bin")
    (work / "tmp").mkdir()
    versions = {k:switch(work, env, r) for k,r in roles.items()}
    need(versions["P"] == versions["C"], "compiler -vV identities differ and mask the format test")
    expect = a.self_commit if a.self_sdk else "unknown"
    need(re.findall(r"^commit-hash: (\S+)$", versions["P"], re.M) == [expect], "unexpected embedded revision")
    save(out / "registration.json", {"mode": mode, "roles": roles, "versions": versions, "files": {p.name:file_sha(p) for p in (HERE / "cross_version.py", HERE / "api.rs", HERE / "provider.rs", HERE / "main.rs")}, "factory_zip_sha256": a.expect_factory_sha256, "runtime_floor": 8*GIB})
    results = {}
    for src, dst in (("P", "C"), ("C", "P")):
        name = src + "-to-" + dst
        folder = out / name
        folder.mkdir()
        try:
            results[name] = direction(roles[src], roles[dst], work, env, folder, mode)
        except Exception as failure:
            results[name] = {"success": False, "errors": {"setup": str(failure)}}
            save(folder / "terminal.json", results[name])
        print(name, results[name]["success"], results[name]["errors"], flush=True)
    accepted = all(v["success"] for v in results.values())
    save(out / "terminal.json", {"success": accepted, "mode": mode, "registration_sha256": file_sha(out / "registration.json"), "directions": {name:file_sha(out / name / "terminal.json") for name in results}})
    need(accepted, "one or more receiving compiler controls failed; see both retained direction receipts")
    need(marker.read_text() == nonce, "private scratch marker changed"); shutil.rmtree(work)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--factory-receipts", type=Path)
    p.add_argument("--expect-factory-sha256")
    for role in ("parent", "child", "self"):
        p.add_argument("--"+role+"-sdk", type=Path)
        p.add_argument("--"+role+"-commit")
        p.add_argument("--"+role+"-format", type=int)
    p.add_argument("--self-driver-sha256")
    p.add_argument("--equal-header-diagnostic", action="store_true")
    run(p.parse_args())
