"""Check native compiler and linker work for real test-build and metadata edits on Ruff #28335."""

import argparse
import ctypes
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from execs import ExecTrace
from measure import capture, fresh, marked, marker_bytes, native_rows, retire, select, typed
from prepare import prepare_ruff
from study import ZMIJ_LIB, compress_bytes, digest, env_for, git, load, need, run, save, sdk_id, sha, text_git

A = "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13"
B = "7b13f01ba1569887a25670820764b24c206da8e5"
TREES = {A: "2b61306d708a211b3725c8d920e7590be6da41ad", B: "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c"}
LOCK = "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"
NEW_TEST = "nodes::tests::f_string_parts"
SIZE_TEST = "nodes::tests::size"
PANICS = {"token::tokens::tests::" + name for name in (
    "tokens_after_offset_inside_token", "tokens_before_offset_inside_token",
    "tokens_in_range_start_offset_inside_token", "tokens_in_range_end_offset_inside_token",
    "tokens_split_at_inside_token", "tokens_split_at_matches_before_and_after_zero_length",
)}
BAD_NAME = "ohm_test_build_missing_28335"
ARGS = {
    "check": ["cargo", "+ohm", "check", "--lib"],
    "test": ["cargo", "+ohm", "test", "--lib", "--no-run"],
}
for prefix in ARGS.values():
    prefix.extend(["-p", "ruff_python_ast", "--locked", "--offline", "-j4", "--message-format=json"])


def source_identity(repo):
    need(text_git(repo, "rev-parse", "HEAD") == A and text_git(repo, "rev-parse", B + "^") == A, "wrong revisions")
    need(all(text_git(repo, "rev-parse", rev + "^{tree}") == tree for rev, tree in TREES.items()), "wrong trees")
    need(len(git(repo, "diff", "--name-only", A, B).splitlines()) == 169, "incomplete Ruff edit")
    for rev in (A, B):
        need(digest(git(repo, "show", rev + ":Cargo.lock")) == LOCK, "unexpected Cargo.lock")


def restore(repo, state):
    rev = A if state == "old" else B
    git(repo, "restore", "--source", rev, "--staged", "--worktree", "--", ".")
    need(text_git(repo, "write-tree") == TREES[rev] and not git(repo, "diff", "--name-only").strip(), "wrong checkout")
    need(text_git(repo, "rev-parse", "HEAD") == A and sha(repo / "Cargo.lock") == LOCK, "source identity drift")
    if state == "invalid":
        with (repo / "crates/ruff_python_ast/src/lib.rs").open("ab") as dst:
            dst.write(("\npub const OHM_TEST_BUILD_INVALID: usize = " + BAD_NAME + ";\n").encode())


def macho_text(path):
    """Read the executable instructions separately from the native UUID, signatures and debug tables."""
    data = path.read_bytes()
    need(data[:8] == bytes.fromhex("cffaedfe0c000001") and struct.unpack_from("<I", data, 12)[0] == 2, "not ARM64 MH_EXECUTE")
    count, size = struct.unpack_from("<II", data, 16)
    pos = 32
    result = []
    for _ in range(count):
        cmd, end = struct.unpack_from("<II", data, pos)
        need(end >= 8 and pos + end <= 32 + size <= len(data), "corrupt Mach-O command")
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", data, pos + 64)[0]
            need(72 + 80 * nsects <= end, "bad segment size")
            for i in range(nsects):
                s = pos + 72 + 80 * i
                names = [data[j:j+16].rstrip(b"\0") for j in (s, s + 16)]
                if names == [b"__text", b"__TEXT"]:
                    length, offset = struct.unpack_from("<QI", data, s + 40)
                    need(length and offset + length <= len(data), "bad executable section")
                    result.append([length, digest(data[offset:offset + length])])
        pos += end
    need(pos == size + 32 and len(result) == 1, "missing text section")
    return {"raw": digest(data), "text": result[0]}


def suite_verdicts(whole, names):
    records = []
    for line in whole.decode().splitlines():
        if not line.startswith("test ") or " ... " not in line:
            continue
        formatted, verdict = line.removeprefix("test ").rsplit(" ... ", 1)
        name = formatted.removesuffix(" - should panic")
        need((formatted != name) == (name in PANICS) and verdict == "ok", "unexpected libtest verdict: " + line)
        records.append([name, verdict])
    need(sorted(name for name, _ in records) == names, "full suite did not execute the exact inventory")
    need(PANICS <= set(names) and f"{len(names)} passed; 0 failed; 0 ignored".encode() in whole,
         "missing annotated case or wrong suite summary")
    return sorted(records)


