"""Acquire true rustc execs and complete AArch64 output witnesses in the registered order."""
import ast
from collections import Counter
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
import tomllib
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runtime as rt
from study import ARGS, EDIT, EDIT_TREE, EXPECTED, LOCK, MISSING, READER, RECHECK, RUFF as BASE, SOURCE, ZMIJ, ZMIJ_LIB
from study import change_source, digest, git, load, need, physical, run, save, sha, source_values, text_git

COMMAND = ["cargo", "+ohm", "build", "-p", "ruff_python_ast", "--target", rt.TARGET, "--locked", "--offline", "-j4", "--message-format=json"]
INTEREST = {"zmij", "compact_str", "ruff_python_ast"}
CROSS = "/usr/bin/aarch64-linux-gnu-gcc"
QEMU = ["/usr/bin/qemu-aarch64", "-L", "/usr/aarch64-linux-gnu"]
EXEC = re.compile(r'^execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0$')


def acquire(root, seed):
    need(not any((rt.WORK / n).exists() for n in ("target", "shared", "cargo-home")), "nonempty installation")
    for n in ("target", "shared"):
        (rt.WORK / n).mkdir()
    shutil.copytree(seed, rt.WORK / "cargo-home")
    save(root / "empty.json", {"target": [], "shared": [], "registry": sha(rt.LOG / "registry.json"), "capacity": rt.room()})


def park(name):
    closed = rt.ROOT / "closed" / name
    closed.mkdir(parents=True)
    for n in ("target", "shared", "cargo-home"):
        (rt.WORK / n).rename(closed / n)


def custody(body, suffix):
    name = digest(body)
    folder = rt.LOG / "objects"
    folder.mkdir(exist_ok=True)
    p = folder / (name + suffix)
    if not p.exists():
        with p.open("xb") as out:
            out.write(body)
    need(sha(p) == name, "evidence changed")
    return name


def archive(data):
    need(data.startswith(b"!<arch>\n"), "not an rlib")
    pos, table = 8, b""
    objects, metadata = [], {}
    while pos < len(data):
        header = data[pos:pos + 60]
        need(len(header) == 60 and header[58:] == b"\x60\n", "invalid ar header")
        size = int(header[48:58])
        raw = data[pos + 60:pos + 60 + size]
        need(len(raw) == size, "truncated ar body")
        token = header[:16].rstrip()
        if token == b"//":
            table = raw
        elif token.startswith(b"/") and token[1:].isdigit():
            index = int(token[1:])
            token = table[index:table.index(b"/\n", index)]
        elif token.startswith(b"#1/"):
            length = int(token[3:])
            token, raw = raw[:length].rstrip(b"\0"), raw[length:]
        else:
            token = token.removesuffix(b"/")
        name = token.decode("ascii")
        if name.endswith(".o"):
            need(rt.elf(raw, (1,)), f"foreign object {name}")
            canonical = re.sub(r"\.[0-9a-z]{7}(?=\.rcgu\.o$)", ".<rustc-session>", name)
            objects.append([canonical, name, len(raw), digest(raw)])
        elif name in ("lib.rmeta", "lib.rmeta-link"):
            need(name not in metadata, "duplicate Rust metadata")
            metadata[name] = [len(raw), digest(raw)]
        pos += 60 + size + size % 2
    need(pos == len(data) and objects and "lib.rmeta" in metadata and len({r[0] for r in objects}) == len(objects),
         "incomplete or ambiguous AArch64 object inventory")
    return {"raw": digest(data), "objects": objects, "metadata": metadata}


