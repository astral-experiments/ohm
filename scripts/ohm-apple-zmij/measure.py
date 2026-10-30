"""Ordinary Cargo measurements and independent endpoint-security/native-product witnesses."""

import collections
import ctypes
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from calibrate import fields
from objects import archive_evidence
from study import (
    ARGS,
    EXPECTED,
    MISSING,
    READER,
    RECHECK,
    SOURCE,
    ZMIJ_LIB,
    change_source,
    check_host,
    compress_bytes,
    copy_tree,
    digest,
    env_for,
    load,
    need,
    physical,
    run,
    save,
    sdk_id,
    sha,
    source_values,
)


def fresh(work, seed):
    # Only these three directories inside our exclusively created per-job root are disposable.
    for name in ("target", "shared", "cargo-home"):
        p = work / name
        need(not p.exists(), f"expected independently empty {p}")
    copy_tree(seed, work / "cargo-home")
    (work / "target").mkdir()
    (work / "shared").mkdir()


def retire(work):
    for name in ("target", "shared", "cargo-home"):
        p = work / name
        need(p.is_dir() and not p.is_symlink() and p.parent == work, "unsafe private scratch path")
        shutil.rmtree(p)
    (work / "zmij-dep-location").unlink(missing_ok=True)


def select(root, role):
    if role == "S":
        return root / "signed"
    sdk = root / "native"
    pair = load(root / "receipts/pair.json")
    parked = root / "parked-native-libraries"
    active = sdk / "lib"
    if not parked.exists():
        parked.mkdir()
        # Switching directory entries preserves the inode and ctime of every
        # loaded driver. Cargo includes those fields in its workspace namespace.
        shutil.copytree(active, parked/"C", symlinks=True, copy_function=os.link)
        for name in pair["differ"]:
            relative = Path(name).relative_to("lib")
            before = parked/"C"/relative
            parent, child = [root/("stage-"+r)/name for r in "PC"]
            need(before.samefile(parent) and sha(child)==pair["products"]["C"]["runtime"][name], "unexpected initial compiler image")
            before.unlink()
            os.link(child, before)
        save(parked/"identity.json", {r:{n:_driver_stamp(root/("stage-"+r)/n) for n in pair["differ"]} for r in "PC"})
    other = "C" if role=="P" else "P"
    names = pair["differ"]
    if not (sdk/names[0]).samefile(root/("stage-"+role)/names[0]):
        need(not (parked/other).exists() and (parked/role).is_dir(), "invalid parked installation")
        active.rename(parked/other)
        try:
            (parked/role).rename(active)
        except OSError:
            (parked/other).rename(active)
            raise
    expected = load(parked/"identity.json")
    for name in names:
        selected = sdk/name
        need(selected.samefile(root/("stage-"+role)/name) and _driver_stamp(selected)==expected[role][name], "changed selected driver identity")
        need(_driver_stamp(root/("stage-"+other)/name)==expected[other][name], "changed inactive driver identity")
    return sdk


def _driver_stamp(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_ctime_ns, s.st_mtime_ns, s.st_size, sha(path)]