def test_verdict(artifact, state, out, repo, held):
    exe = held or Path(artifact["executable"])
    need(exe.is_file() and artifact["profile"]["test"], "missing test executable")
    cwd = repo / "crates/ruff_python_ast"
    listing = run([str(exe), "--list", "--format", "terse"], cwd=cwd)
    compress_bytes(out / "test-list.gz", listing)
    inventory = listing.decode().splitlines()
    need(len(inventory) == len(set(inventory)) and all(row.endswith(": test") for row in inventory), "unexpected test inventory")
    names = sorted(row.removesuffix(": test") for row in inventory)
    need(SIZE_TEST in names and (NEW_TEST in names) == (state == "new"), "wrong test generation")
    for label in ([SIZE_TEST, NEW_TEST] if state == "new" else [SIZE_TEST]):
        stdout = run([str(exe), "--exact", label, "--test-threads=1"], cwd=cwd)
        need(("test " + label + " ... ok").encode() in stdout and b"1 passed; 0 failed" in stdout, "selected test did not run")
        compress_bytes(out / (label.split("::")[-1] + ".gz"), stdout)
    completed = subprocess.run([str(exe), "--test-threads=1"], cwd=cwd, capture_output=True, timeout=180)
    compress_bytes(out / "test-suite.gz", completed.stdout)
    compress_bytes(out / "test-suite-stderr.gz", completed.stderr)
    save(out / "test-suite-exit.json", completed.returncode)
    need(completed.returncode == 0, "full unit-test suite reported a failure")
    verdicts = suite_verdicts(completed.stdout, names)
    product = macho_text(exe)
    archive = repo.parent / "receipts/test-executables" / (product["raw"] + ".macho.gz")
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        need(compress_bytes(archive, exe.read_bytes()) == product["raw"], "test executable changed during custody")
    return {**product, "tests": names, "verdicts": verdicts}


def check_verdict(artifacts, artifact, state, work, env, out, held):
    candidates = [Path(p) for p in artifact["filenames"] if p.endswith(".rmeta")]
    need(len(candidates) == 1 and candidates[0].is_file(), "missing actual check metadata")
    meta = held or candidates[0]
    search = sorted({Path(p).parent for a in artifacts for p in a["filenames"] if p.endswith((".rmeta", ".rlib", ".dylib"))})
    args = ["rustc", "+ohm", "--edition=2024", "--crate-type=lib", "--crate-name=layout_reader",
            "--emit=metadata", "--error-format=json", "--extern", "ruff_python_ast=" + str(meta)]
    for p in search:
        args.extend(["-L", "dependency=" + str(p)])
    expected = 64 if state == "old" else 56
    source = work / "layout_reader.rs"
    for x in (expected, 120 - expected):
        source.write_text("const _: [(); %d] = [(); std::mem::size_of::<ruff_python_ast::Expr>()];\n" % x)
        argv = [*args, str(source), "-o", str(work / "layout_reader.rmeta")]
        code, _, stderr, _, _ = capture(argv, work, env, out / ("layout-" + str(x)))
        need(code == (0 if x == expected else 1), "wrong metadata verdict for layout " + str(x))
        if x != expected:
            errors = [json.loads(line) for line in stderr.splitlines()]
            need(any((e.get("code") or {}).get("code") == "E0308" for e in errors), "wrong contrary layout diagnostic")
    return {"raw": sha(meta), "layout": expected}


def result_unit(verb, artifacts):
    selected = [a for a in artifacts if a["target"]["name"] == "ruff_python_ast" and
                ((a["executable"] is not None) if verb == "test" else a["target"]["kind"] == ["lib"])]
    need(len(selected) == 1, "ambiguous Ruff result")
    return selected[0]


def hold(verb, work, label, result):
    status, stream, _, _, _ = result
    need(status == 0, "timed subject failed")
    art = result_unit(verb, typed(stream, True)[0])
    if verb == "test":
        src = Path(art["executable"])
    else:
        src, = [Path(p) for p in art["filenames"] if p.endswith(".rmeta")]
    dest = work / "held" / label / src.name
    dest.parent.mkdir(parents=True)
    fn = ctypes.CDLL(None, use_errno=True).clonefile
    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    need(fn(os.fsencode(src), os.fsencode(dest), 0) == 0, "APFS result clone failed")
    return dest, marker_bytes(Path((work / "zmij-dep-location").read_text()).read_bytes())