def native(trace, cwd):
    cargo, rustc = (rt.SDK / "bin" / n for n in ("cargo", "rustc"))
    builds, tools, other, cargo_rows = [], [], [], []
    for p in sorted(trace.glob("proc.*")):
        pid = int(p.suffix[1:])
        lines = p.read_text(errors="backslashreplace").splitlines()
        status = [int(m[1]) for l in lines if (m := re.fullmatch(r"\+\+\+ exited with (\d+) \+\+\+", l))]
        for line in lines:
            if not line.endswith("= 0") or not line.startswith(("execve(", "execveat(")):
                continue
            match = EXEC.fullmatch(line)
            need(match, f"unclassified successful exec: {line[:260]}")
            path = Path(ast.literal_eval(match[1]))
            path = path if path.is_absolute() else cwd / path
            args = ast.literal_eval(match[2])
            row = {"pid": pid, "path": str(path), "argv": args, "terminal": status}
            if path.exists() and path.samefile(cargo):
                cargo_rows.append(row)
            elif path.exists() and path.samefile(rustc):
                if "--crate-name" in args and any(a == "--emit" or a.startswith("--emit=") for a in args):
                    row["crate"] = args[args.index("--crate-name") + 1]
                    row["link_only"] = any(a.startswith("-Zlink-only") or a == "link-only" for a in args)
                    need(not any("ohm-branch-cache" in a or "incremental-branches" in a for a in args), "extra cache policy")
                    builds.append(row)
                else:
                    other.append(row)
            elif (path.name in {"gcc", "cc", "collect2", "ld", "ld.bfd", "ld.lld", "rust-lld", "wild"}
                  or path.name.startswith("aarch64-linux-gnu-") or "wild-ld/" in str(path)):
                tools.append(row)
    need(len(cargo_rows) == 1 and cargo_rows[0]["terminal"], "unobserved physical release Cargo")
    return {"cargo": cargo_rows, "rustcs": builds, "link_tools": tools, "compiler_probes": other}


def command(folder, env, expected=0):
    trace = folder / "exec"
    trace.mkdir(parents=True)
    cmd = ["strace", "-ff", "-q", "-s", "262144", "-e", "trace=execve,execveat", "-o", trace / "proc", *COMMAND]
    result = rt.record(cmd, folder / "cargo", rt.RUFF, env, expected)
    observed = native(trace, rt.RUFF)
    need(observed["cargo"][0]["terminal"] == [expected], "wrong traced Cargo terminal")
    if expected == 0:
        need(all(x["terminal"] == [0] for x in observed["rustcs"]), "failed compiler in a successful build")
    save(folder / "native.json", observed)
    with tarfile.open(folder / "exec.tar.gz", "x:gz", compresslevel=1) as out:
        out.add(trace, arcname="exec")
    with tarfile.open(folder / "exec.tar.gz") as archived:
        for p in trace.iterdir():
            need(archived.extractfile("exec/" + p.name).read() == p.read_bytes(), "trace escrow changed")
    shutil.rmtree(trace)
    return result, observed


def typed(stdout, success):
    events = [json.loads(x) for x in stdout.splitlines()]
    need(events[-1] == {"reason": "build-finished", "success": success}, "wrong Cargo JSON terminal")
    rows = [r for r in events if r["reason"] == "compiler-artifact"]
    def ident(r):
        return [r["package_id"], r["target"]["name"], r["target"]["kind"], sorted(r["features"]), r["profile"]]
    return rows, sorted((ident(r) for r in rows), key=json.dumps), sorted(r["target"]["name"] for r in rows if not r["fresh"]), events


def object_proof(r, folder, searches, state, env):
    paths = [Path(p) for p in r["filenames"] if p.endswith(".rlib")]
    need(len(paths) == 1, "expected one physical AST archive")
    data = paths[0].read_bytes()
    native_elf = archive(data)
    custody(data, ".rlib")
    workspace = rt.WORK / "reader"
    workspace.mkdir(exist_ok=True)
    caller = workspace / "main.rs"
    caller.write_bytes(READER)
    common = ["rustc", "+ohm", "--edition=2024", "--target", rt.TARGET, "--extern", "ruff_python_ast=" + str(paths[0])]
    for value in searches:
        common.extend(["-L", value])
    binary = workspace / "reader"
    binary.unlink(missing_ok=True)
    rt.record([*common, "--crate-name", "qa_version_reader", caller, "-C", "linker=" + CROSS, "-o", binary],
              folder / "reader-link", rt.RUFF, env)
    fresh = binary.read_bytes()
    need(rt.elf(fresh, (2, 3)), "wrong native executable class/target")
    value = rt.record([*QEMU, binary], folder / "qemu", rt.RUFF, env).stdout.decode().strip()
    need(value == EXPECTED[state], f"incorrect genuine reader: {value}")
    minor = 14 if state == "old" else 15
    for label, v, exit_code in (("correct", minor, 0), ("contrary", 29 - minor, 1)):
        caller.write_text("use ruff_python_ast::PythonVersion as V;\n"
                          f"const _: [();{v}]=[();V::latest().as_tuple().1 as usize];\n"
                          f"const _: [();{v}]=[();V::latest_ty().as_tuple().1 as usize];\n")
        dest = workspace / "reader.rmeta"
        dest.unlink(missing_ok=True)
        checked = rt.record([*common, "--crate-type", "lib", "--emit=metadata", "--error-format=json", caller, "-o", dest],
                            folder / label, rt.RUFF, env, exit_code)
        need(dest.is_file() == (exit_code == 0), "contrary caller published metadata")
        if exit_code:
            codes = [x.get("code", {}).get("code") for x in map(json.loads, checked.stderr.splitlines()) if x.get("code")]
            need("E0308" in codes, "wrong contrary diagnostic")
    return {"archive": native_elf, "reader": custody(fresh, ".elf"), "value": value}


