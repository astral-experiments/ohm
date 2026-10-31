"""Observe each foreground Cargo on a private target. Retain the operands and executable bytes."""

import gzip
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from acquire import (
    HERE,
    NAME,
    OUT,
    PKG,
    RAW,
    READERS,
    ROOT,
    TARGET,
    environment,
    image,
    installed_tree,
    need,
    save,
    sha,
)
from fixture import (
    BASE,
    BINS,
    PUBLISHED,
    SCHEDULE,
    STATES,
    WORK,
    bin_id,
    copy_sha,
    make_providers,
    project,
    projected_errors,
    put,
)

REG = json.loads((HERE / "registration.json").read_bytes())
CMD = ["cargo", "+" + NAME, "build", "--bins", "--offline", "--message-format=json"]
MARK = b"/dev/null/ohm-recheck-dependent-links"
LINKER_ENV = "CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER"


def sdk(role, select):
    installed = json.loads((OUT / "installed.json").read_bytes())
    name = "bin/cargo"
    if select and not (PKG / name).samefile(RAW / ("cargo-" + role)):
        tmp = PKG / "bin/cargo.qa-next"
        need(not tmp.exists(), "existing unowned tool replacement")
        os.link(RAW / ("cargo-" + role), tmp)
        os.replace(tmp, PKG / name)
    original = installed["installed_tree"]
    now = installed_tree(PKG)
    need(
        set(now) == set(original) and all(now[n] == v for n, v in original.items() if n != name),
        "another installed tool, standard library or symlink changed",
    )
    covered = {}
    for f, h in installed["files"].items():
        expected = installed["cargos"][role]["sha256"] if f == name else h
        need(sha(PKG / f) == expected, ("changed package member", role, f))
        covered[f] = expected
    env = environment()
    v = subprocess.check_output(["cargo", "+" + NAME, "-Vv"], env=env, text=True)
    need(
        "commit-hash: " + READERS[role] + "\n" in v and "host: " + TARGET + "\n" in v,
        "wrong actual Cargo",
    )
    where = subprocess.check_output(
        ["rustup", "which", "--toolchain", NAME, "cargo"], env=env, text=True
    ).strip()
    need(
        Path(where).samefile(PKG / name) and (PKG / name).samefile(RAW / ("cargo-" + role)),
        "rustup selected a different physical Cargo",
    )
    return {
        "cargo": image(PKG / name),
        "rustc": image(PKG / "bin/rustc"),
        "verified_files": covered,
        "version": v,
    }


def original(trace, cmd, cwd, env, out, limit=120):
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    rc = None
    try:
        with (out / "stdout").open("xb") as so, (out / "stderr").open("xb") as se:
            rc, _ = trace.command(
                cmd, env=env, cwd=cwd, out=so, err=se, timeout=limit, observed_rows=rows
            )
    finally:
        (out / "es.json.gz").write_bytes(
            gzip.compress(json.dumps(rows, separators=(",", ":")).encode(), mtime=0)
        )
        save(out / "command.json", {"argv": cmd, "cwd": str(cwd), "code": rc, "events": len(rows)})
    return rc, rows, (out / "stdout").read_bytes(), (out / "stderr").read_bytes()


def keep(body):
    key = copy_sha(body)
    dest = OUT / "native-bodies" / (key + ".gz")
    dest.parent.mkdir(exist_ok=True)
    if not dest.exists():
        dest.write_bytes(gzip.compress(body, compresslevel=3, mtime=0))
    need(gzip.decompress(dest.read_bytes()) == body, "content readback")
    return key


def is_image(row, path):
    file = Path(row["path"])
    return file.is_file() and file.samefile(path)


def output(argv):
    value = [v for k, v in zip(argv, argv[1:]) if k == "-o"]
    need(len(value) == 1, "Xcode ld did not have exactly one output")
    return value[0]


def parents(leaf, rows):
    ancestry = []
    current = leaf
    while True:
        parent = next(
            (r for r in reversed(rows) if r["pid"] == current["ppid"] and r["seq"] < current["seq"]),
            None,
        )
        if parent is None:
            return ancestry
        ancestry.append(parent)
        current = parent


def rust_owner(argv, name):
    return (
        any(a == "--crate-name" and v == name for a, v in zip(argv, argv[1:]))
        or any(
            Path(a).name in (name + ".rlink",)
            or (a.endswith(".rlink") and Path(a).stem.split("-")[0] == name)
            for a in argv
        )
        and any(s in ("-Zlink-only", "link-only") for s in argv)
    )