def phase(verb, root, work, sdk, env, role, state, label, trace, dest, *, captured=None, held=None):
    ok = state != "invalid"
    status, stdout, stderr, events, stats = captured or capture(ARGS[verb], root / "ruff", env, dest, trace)
    need(status == (0 if ok else 101), f"{verb} {label} exit {status} {stderr[-1024:]!r}")
    artifacts, dirty, codes, roster = typed(stdout, ok)
    units = [a for a in artifacts if a["target"]["name"] == "zmij" and a["target"]["kind"] == ["lib"]]
    need(len(units) == 1 and sha(units[0]["target"]["src_path"]) == ZMIJ_LIB, "wrong locked zmij")
    native = native_rows(events, sdk) if events is not None else None
    if native is not None:
        need(native["cargo"] == 1 and native["full"].count("zmij") == int(not units[0]["fresh"]), "typed/physical count mismatch")
        need(all(link["stock"] for link in native["linkers"]), "unexpected native linker")
    marker, body = held[1] if held else marked(work)
    compress_bytes(dest / "zmij.dep.gz", body)
    verdict = None
    if ok:
        selected = result_unit(verb, artifacts)
        copy = held[0] if held else None
        verdict = (test_verdict(selected, state, dest, root / "ruff", copy) if verb == "test"
                   else check_verdict(artifacts, selected, state, work, env, dest, copy))
        if native is not None and label == "edit" and verb == "test":
            need("ruff_python_ast" in native["full"] and native["linkers"], "real test edit did not compile and link")
    else:
        need("E0425" in codes and BAD_NAME.encode() in stdout, "invalid edit silently passed or wrong diagnostic")
    row = {"verb": verb, "role": role, "state": state, "argv": ARGS[verb], "status": status, "native": native,
           "fresh_zmij": units[0]["fresh"], "marker": marker, "dirty": dirty, "roster": roster,
           "codes": codes, "product": verdict, "cargo": stats, "streams": stats["streams"]}
    save(dest / "verified.json", row)
    return row


def installed(verb, root, role, out, steps, trace, *, timed=False):
    work = root / ("signed-verbs-work" if role == "S" else "native-verbs-work")
    work.mkdir(exist_ok=True)
    sdk = select(root, role)
    env = env_for(work, sdk)
    fresh(work, root / "seed")
    ident = sdk_id(sdk, env)
    driver, = (sdk / "lib").glob("librustc_driver*.dylib")
    stamp = driver.stat().st_ctime_ns
    save(out / "selected-driver.json", {"role":role,"image":ident["driver"],"ctime_ns":stamp})
    rows = {}
    prev = None
    pending = []
    for label, state in steps:
        if state != prev:
            restore(root / "ruff", state)
        if timed and label in ("edit", "repeat-1", "repeat-2"):
            need(trace is None, "observer and clock must run separately")
            dest = out / label
            captured = capture(ARGS[verb], root / "ruff", env, dest, clock=True)
            pending.append((label, dest, captured, hold(verb, work, label, captured)))
            if label == "repeat-2":
                for key, where, cap, snapshot in pending:
                    rows[key] = phase(verb, root, work, sdk, env, role, "new", key, None, where, captured=cap, held=snapshot)
                shutil.rmtree(work / "held")
                pending.clear()
        else:
            rows[label] = phase(verb, root, work, sdk, env, role, state, label, trace, out / label)
        prev = state
    need(not pending, "truncated timed commands")
    need(ident == sdk_id(sdk, env) and driver.stat().st_ctime_ns==stamp, "SDK changed during run")
    retire(work)
    return rows


def signed(root):
    need((root / "receipts/observer.json").is_file(), "signed pilot requires confirmed kernel capture")
    trace = ExecTrace()
    try:
        trace.ready()
        for verb in ARGS:
            out = root / "receipts/signed-verbs" / verb
            refs = {}
            for state in ("old", "new"):
                row = installed(verb, root, "S", out / ("empty-" + state), [("clean", state)], trace)["clean"]
                refs[state] = row["product"]
            steps = [("cold", "old"), ("edit", "new"), ("repeat-1", "new"), ("repeat-2", "new"),
                     ("invalid", "invalid"), ("repair", "new")]
            rows = installed(verb, root, "S", out / "visit", steps, trace)
            comparisons = {}
            for label, row in rows.items():
                item = row["product"]
                if item is None:
                    continue
                ref = refs[row["state"]]
                checks = {k: item[k] == v for k, v in ref.items()}
                need(checks["tests" if verb == "test" else "layout"], "clean behavior mismatch")
                comparisons[label] = checks
            if verb == "test":
                old, new = (set(refs[state]["tests"]) for state in ("old", "new"))
                need(new - old == {NEW_TEST} and not old - new, "unexpected complete inventory change")
            mechanism = all(rows[k]["native"]["full"].count("zmij") == 1 for k in ("repeat-1", "repeat-2"))
            report = {"source": [A, B], "role": "signed-release", "verb": verb, "score": None,
                      "both_repeats_compile_zmij": mechanism, "clean_comparisons": comparisons,
                      "clean": refs, "physical": {k: r["native"] for k, r in rows.items()}}
            save(out / "result.json", report)
            print(verb, "repeat zmij opportunity", mechanism, "clean comparisons", comparisons, flush=True)
    finally:
        trace.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "signed"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.mode == "seed":
        prepare_ruff(root, A, B, source_identity)
    else:
        signed(root)