def marker(folder):
    unique = {}
    for scope in ("target", "shared"):
        for p in (rt.WORK / scope).rglob("zmij-*.d"):
            b = p.read_bytes()
            if b"zmij-1.0.10/src/lib.rs" in b:
                unique[p.stat().st_dev, p.stat().st_ino] = (p, b)
    need(len(unique) == 1, f"ambiguous target zmij dep-info: {list(unique)}")
    path, b = next(iter(unique.values()))
    (folder / "zmij.d").write_bytes(b)
    return {"depinfo": str(path), "sha256": digest(b), "hard": MISSING in b, "recheck": RECHECK in b}


def visit(root, label, state, env, searches):
    folder = root / label
    rc = 101 if state == "invalid" else 0
    need(text_git(rt.RUFF, "rev-parse", "HEAD") == BASE, "Ruff HEAD moved")
    result, observed = command(folder, env, rc)
    rows, inventory, dirty, events = typed(result.stdout, rc == 0)
    record = {"phase": label, "capacity": rt.room(), "source": sha(rt.RUFF / SOURCE), "typed": inventory,
              "dirty": dirty, "crates": [r["crate"] for r in observed["rustcs"]],
              "native": sha(folder / "native.json"), "marker": marker(folder)}
    for x in observed["rustcs"]:
        av = x["argv"]
        if x["crate"] in INTEREST:
            need("--target" in av and av[av.index("--target") + 1] == rt.TARGET and not x["link_only"], "wrong crate target")
        if x["crate"] == "ruff_python_ast":
            searches[:] = [av[i + 1] for i in range(len(av) - 1) if av[i] == "-L" and av[i + 1].startswith("dependency=")]
    if state == "invalid":
        codes = [r.get("message", {}).get("code") for r in events if r["reason"] == "compiler-message"]
        need(any(c and c["code"] == "E0425" for c in codes) and b"apple_zmij_missing_name" in result.stdout, "wrong actual invalid source diagnostic")
        record["error"] = "E0425"
    else:
        ast_rows = [r for r in rows if r["target"]["name"] == "ruff_python_ast"]
        need(len(ast_rows) == 1 and searches, "missing physical AST or search path")
        record.update(object_proof(ast_rows[0], folder, searches, state, env))
    save(folder / "verified.json", record)
    return record


def instructions(profile, pid):
    total, edge, pids, headers, totals = 0, False, [], [], []
    with profile.open("rb") as inp:
        for line in inp:
            if line.startswith(b"pid: "):
                pids.append(int(line.split()[1]))
            elif line.startswith(b"events: "):
                headers.append(line.split()[1:])
            elif line.startswith(b"totals: "):
                totals.append(int(line.split()[1]))
            elif line.startswith(b"calls="):
                need(not edge, "unfinished call edge")
                edge = True
            elif line.strip() and line[:1] in b"0123456789+-*":
                if edge:
                    edge = False
                else:
                    total += int(line.split()[-1])
    need(not edge and headers == [[b"Ir"]] and pids == [pid] and totals == [total] and total > 0,
         f"unaccounted per-process profile {pid}")
    return total