def classify(rows, cargo, compiler, ld, roots, provider):
    need(
        all(x["pid"] > 0 and x["ppid"] > 0 and x["argv"] for x in rows)
        and all(a["seq"] < b["seq"] for a, b in zip(rows, rows[1:])),
        "invalid ES scope",
    )
    cargo_roots = [
        r
        for r in rows
        if is_image(r, cargo)
        and "build" in r["argv"]
        and "--bins" in r["argv"]
        and "--offline" in r["argv"]
    ]
    need(len(cargo_roots) == 1, "physical Cargo root missing or duplicated")
    rust = [r for r in rows if is_image(r, compiler)]
    links = [r for r in rows if is_image(r, ld) and "-o" in r["argv"]]
    final = {}
    for row in links:
        args = row["argv"]
        product = output(args)
        name = bin_id(product, roots)
        if not name:
            continue
        a = [
            v if k == "-L" else k[2:]
            for k, v in zip(args, args[1:])
            if k == "-L" or k.startswith("-L") and len(k) > 2
        ]
        library = (
            "-lanswer" in args
            or any(k == "-l" and v == "answer" for k, v in zip(args, args[1:]))
            or str(provider / "libanswer.a") in args
        )
        need(
            library and str(provider) in a and name not in final,
            "wrong native archive or duplicate selected linker",
        )
        ancestors = parents(row, rows)
        owner = [r for r in ancestors if r in rust and rust_owner(r["argv"], name)]
        need(
            len(owner) == 1 and cargo_roots[0] in ancestors,
            "no physical Cargo → selected rustc → Xcode ld ancestry",
        )
        final[name] = row | {
            "rustc_parent_pid": owner[0]["pid"],
            "cargo_ancestor_pid": cargo_roots[0]["pid"],
        }
    return {"cargo": cargo_roots, "rustc": rust, "all_ld": links, "final": final}


def witnesses(typed, roster, previous, dirname, cgu):
    result = {}
    for name in BINS:
        (leaf,) = [
            x
            for x in typed
            if x["reason"] == "compiler-artifact"
            and x["target"]["name"] == name
            and x["target"]["kind"] == ["bin"]
        ]
        exe = Path(leaf["executable"])
        need(exe.is_file() and exe.resolve().is_relative_to(WORK / "target"), "foreign Cargo output")
        body = exe.read_bytes()
        h = keep(body)
        need(
            body[:8] == bytes.fromhex("cffaedfe0c000001") and body[12:16] == b"\2\0\0\0",
            "not an ARM64 Mach executable",
        )
        run = subprocess.run([exe], cwd=WORK, capture_output=True, check=False, timeout=10)
        need(
            run.returncode == 0 and not run.stderr and run.stdout in (b"17\n", b"29\n", b"37\n"),
            "wrong native consumer",
        )
        selection = roster["final"].get(name)
        if selection:
            path = output(selection["argv"])
            need(
                Path(path).is_file() and sha(path) == h, "Xcode output differs from published executable"
            )
            dst = dirname / name
            dst.mkdir()
            proof = cgu.witness(ROOT, dst, body, path, linker=selection["argv"])
            previous[name, h] = proof
        else:
            need((name, h) in previous, "no successful genuine prior linker for the selected product")
            proof = previous[name, h]
        need(proof["raw"] == h, "unbound selected binary")
        result[name] = {
            "raw": h,
            "proof": proof,
            "exit": run.returncode,
            "stdout": run.stdout.decode(),
            "value": int(run.stdout),
            "public": str(exe),
        }
    return result


def engine_inputs():
    d = {}
    translated = {}
    seals = {}
    roots = (WORK / "build", WORK / "target")
    for root in roots:
        for f in root.rglob("engine*.d"):
            if f.is_file() and b"engine/src/lib.rs" in (data := f.read_bytes()):
                d[str(f)] = {
                    "body": keep(data),
                    "markers": sorted(
                        {x.decode() for x in data.split() if x.startswith(MARK) and not x.endswith(b":")}
                    ),
                }
        for f in root.rglob("dep-lib-engine"):
            if f.is_file():
                body = f.read_bytes()
                translated[str(f)] = {
                    "body": keep(body),
                    "actual_marker_bytes": MARK in body,
                    "LNK1_footer": body[-40:-36] == b"LNK1",
                }
        for f in root.rglob("seal"):
            if f.parent.name == "native-link" and f.is_file():
                p = f.parent / "product"
                seals[str(f)] = {
                    "seal": keep(f.read_bytes()),
                    "product": sha(p) if p.is_file() else None,
                }
    return {"dep_info": d, "cargo_deps": translated, "seals": seals}