def stock_linker(path, ld):
    """Resolve Xcode's active native linker or its separately installed Apple variant by inode."""
    if not path.is_file():
        return False
    if path.samefile(ld):
        return True
    if path.name not in ("ld-classic", "ld-prime", "ld64"):
        return False
    found = subprocess.run(["xcrun", "--find", path.name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return found.returncode == 0 and path.samefile(found.stdout.decode().strip())


def native_rows(rows, sdk):
    partial = bool(rows and rows[0].get("scope") == "compiler-wrapper-unscored")
    if partial:
        rows = rows[1:]
    rustc, cargo = (sdk / "bin" / n for n in ("rustc", "cargo"))
    cargo_events = [r for r in rows if Path(r["path"]).exists() and Path(r["path"]).samefile(cargo)]
    # #293 executes this very Cargo binary a second time through a per-unit linker alias.
    drivers = [r for r in cargo_events if r["argv"] and Path(r["argv"][0]).name == "ohm-link-cc"
               and Path(r["argv"][0]).parent.name.endswith(".rlink-objects")]
    real_cargo = [r for r in cargo_events if r not in drivers]
    full = []
    relink = []
    linkers = []
    ld = Path(run(["xcrun", "--find", "ld"]).decode().strip()).resolve()
    for r in rows:
        path, a = Path(r["path"]), r["argv"]
        if path.exists() and path.samefile(rustc) and "--crate-name" in a:
            name = a[a.index("--crate-name") + 1]
            if name == "___" and ("--print" in a or any(x.startswith("--print=") for x in a)):
                continue
            need(
                not any("ohm-branch-cache" in x or "incremental-branches" in x for x in a),
                "branch retention in compiler flags",
            )
            if any("link-only" in x for x in a):
                relink.append(name)
            else:
                full.append(name)
        if (
            path.name
            in ("ld", "ld64", "ld-classic", "ld-prime", "ld64.lld", "ld.lld", "rust-lld", "wild", "wild-ld")
            or path.exists()
            and path.samefile(ld)
        ):
            linkers.append(
                {"name": path.name, "sha": sha(path), "stock": stock_linker(path, ld), "argv": r["argv"]}
            )
    return {
        "scope": "compiler-wrapper-unscored" if partial else "kernel-exec",
        "cargo": None if partial else len(real_cargo),
        "cargo_link_driver": [{"pid": r["pid"], "ppid": r["ppid"], "alias": r["argv"][0],
                              "path": r["path"], "cdhash": r["cdhash"]} for r in drivers],
        "full": sorted(full),
        "link_only": sorted(relink),
        "linkers": None if partial else linkers,
    }


def typed(stream, success):
    events = [json.loads(line) for line in stream.splitlines()]
    need(events and events[-1] == {"reason": "build-finished", "success": success}, "Cargo JSON terminal")
    artifacts = [r for r in events if r["reason"] == "compiler-artifact"]
    keys = [
        (
            r["package_id"],
            r["target"]["name"],
            ",".join(r["target"]["kind"]),
            tuple(r["features"]),
            json.dumps(r["profile"], sort_keys=True, separators=(",", ":")),
        )
        for r in artifacts
    ]
    need(len(set(keys)) == len(keys), "ambiguous typed Cargo artifact")
    dirty = sorted([list(k) for k, r in zip(keys, artifacts) if not r["fresh"]])
    codes = [
        r["message"]["code"]["code"]
        for r in events
        if r["reason"] == "compiler-message" and r["message"].get("code")
    ]
    return artifacts, dirty, codes, sorted(keys)


def marked(work):
    paths = list((work / "shared").rglob("zmij-*.d")) + list((work / "target").rglob("zmij-*.d"))
    # Some layout paths may expose the same physical file. Never select among different candidates.
    unique = {(p.stat().st_dev, p.stat().st_ino): p for p in paths}
    need(len(unique) == 1, f"ambiguous zmij dep-info ({len(unique)})")
    p = next(iter(unique.values()))
    (work / "zmij-dep-location").write_text(str(p))
    b = p.read_bytes()
    return marker_bytes(b)


def marker_bytes(b):
    need(b"zmij-1.0.10/src/lib.rs" in b, "dep-info lost registry source")
    return {"sha256": digest(b), "hard": MISSING in b, "recheck": RECHECK in b}, b


def capture(argv, cwd, env, out, trace=None, clock=False):
    out.mkdir(parents=True)
    rows = None
    times = {}
    # Only enroll these exact Cargo subjects. Native readers and provider fixtures run separately.
    ast_request = (len(argv) > 3 and argv[:2] == ["cargo", "+ohm"] and argv[2] in {"build", "test"}
                   and "-p" in argv and argv[argv.index("-p")+1] == "ruff_python_ast")
    if ast_request:
        from ast_developer_witness import before, after, runtime
        host = runtime(env)
        prior = before(host[0]) if trace is not None else None
    with tempfile.TemporaryFile() as o, tempfile.TemporaryFile() as e:
        if trace is not None:
            status, rows = trace.command(argv, env=env, cwd=cwd, out=o, err=e)
        else:
            command = argv
            if clock:
                t = out / "time.txt"
                command = ["/usr/bin/time", "-l", "-o", str(t), *argv]
            p = None
            expired = threading.Event()

            def stop():
                expired.set()
                if p:
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            watchdog = threading.Timer(600, stop)
            watchdog.start()
            try:
                start = time.monotonic_ns()
                p = subprocess.Popen(command, cwd=cwd, env=env, stdout=o, stderr=e, start_new_session=True)
                status = p.wait()
                stop_ns = time.monotonic_ns()
                elapsed = stop_ns - start
            finally:
                watchdog.cancel()
            need(not expired.is_set(), "Cargo watchdog expired")
            if clock:
                times = {"ns": elapsed, "start_ns": start, "stop_ns": stop_ns, **fields(t.read_text())}
        o.seek(0)
        stdout = o.read()
        e.seek(0)
        stderr = e.read()
    sums = {
        "stdout": compress_bytes(out / "stdout.gz", stdout),
        "stderr": compress_bytes(out / "stderr.gz", stderr),
    }
    if rows is not None:
        sums["native_events"] = compress_bytes(
            out / "exec.json.gz", json.dumps(rows, separators=(",", ":")).encode()
        )
    if ast_request and trace is not None:
        receipt=after(host, env, out, rows, prior, argv[2])
        if argv[2]=='build' and status==0:
            from ast_developer_witness import library_work_products
            archive,_=products(typed(stdout,True)[0])
            library_work_products(host[0],out,archive,receipt)
    return status, stdout, stderr, rows, dict(streams=sums, **times)


def products(artifacts):
    outputs = [Path(p) for r in artifacts for p in r["filenames"]]
    ast = [
        Path(p)
        for r in artifacts
        if r["target"]["name"] == "ruff_python_ast"
        for p in r["filenames"]
        if p.endswith(".rlib")
    ]
    need(len(ast) == 1 and ast[0].is_file(), "missing Ruff rlib")
    return ast[0], sorted({p.parent for p in outputs if p.suffix in (".rlib", ".rmeta", ".dylib")})


def caller(work, sdk, env, archive, search, state, out, trace):
    source = work / "reader.rs"
    source.write_bytes(READER)
    binary = work / "reader"
    args = [
        "rustc",
        "+ohm",
        "--edition=2024",
        "--crate-name",
        "qa_version_reader",
        str(source),
        "--extern",
        "ruff_python_ast=" + str(archive),
    ]
    for p in search:
        args.extend(["-L", "dependency=" + str(p)])
    args.extend(["-o", str(binary)])
    status, _, stderr, rows, stats = capture(args, work, env, out / "link", trace)
    need(status == 0, "actual reader link failed: " + stderr.decode(errors="replace")[-800:])
    native = None
    if trace:
        native = native_rows(rows, sdk)
        need(
            native["full"] == ["qa_version_reader"]
            and (native["linkers"] is None or sum(l["stock"] for l in native["linkers"]) == 1),
            "missing actual Apple linker/reader",
        )
    value = run([str(binary)]).decode().strip()
    need(value == EXPECTED[state], "wrong reader value: " + value)
    with binary.open("rb") as f:
        header = f.read(16)
    need(
        header[:8] == bytes.fromhex("cffaedfe0c000001") and header[12:16] == b"\2\0\0\0",
        "reader is not ARM64 MH_EXECUTE",
    )
    from verbs import macho_text
    binary_digest = sha(binary)
    if trace is not None:
        archived = work.parent / "receipts/ast-rlib" / (sha(archive) + ".rlib.gz")
        archived.parent.mkdir(exist_ok=True)
        if not archived.exists():
            need(compress_bytes(archived, archive.read_bytes()) == sha(archive), "archive changed during custody")
    copies = work.parent / "receipts" / "clean-readers"
    copies.mkdir(exist_ok=True)
    receipt = copies / (binary_digest + ".macho.gz")
    if not receipt.exists():
        need(
            compress_bytes(receipt, binary.read_bytes()) == binary_digest,
            "native reader changed during custody",
        )
    return {
        "sha256": binary_digest,
        "value": value,
        "macho_text": macho_text(binary)["text"],
        **archive_evidence(archive),
        "native": native,
        "streams": stats["streams"],
    }


def hold_output(work, result, where):
    status, stdout, _err, _rows, _stats = result
    if status != 0:
        return None
    archive, search = products(typed(stdout, True)[0])
    staged = work / "held-readers"
    staged.mkdir(exist_ok=True)
    dest = staged / (where.name + "-libruff_python_ast.rlib")
    # APFS clone in the controller, outside the timed call. No reader, linker, child
    # process or userspace scan of an object runs between the three Cargo commands.
    libc = ctypes.CDLL(None, use_errno=True)
    fn = libc.clonefile
    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    need(fn(os.fsencode(archive), os.fsencode(dest), 0) == 0, "APFS clonefile of returned artifact failed")
    return dest, search, marker_bytes(Path((work / "zmij-dep-location").read_text()).read_bytes())


def phase(root, work, sdk, env, role, label, state, trace, out, *, captured=None, held=None):
    repo = root / "ruff"
    expected = state != "invalid"
    check_host(root, 6)
    status, stdout, stderr, rows, stats = (
        captured if captured is not None else capture(ARGS, repo, env, out, trace)
    )
    need(status == (0 if expected else 101), f"{label}: Cargo exit {status}")
    arts, dirty, codes, roster = typed(stdout, expected)
    zmij = [r for r in arts if r["target"]["name"] == "zmij" and r["target"]["kind"] == ["lib"]]
    need(
        len(zmij) == 1 and sha(zmij[0]["target"]["src_path"]) == ZMIJ_LIB, "unmodified original zmij not used"
    )
    mark, body = held[2] if held else marked(work)
    compress_bytes(out / "zmij.dep.gz", body)
    if expected:
        archive, search = held[:2] if held else products(arts)
        canon = work / "reader-in/libruff_python_ast.rlib"
        canon.parent.mkdir(exist_ok=True)
        if canon.exists():
            canon.unlink()
        os.link(archive, canon)
        reader = caller(work, sdk, env, canon, search, state, out / "reader", trace)
        canon.unlink()
        if held:
            held[0].unlink()
    else:
        need("E0425" in codes and b"apple_zmij_missing_name" in stdout + stderr, "wrong invalid diagnostic")
        reader = None
    native = native_rows(rows, sdk) if rows is not None else None
    if native:
        need(
            native["cargo"] in (None, 1) and native["full"].count("zmij") == int(not zmij[0]["fresh"]),
            "actual vs typed zmij mismatch",
        )
        need(all(link["stock"] for link in native["linkers"]), "non-Apple linker in Cargo invocation")
        if label == "edit":
            need("ruff_python_ast" in native["full"], "real AST library edit did not compile")
    record = {
        "phase": label,
        "role": role,
        "state": state,
        "success": expected,
        "dirty": dirty,
        "roster": roster,
        "native": native,
        "marker": mark,
        "fresh_zmij": zmij[0]["fresh"],
        "reader": reader,
        "codes": codes,
        "source": sha(repo / SOURCE),
        "cargo": stats,
    }
    save(out / "verified.json", record)
    return record


def installation(root, role, out, *, trace=None, timed=False, clean_only=None, invalid=False):
    work = root / ("signed-study-work" if role == "S" else "study-work")
    work.mkdir(exist_ok=True)
    sdk = select(root, role)
    env = env_for(work, sdk)
    fresh(work, root / "seed")
    before = sdk_id(sdk, env)
    repo = root / "ruff"
    values = source_values(repo)
    plan = [("cold", "old"), ("edit", "new"), ("repeat-1", "new"), ("repeat-2", "new")]
    if clean_only:
        plan = [("clean-" + clean_only, clean_only)]
    if invalid:
        plan.extend([("invalid", "invalid"), ("repair", "new")])
    records = {}
    previous = None
    pending = []
    for label, state in plan:
        if state != previous:
            change_source(repo, values, state)
        if label in ("edit", "repeat-1", "repeat-2"):
            dest = out / label
            result = capture(ARGS, repo, env, dest, trace, clock=timed)
            frozen = hold_output(work, result, dest)
            pending.append((label, state, dest, result, frozen))
            if label == "repeat-2":
                for k, s, d, r, h in pending:
                    records[k] = phase(root, work, sdk, env, role, k, s, trace, d, captured=r, held=h)
                pending = []
        else:
            records[label] = phase(root, work, sdk, env, role, label, state, trace, out / label)
        previous = state
    need(before == sdk_id(sdk, env), "physical SDK changed within installation")
    save(
        out / "terminal.json",
        {
            "role": role,
            "compiler": before,
            "phases": list(records),
            "phase_sha256": {k: sha(out / k / "verified.json") for k in records},
        },
    )
    if timed:
        from ast_developer_witness import timed_final
        timed_final(work,out)
    retire(work)
    return records