def counter(folder, env, ordinary):
    require = load(ordinary / "native.json")
    expected = {r["crate"]: r["argv"] for r in require["rustcs"]}
    need(len(expected) == len(require["rustcs"]) and expected.keys() <= INTEREST, "unexpected counter roster")
    folder.mkdir()
    profiles = folder / "profiles"
    profiles.mkdir(mode=0o700)
    cmd = [rt.ROOT / "trace", profiles, rt.SDK / "bin/rustc", rt.SDK / rt.WILD, ",".join(sorted(INTEREST)), "--", *COMMAND]
    stdout = rt.record(cmd, folder / "cargo", rt.RUFF, env)
    need(typed(stdout.stdout, True)[1:3] == typed(gzip.decompress((ordinary / "cargo/stdout.gz").read_bytes()), True)[1:3],
         "instrumentation changed the Cargo graph")
    need(re.findall(rb"^cargo (\d+)\nlinks (\d+)$", stdout.stderr, re.M) == [(b"0", b"0")], "unexpected instrumented status or stock link")
    observed = {}
    for pid, name, redirected, code in re.findall(rb"^compiler (\d+) (\S+) (\d+) (\d+)$", stdout.stderr, re.M):
        base, crate = pid.decode(), name.decode()
        need(redirected == b"1" and code == b"0" and crate in expected and crate not in observed, "unmatched counted rustc")
        args = (profiles / f"rustc.{base}.argv").read_bytes().split(b"\0")
        need(args[-1] == b"" and list(map(os.fsdecode, args[:-1])) == expected[crate], "instrumentation changed actual rustc argv")
        jobs = (profiles / f"rustc.{base}.jobserver").read_text()
        fds = (profiles / f"rustc.{base}.fds").read_text()
        inherited = re.search(r"--jobserver-(?:auth|fds)=(\d+),(\d+)", jobs)
        need(inherited and all(re.search(r"^" + fd + r" pipe:\[\d+\]$", fds, re.M) for fd in inherited.groups()),
             "missing real GNU jobserver descriptors")
        profile, log = profiles / f"output.{base}.{base}", profiles / f"valgrind.{base}.{base}"
        need(list(profiles.glob(f"valgrind.{base}.*")) == [log], "additional compiler child in Callgrind stream")
        ir = instructions(profile, int(base))
        log_body = log.read_bytes()
        need(re.findall(rb"^==" + pid + rb"== Events\s*:\s+Ir\s*$", log_body, re.M)
             and re.findall(rb"^==" + pid + rb"== Collected\s+:\s+([\d,]+)\s*$", log_body, re.M)[0].replace(b",", b"") == str(ir).encode(),
             "logger total disagrees")
        externs = {args[i + 1].decode().split("=", 1)[0]: sha(Path(os.fsdecode(args[i + 1]).split("=", 1)[1]))
                   for i in range(len(args) - 1) if args[i] == b"--extern" and b"=" in args[i + 1]}
        observed[crate] = {"Ir": ir, "pid": int(base), "argv": sha(profiles / f"rustc.{base}.argv"),
                           "profile": sha(profile), "externs": externs}
    need(set(observed) == set(expected) and len(list(profiles.glob("output.*"))) == len(observed), "missing or extra complete compiler")
    for p in profiles.glob("output.*"):
        zipped = p.with_name(p.name + ".gz")
        with p.open("rb") as source, gzip.open(zipped, "xb", compresslevel=2) as out:
            shutil.copyfileobj(source, out)
        with gzip.open(zipped, "rb") as inp:
            need(rt.hashlib.file_digest(inp, "sha256").hexdigest() == sha(p), "profile compression changed data")
        p.unlink()
    save(folder / "verified.json", {"rustcs": observed, "compiler_only_Ir": sum(v["Ir"] for v in observed.values())})
    return observed