def visit(trace, ld, role, lane, label, state, env, dest, previous, cgu):
    need(shutil.disk_usage(ROOT).free > 4 << 30, "insufficient remaining native workspace")
    (WORK / "links").write_text("")
    rc, rows, so, se = original(trace, CMD, WORK, env, dest)
    typed = [json.loads(s) for s in so.splitlines() if s.strip()]
    need(
        rc in (0, 101) and typed[-1] == {"reason": "build-finished", "success": rc == 0},
        "incomplete ordinary Cargo",
    )
    roots = (WORK / "build", WORK / "target")
    roster = classify(rows, PKG / "bin/cargo", PKG / "bin/rustc", ld, roots, WORK / "native")
    wrapper = (WORK / "links").read_text().splitlines()
    need(all(v == "link" for v in wrapper), "unexpected shell linker observer")
    if lane == "C":
        need(not wrapper and LINKER_ENV not in env, "default linker was interposed")
    else:
        need(
            len(wrapper) == len(roster["all_ld"]),
            "custom shell counter disagrees with physical Xcode links",
        )
    products = witnesses(typed, roster, previous, dest, cgu) if rc == 0 else {}
    inputs = engine_inputs()
    need(inputs["dep_info"] and inputs["cargo_deps"], "missing actual engine producer or Cargo dep-info")
    markers = {m for f in inputs["dep_info"].values() for m in f["markers"]}
    need(
        markers == (set() if lane == "B" else {MARK.decode()}),
        ("unexpected compiler native marker", lane, markers),
    )
    want_footer = lane != "B" and role != "old328"
    need(
        all(
            r["LNK1_footer"] == want_footer and r["actual_marker_bytes"] == want_footer
            for r in inputs["cargo_deps"].values()
        ),
        ("unexpected marker translation in the real Cargo record", role, lane, inputs["cargo_deps"]),
    )
    result = {
        "phase": label,
        "provider": state,
        "code": rc,
        "wrapper_count": len(wrapper),
        "processes": roster,
        "inputs": inputs,
        "products": products,
        "error": (so + b"\n" + se).decode(errors="replace") if rc else None,
    }
    save(dest / "visit.json", result)
    return result


def check(row, expected, links=None):
    if expected in ("malformed", "missing"):
        need(
            row["code"] == 101
            and row["processes"]["final"]
            and projected_errors(row["error"], expected),
            ("missing actual linker rejection", row["phase"], expected, row["code"]),
        )
    else:
        need(
            row["code"] == 0
            and set(row["products"]) == set(BINS)
            and all(x["value"] == expected for x in row["products"].values()),
            ("unexpected binary values", row["phase"], expected, row["code"]),
        )
    if links is not None:
        need(
            len(row["processes"]["all_ld"]) == links
            and set(row["processes"]["final"]) == (set(BINS) if links == 2 else set()),
            ("wrong actual linker counts", row["phase"], links),
        )


def reset_build():
    for p in (WORK / "target", WORK / "build"):
        if p.exists():
            need(
                p.is_dir() and not p.is_symlink() and p.parent == WORK, "attempt to retire foreign build"
            )
            shutil.rmtree(p)


def lane_run(trace, ld, role, lane, cgu):
    out = OUT / role / lane
    out.mkdir(parents=True)
    need(not WORK.exists(), "source root not fresh")
    src = project(lane)
    save(out / "sources.json", src)
    env = environment() | {
        "CARGO_TARGET_DIR": str(WORK / "target"),
        "CARGO_BUILD_BUILD_DIR": str(WORK / "build"),
        "OHM_SMOKE_LINK_LOG": str(WORK / "links"),
    }
    if lane != "C":
        env[LINKER_ENV] = str(WORK / "count-links")
    save(
        out / "environment.json",
        {k: env[k] for k in sorted(env) if k.startswith(("CARGO", "RUST", "OHM", "CI", "GITHUB"))},
    )
    prior = {}
    warm = {}
    ref = {}
    current = None
    info = None
    cases = SCHEDULE if lane != "U-legacy" else SCHEDULE[:6]
    for label, state in cases:
        if state != current:
            info = put(WORK / "native/libanswer.a", state, lane.startswith("U"))
            current = state
        warm[label] = visit(trace, ld, role, lane, label, info, env, out / "warm" / label, prior, cgu)
    # Each reference starts with both stores independently empty, same path/reader inode/source.
    for state in STATES if lane != "U-legacy" else (17, 29, "malformed"):
        reset_build()
        info = put(WORK / "native/libanswer.a", state, False)
        ref[state] = visit(
            trace, ld, role, lane, "empty-" + str(state), info, env, out / "empty" / str(state), {}, cgu
        )
        check(ref[state], state)
    for label, state in cases:
        row = warm[label]
        if lane.startswith("U") and label == "changed29":
            bef = warm["settled17"]["provider"]
            aft = row["provider"]
            need(
                all(bef[k] == aft[k] for k in ("dev", "ino", "bytes", "mtime_ns"))
                and bef["sha256"] != aft["sha256"],
                "weak stale-provider transition",
            )
        if lane == "U-legacy" and label in ("changed29", "unchanged29", "malformed"):
            check(row, 17, 0)
            comparison = ref[17]
        else:
            count = None
            if role == "packaged" and lane == "A" and label == "unchanged17":
                count = 2
            if lane == "C" and label == "changed29":
                count = 2
            if lane == "C" and row["code"] == 0 and not row["processes"]["final"]:
                for bin_name, product in row["products"].items():
                    seal = str(
                        Path(product["proof"]["output"]).with_suffix(".rlink-objects")
                        / "native-link/seal"
                    )
                    need(
                        row["inputs"]["seals"].get(seal, {}).get("product") == product["raw"],
                        ("unexplained stock-linker reuse", label, bin_name),
                    )
            if lane == "B" and label.startswith(("unchanged", "settled")):
                count = 0
            if lane in ("A", "B", "U") and label == "changed29":
                count = 2
            check(row, state, count)
            comparison = ref[state]
        if row["code"] == 0:
            for b in BINS:
                p = row["products"][b]
                r = comparison["products"][b]
                need(
                    p["value"] == r["value"] and cgu.agrees(p["proof"], r["proof"]),
                    ("own empty complete Mach-O mismatch", role, lane, label, b, p["raw"], r["raw"]),
                )
    need(all(sha(WORK / name) == h for name, h in src.items()), "source changed during native fixture")
    return {
        "warm": {
            k: {
                "code": v["code"],
                "ld": len(v["processes"]["all_ld"]),
                "outputs": {k: p["raw"] for k, p in v["products"].items()},
            }
            for k, v in warm.items()
        },
        "empty": {str(k): v["code"] for k, v in ref.items()},
    }