def prepare():
    rt.room()
    differences = {}
    for role in "PC":
        differences[role] = rt.select(role)
        rt.probe(role)
    need(differences["P"] == differences["C"], "different role selector")
    save(rt.LOG / "pair.json", {"changed_paths": differences["P"], "P": sha(rt.LOG / "P-sdk.json"), "C": sha(rt.LOG / "C-sdk.json"),
                                "host_compiler": rt.HOST, "cross_target": rt.TARGET, "signed": rt.TOOLS,
                                "link_driver": physical(Path(CROSS)), "qemu": physical(Path(QEMU[0])),
                                "loader": physical(Path("/usr/aarch64-linux-gnu/lib/ld-linux-aarch64.so.1"))})
    rt.WORK.mkdir()
    run(["git", "init", "-q", "--template=", str(rt.RUFF)])
    git(rt.RUFF, "fetch", "--no-tags", "--depth=2", "https://github.com/astral-sh/ruff.git", EDIT)
    git(rt.RUFF, "switch", "-q", "-c", "qa-apple-zmij", BASE)
    source_values(rt.RUFF)
    need(len(git(rt.RUFF, "diff", "--name-only", BASE, EDIT).splitlines()) == 74, "historical edit width changed")
    seed = rt.ROOT / "seed"
    seed.mkdir()
    env = rt.environment()
    env.update(CARGO_HOME=str(seed), CARGO_TARGET_DIR=str(rt.ROOT / "fetch-target"), CARGO_BUILD_BUILD_DIR=str(rt.ROOT / "fetch-build"))
    env.pop("CARGO_NET_OFFLINE")
    rt.record(["cargo", "+ohm", "fetch", "--locked"], rt.LOG / "fetch", rt.RUFF, env)
    locked = {p["name"] + "-" + p["version"] + ".crate": p["checksum"] for p in tomllib.loads((rt.RUFF / "Cargo.lock").read_text())["package"] if "checksum" in p}
    packages = list((seed / "registry/cache").glob("*/*.crate"))
    found = {p.name: sha(p) for p in packages}
    need(found == locked and found["zmij-1.0.10.crate"] == ZMIJ and len(found) > 400, "incomplete/mismatched locked registry")
    files = [p for p in packages if p.name == "zmij-1.0.10.crate"]
    need(len(files) == 1, "ambiguous installed zmij archive")
    with tarfile.open(files[0]) as tar:
        data = tar.extractfile("zmij-1.0.10/src/lib.rs").read()
    need(digest(data) == ZMIJ_LIB and b'#[cfg(all(target_arch = "aarch64", target_feature = "neon", not(miri)))]' in data
         and b'asm!("/*{:v}*/", inout(vreg) extended);' in data, "actual registry source does not select the candidate")
    save(rt.LOG / "registry.json", {"lock": LOCK, "archives": found, "zmij_lib": digest(data), "edit": EDIT, "tree": EDIT_TREE})


def semantic(row):
    return {"native": [[n, size, key] for n, original, size, key in row["archive"]["objects"]],
            "reader": row["reader"], "value": row["value"]}


def trial(label, role):
    rt.select(role)
    root = rt.LOG / label
    root.mkdir()
    values = source_values(rt.RUFF)
    change_source(rt.RUFF, values, "old")
    env = rt.environment()
    searches = []
    acquire(root, rt.ROOT / "seed")
    stages = {"old-empty": visit(root, "old-empty", "old", env, searches)}
    change_source(rt.RUFF, values, "new")
    for name in ("edit", "unchanged-1"):
        stages[name] = visit(root, name, "new", env, searches)
    # The instrumented call is bracketed by ordinary kernel-traced visits.
    try:
        measured = counter(root / "counter", env, root / "unchanged-1")
    except Exception as exc:
        save(root / "counter-unavailable.json", {"exception": repr(exc), "details": traceback.format_exc()})
        measured = None
    stages["unchanged-2"] = visit(root, "unchanged-2", "new", env, searches)
    before, after = (load(root / n / "native.json") for n in ("unchanged-1", "unchanged-2"))
    need(sorted(r["argv"] for r in before["rustcs"]) == sorted(r["argv"] for r in after["rustcs"])
         and stages["unchanged-1"]["dirty"] == stages["unchanged-2"]["dirty"], "ordinary flanks changed")
    change_source(rt.RUFF, values, "invalid")
    stages["invalid"] = visit(root, "invalid", "invalid", env, searches)
    change_source(rt.RUFF, values, "new")
    stages["repair"] = visit(root, "repair", "new", env, searches)
    park(label + "-warm")
    acquire(root / "clean", rt.ROOT / "seed")
    searches.clear()
    stages["empty-edited"] = visit(root, "empty-edited", "new", env, searches)
    park(label + "-clean")
    cold = semantic(stages["empty-edited"])
    for n in ("edit", "unchanged-1", "unchanged-2", "repair"):
        need(semantic(stages[n]) == cold, f"{label}: {n} and independent clean differ; retain full archives and complete readers")
    need(stages["old-empty"]["reader"] != cold["reader"] and stages["old-empty"]["value"] != cold["value"], "uninformative reader")
    need(all(s["typed"] == stages["old-empty"]["typed"] for n, s in stages.items() if n != "invalid"), "typed unit roster changed")
    return {"role": role, "cold": cold, "old": semantic(stages["old-empty"]), "measured": measured,
            "stages": {n: {"rustcs": r["crates"], "dirty": r["dirty"], "hard": r["marker"]["hard"], "recheck": r["marker"]["recheck"],
                      "output": r.get("reader"), "raw_archive": r.get("archive", {}).get("raw"),
                      "receipt": sha(root / n / "verified.json")} for n, r in stages.items()}}