def release_script(trace):
    need(sha(PUBLISHED) == REG["corrected_smoke"]["sha256"], "changed proposed release smoke")
    path = ROOT / "proposed-script"
    dest = OUT / "fourfix/actual-corrected-script"
    args = ["bash", str(PUBLISHED), NAME, str(path)]
    if trace is None:
        dest.mkdir(parents=True)
        with (dest / "stdout").open("xb") as out, (dest / "stderr").open("xb") as err:
            rc = subprocess.run(
                args, cwd=ROOT, env=environment(), stdout=out, stderr=err, timeout=600
            ).returncode
        rows = []
        so = (dest / "stdout").read_bytes()
        save(dest / "command.json", {"argv": args, "cwd": str(ROOT), "code": rc, "events": None})
    else:
        rc, rows, so, _ = original(trace, args, ROOT, environment(), dest, 600)
    # Keep the two negative diagnostic files before accepting the caller's own assertions.
    for f in (path / "missing.log", path / "declared/bad-archive.log"):
        if f.is_file():
            shutil.copyfile(f, dest / f.name)
    entries = [
        x
        for x in rows
        if is_image(x, PKG / "bin/cargo") and "build" in x["argv"] and "--offline" in x["argv"]
    ]
    headings = [s for s in so.decode().splitlines() if s.startswith("Checking ")]
    actual = {}
    for mode in ("executable-default", "executable-relink", "library-default", "library-relink"):
        actual[mode] = (path / mode / "target/debug/reader", "2:37")
    for flavor, value in [("target", "29"), ("marked-target", "37")]:
        for bin_name in BINS:
            actual[flavor + "/" + bin_name] = (path / "declared" / flavor / "debug" / bin_name, value)
    programs = {}
    for key, (binary, required) in actual.items():
        if binary.is_file():
            proc = subprocess.run([str(binary)], cwd=path, capture_output=True, timeout=10)
            programs[key] = {
                "path": str(binary),
                "raw": keep(binary.read_bytes()),
                "exit": proc.returncode,
                "stdout": proc.stdout.decode(),
                "stderr": proc.stderr.decode(),
                "expected": required,
            }
    save(dest / "terminal-programs.json", programs)
    need(
        set(programs) == set(actual)
        and all(
            p["exit"] == 0 and p["stdout"] == p["expected"] + "\n" and not p["stderr"]
            for p in programs.values()
        ),
        "wrong actual final .incbin or archive executable",
    )
    blocks = so.decode().split("Checking ")[1:]
    need(
        len(blocks) == 4
        and all(any("incbin file" in l and "payload.bin" in l for l in b.splitlines()) for b in blocks),
        "missing a genuine assembler diagnostic in the four real transitions",
    )
    need(
        rc == 0
        and headings
        == [
            "Checking executable-default",
            "Checking executable-relink",
            "Checking library-default",
            "Checking library-relink",
        ]
        and (trace is None or len(entries) == 29),
        "frozen release smoke did not finish every Cargo arm",
    )
    need(
        "payload.bin" in (dest / "missing.log").read_text()
        and "libanswer.a" in (dest / "bad-archive.log").read_text(),
        "missing frozen negative-control diagnostics",
    )
    return {
        "code": rc,
        "observer": "kernel-exec" if trace else "ordinary-foreground",
        "cargo": len(entries) if trace else None,
        "script": sha(PUBLISHED),
        "headings": headings,
    }


def main():
    root = Path(os.environ["GITHUB_WORKSPACE"]) / "observer/scripts/ohm-apple-zmij"
    sys.path.insert(0, str(root))
    import cgu_inputs
    from execs import ExecTrace
    from pilot import observer_probe

    need(sha(BASE) == REG["original_smoke"]["sha256"], "release fixture source changed")
    try:
        observer_probe(ROOT)
    except Exception:
        # Keep this unwrapped release-script result even on a machine that cannot calibrate ES.
        dest = OUT / "fourfix"
        dest.mkdir()
        save(dest / "selected-sdk.json", sdk("fourfix", True))
        r = release_script(None)
        save(dest / "foreground-script.json", r)
        raise
    observed = json.loads((OUT / "observer-probe/observed/result.json").read_bytes())
    ld = Path(observed["printed_linker"][0][0]).resolve(strict=True)
    need(sha(ld) == json.loads((OUT / "observer.json").read_bytes())["ld"], "wrong observed platform ld")
    trace = ExecTrace()
    results = {}
    failed = []
    try:
        trace.ready()
        for role in ("fourfix", "packaged", "old328"):
            dest = OUT / role
            dest.mkdir()
            before = sdk(role, True)
            save(dest / "selected-sdk.json", before)
            for lane in REG["readers"][role]:
                if role == "fourfix" and lane == "A":
                    # The actual corrected release script has an independent outcome even if the C fixture refuses.
                    try:
                        make_providers()
                    except Exception as exc:
                        row = {
                            "role": "calibration",
                            "lane": "C-provider",
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                        }
                        failed.append(row)
                        save(OUT / "C-provider-refused.json", row)
                        raise
                try:
                    r = (
                        release_script(trace)
                        if lane == "actual-corrected-script"
                        else lane_run(trace, ld, role, lane, cgu_inputs)
                    )
                    results[role + "/" + lane] = r
                except Exception as exc:
                    row = {
                        "role": role,
                        "lane": lane,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    failed.append(row)
                    save(dest / (lane + "-refused.json"), row)
                finally:
                    if WORK.exists():
                        need(WORK.parent == ROOT and not WORK.is_symlink(), "foreign disposable fixture")
                        shutil.rmtree(WORK)
            after = sdk(role, False)
            need(before == after, "SDK source/physical inode changed inside a role")
    finally:
        trace.close()
        save(
            OUT / "matrix.json",
            {
                "results": results,
                "refused": failed,
                "scope": "actual native arm64 correctness; no clock",
            },
        )
    need(not failed and len(results) == 10, "one or more native arms refused; see complete receipts")


if __name__ == "__main__":
    main()