def screen():
    trials = {}
    for label, role in (("mirror1-P", "P"), ("mirror1-C", "C"), ("mirror2-C", "C"), ("mirror2-P", "P")):
        trials[label] = trial(label, role)
        save(rt.LOG / label / "complete.json", trials[label])
    base = trials["mirror1-P"]
    need(all(v["cold"]["native"] == base["cold"]["native"] and v["old"]["native"] == base["old"]["native"]
             and v["cold"]["value"] == base["cold"]["value"] and v["old"]["value"] == base["old"]["value"]
             for v in trials.values()), "same-source cross-role native payloads or runtime values differ")
    observations = {}
    for mirror in ("mirror1", "mirror2"):
        p, c = [trials[mirror + "-" + r] for r in "PC"]
        checked = {}
        for phase in ("edit", "unchanged-1", "unchanged-2"):
            a, b = [x["stages"][phase] for x in (p, c)]
            links = [load(rt.LOG / (mirror + "-" + r) / phase / "native.json")["link_tools"] for r in "PC"]
            no_extra = not (Counter(Path(v["path"]).name for v in links[1]) - Counter(Path(v["path"]).name for v in links[0]))
            before, after = map(Counter, (a["rustcs"], b["rustcs"]))
            checked[phase] = {"parent": a, "child": b, "no_extra_linker_processes": no_extra,
                              "eliminated": list((before - after).elements()), "extra": list((after - before).elements()),
                              "candidate_removed_zmij": before["zmij"] > 0 and after["zmij"] == 0}
            if phase.startswith("unchanged"):
                checked[phase]["eligible"] = (checked[phase]["candidate_removed_zmij"] and not checked[phase]["extra"]
                    and no_extra and a["hard"] and not b["hard"] and sum(after.values()) < sum(before.values()))
        observations[mirror] = checked
    go = all(x[n]["eligible"] for x in observations.values() for n in ("unchanged-1", "unchanged-2"))
    save(rt.LOG / "terminal.json", {"two_mirrors": observations, "mechanism_observed": go,
                                   "per_compiler_counts": {n: t["measured"] for n,t in trials.items()},
                                   "sha256": {name: sha(rt.LOG / name / "complete.json") for name in trials},
                                   "primary": "kernel-observed complete compiler count on the first unchanged edited Ruff build"})


def selftest():
    good = bytearray(64)
    good[:6] = b"\x7fELF\x02\x01"
    good[16:20] = b"\x01\0\xb7\0"
    def member(name, data):
        header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{644:<8}{len(data):<10}".encode() + b"\x60\n"
        return header + data + (b"\n" if len(data) % 2 else b"")
    a = b"!<arch>\n" + member("lib.rmeta", b"R") + member("a.o", good)
    need(archive(a)["objects"][0][3] == digest(good), "positive complete ELF section fixture")
    for b in (a.replace(b"\xb7\0", b">\0"), a[:-2]):
        try:
            archive(b)
        except (RuntimeError, ValueError):
            continue
        raise RuntimeError("accepted malformed or foreign ELF")
    need(EXEC.fullmatch('execve("/usr/bin/rustc", ["rustc", "--crate-name", "zmij"], 0xabc /* 23 vars */) = 0'),
         "strace parser rejects a complete POSIX native argv")
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / "profile"
        path.write_bytes(b"pid: 7\nevents: Ir\n1 7\ncalls=1 2\n2 11\n3 4\ntotals: 11\n")
        need(instructions(path, 7) == 11, "edge/self costs conflated")
        path.write_bytes(path.read_bytes().replace(b"totals: 11", b"totals: 12"))
        try:
            instructions(path, 7)
        except RuntimeError:
            return
        raise RuntimeError("inconsistent native Ir stream accepted")


if __name__ == "__main__":
    action = sys.argv[1]
    try:
        if action == "freeze":
            rt.freeze(sys.argv[2], sys.argv[3])
        else:
            {"selftest": selftest, "room": lambda: rt.room(True), "release": rt.release, "admit": prepare, "screen": screen}[action]()
    except Exception:
        if action != "selftest" and rt.LOG.is_dir():
            failed = rt.LOG / ("failed-" + action + ".txt")
            if not failed.exists():
                failed.write_text(traceback.format_exc())
        raise
