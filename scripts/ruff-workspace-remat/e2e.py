"""Signed Ruff #27836 test-build replay. Only Cargo within an edit history is metered."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tomllib


SCHEMA = "ohm-ruff-27836-test-no-run-v1"
OLD = "ec92fb2b9c451acb04b43dbbf173b6a236eee67e"
NEW = "f9115b8deefa56b18b79449f8acafe25475c54d3"
LOCK = "e37036fd781578faeafa15fc0a09b938dd78bd160c8e3be958dfb74eb975f61c"
SESSION = "crates/ty_server/src/session.rs"
HARNESS = "crates/ty_server/tests/e2e/main.rs"
FOLDERS = "crates/ty_server/tests/e2e/workspace_folders.rs"
LIB = "crates/ty_server/src/lib.rs"
PATHS = (SESSION, HARNESS, FOLDERS)
ADDED = "workspace_folders::single_file_workspace"
SIBLING = "workspace_folders::initialize_multiple_workspace_folders"
WARNING = "0:0..0:7[WARNING]: Name `missing` used when not defined"
INVALID = b"\nconst OHM_E2E_STUDY_INVALID: () = 1u32;\n"
FLAGS = {"normal": [], "defer": ["-Cllvm-args=-late-remat-update-threshold=1"]}
CARGO = ["cargo", "+ohm", "test", "-p", "ty_server", "--test", "e2e", "--no-run",
         "--locked", "--offline", "-j4", "--message-format=json"]
EDIT = ("old", "new", "unchanged", "invalid", "repair")
CLEAN = ("clean-new", "negative", "restored-new")


def need(condition, context):
    if not condition:
        raise ValueError(context)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def enroll(r, source, registry):
    need(r.git(source, "rev-parse", "HEAD").decode().strip() == NEW
         and r.git(source, "rev-parse", NEW + "^").decode().strip() == OLD
         and not r.git(source, "status", "--porcelain=v1", "--untracked-files=all"), "wrong or dirty Ruff checkout")
    changed = r.git(source, "diff", "--name-status", OLD, NEW).decode().splitlines()
    need(sorted(changed) == sorted("M\t" + path for path in PATHS), changed)
    blobs = {rev: {p: r.git(source, "show", rev + ":" + p) for p in PATHS} for rev in (OLD, NEW)}
    for rev in (OLD, NEW):
        lock = r.git(source, "show", rev + ":Cargo.lock")
        entries = [v for v in tomllib.loads(lock.decode())["package"] if "checksum" in v]
        archives = {v["name"] + "-" + v["version"] + ".crate": v["checksum"] for v in entries}
        need(digest(lock) == LOCK and len(entries) == len(archives) == 505 and archives == registry,
             "incorrect or different Ruff registry closure")
    sibling = ("fn " + SIBLING.split("::")[-1] + "()").encode()
    need(all(blobs[rev][FOLDERS].count(sibling) == 1 for rev in (OLD, NEW))
         and b"fn single_file_workspace()" not in blobs[OLD][FOLDERS]
         and blobs[NEW][FOLDERS].count(b"fn single_file_workspace()") == 1
         and blobs[NEW][FOLDERS].count(json.dumps(WARNING).encode()) == 1, "wrong new warning oracle")
    return blobs


def source_state(r, repo, blobs, phase, write=False):
    effective = {p: (OLD if phase == "old" or phase == "negative" and p == SESSION else NEW) for p in PATHS}
    expected = {p: blobs[v][p] + (INVALID if phase == "invalid" and p == SESSION else b"")
                for p, v in effective.items()}
    for name, body in expected.items():
        path = repo / name
        need(path.is_file() and path.resolve() == path, ("unexpected file", path))
        if write and path.read_bytes() != body:
            path.write_bytes(body)
        need(path.read_bytes() == body, ("unexpected source bytes", phase, name))
    dirty = sorted(p for p in PATHS if expected[p] != blobs[OLD][p])
    need(r.git(repo, "rev-parse", "HEAD").decode().strip() == OLD
         and not r.git(repo, "diff", "--cached", "--name-only")
         and r.git(repo, "diff", "--name-only", "HEAD").decode().splitlines() == sorted(dirty)
         and not r.git(repo, "ls-files", "--others", "--exclude-standard")
         and r.sha(repo / "Cargo.lock") == LOCK, ("unregistered effective checkout", phase))
    return {"base": OLD, "effective": effective, "invalid": phase == "invalid", "dirty_paths": dirty,
            "sha256": {p: digest(b) for p, b in expected.items()},
            "physical": {p: [(repo/p).stat().st_ino, (repo/p).stat().st_mtime_ns,
                             (repo/p).stat().st_ctime_ns] for p in PATHS}}


def artifact_key(pkg, target, features, test):
    return json.dumps([pkg, target["name"], target["kind"], target["crate_types"], target["src_path"],
                       sorted(features), test], separators=(",", ":"))


def graph_units(graph, repo, flags):
    us = graph["units"]
    need(graph["version"] == 1 and len(graph["roots"]) == 1, "test graph root/version")
    root, = graph["roots"]
    seen, todo = set(), [root]
    while todo:
        i = todo.pop()
        need(type(i) is int and 0 <= i < len(us), ("invalid unit edge", i))
        if i not in seen:
            seen.add(i)
            todo.extend(d["index"] for d in us[i]["dependencies"])
    need(len(seen) == len(us), "unreachable Cargo units")
    owners, expected = {}, Counter()
    root_pkg = us[root]["pkg_id"]
    for i, u in enumerate(us):
        mode, target, profile = u["mode"], u["target"], u["profile"]
        need(mode in ("build", "test", "run-custom-build"), ("unknown unit", mode))
        is_owner = u["pkg_id"] == root_pkg
        observed = profile.get("rustflags", [])
        need(observed == (flags if is_owner else []), ("wrong rustc flags", target["name"], observed))
        if mode == "run-custom-build":
            need(not is_owner and target["kind"] == ["custom-build"], ("unexpected build script", i))
            continue
        key = artifact_key(u["pkg_id"], target, u["features"], mode == "test")
        expected[key] += 1
        if is_owner:
            name = target["name"]
            signature = (mode, target["kind"], target["crate_types"], Path(target["src_path"]))
            required = {"ty_server": ("build", ["lib"], ["lib"], repo/LIB),
                        "e2e": ("test", ["test"], ["bin"], repo/HARNESS)}
            need(name in required and name not in owners and signature == required[name]
                 and profile["opt_level"] == "1", ("wrong owner", i, signature, profile))
            owners[name] = key
        if mode == "test":
            need(i == root and is_owner and target["name"] == "e2e", ("other harness unit", i))
    need(set(owners) == {"ty_server", "e2e"}, ("owner units", owners))
    return expected, owners


def verbose_owners(stderr, repo, flags, compiler=None):
    owners = {}
    for line in stderr.splitlines():
        if "Running " not in line or "--crate-name " not in line:
            continue
        prefix = "Running " + chr(96)
        need(prefix in line and line.endswith(chr(96)), ("unrecognized verbose rustc argv", line))
        args = shlex.split(line.split(prefix, 1)[1][:-1])
        crate_at = args.index("--crate-name")
        if compiler is not None:
            need(any(Path(a).is_absolute() and Path(a).is_file() and Path(a).samefile(compiler)
                     for a in args[:crate_at] if "=" not in a), ("wrong physical rustc", args[:crate_at]))
        name = args[crate_at + 1]
        opts = ["-C" + args[i+1] if a == "-C" else a for i, a in enumerate(args) if a.startswith("-C")]
        root_path = {"ty_server": LIB, "e2e": HARNESS}.get(name)
        own = root_path is not None and any(a in (root_path, str(repo/root_path)) for a in args)
        treatments = [v for v in opts if "late-remat-update-threshold" in v]
        need(treatments == (flags if own else []), ("unexpected effective LLVM option", name, treatments))
        if own:
            need(name not in owners and "-Copt-level=1" in opts and ("--test" in args) == (name == "e2e"),
                 ("duplicate or wrong owner invocation", name))
            owners[name] = args
    need(set(owners) == {"ty_server", "e2e"}, ("missing verbose owner", list(owners)))
    return owners


def products(rows, expected, owners, phase, work, repo):
    good = phase != "invalid"
    need(rows and rows[-1] == {"reason": "build-finished", "success": good}
         and sum(r["reason"] == "build-finished" for r in rows) == 1, "wrong Cargo verdict")
    permitted = {"compiler-artifact", "compiler-message", "build-script-executed", "build-finished"}
    need(all(r["reason"] in permitted for r in rows), "unknown Cargo JSON reason")
    errors = [r for r in rows if r["reason"] == "compiler-message" and r["message"]["level"] == "error"]
    artifacts = [r for r in rows if r["reason"] == "compiler-artifact"]
    if not good:
        coded = [e for e in errors if e["message"].get("code")]
        need(len(coded) == 1 and coded[0]["message"]["code"]["code"] == "E0308"
             and coded[0]["target"]["src_path"] == str(repo/LIB), ("wrong source error", coded))
        spans = [s for s in coded[0]["message"]["spans"] if s["is_primary"]]
        need(len(spans) == 1 and spans[0]["file_name"] in (SESSION, str(repo/SESSION))
             and any(t["text"].strip() == INVALID.decode().strip() for t in spans[0]["text"]), "wrong E0308 primary")
    else:
        need(not errors, "successful Cargo with error")
    keys = []
    dirty = []
    binary = None
    for a in artifacts:
        need(type(a["fresh"]) is bool and type(a["profile"]["test"]) is bool, "artifact flags")
        key = artifact_key(a["package_id"], a["target"], a["features"], a["profile"]["test"])
        keys.append(key)
        if not a["fresh"]:
            dirty.append(key)
        if key == owners["e2e"]:
            need(good and binary is None and a["executable"] in a["filenames"], "missing/duplicate test product")
            binary = Path(a["executable"])
            need(binary.is_absolute() and binary.resolve().is_relative_to(work)
                 and any(binary.resolve().is_relative_to(work/x) for x in ("target", "build"))
                 and binary.is_file() and os.access(binary, os.X_OK), ("non-private test product", binary))
    actual = Counter(keys)
    need(actual == expected if good else not actual - expected, ("wrong Cargo artifact inventory", phase, expected-actual, actual-expected))
    if good:
        need(binary is not None, "no test executable")
    else:
        need(not (actual.keys() & owners.values()), "invalid build emitted an owner product")
    if phase in ("old", "clean-new"):
        need(Counter(dirty) == expected, "unexpected fresh artifact in empty roots")
    if phase == "new":
        need(set(owners.values()).issubset(dirty), ("missing real edit owner", dirty))
    return sorted(dirty), sorted(keys), binary


def test_names(stdout):
    names = []
    for line in stdout.splitlines():
        if not line.strip() or re.fullmatch(r"\d+ tests?, \d+ benchmarks?", line):
            continue
        need(line.endswith(": test"), ("unexpected harness listing", line))
        names.append(line.removesuffix(": test"))
    need(len(names) == len(set(names)) and SIBLING in names, "bad native harness inventory")
    return sorted(names)


def executed(stdout, stderr, name, negative):
    output = stdout + "\n" + stderr
    result = "FAILED" if negative else "ok"
    need(re.search(r"(?m)^test "+re.escape(name)+r" \.\.\. "+result+r"$", stdout)
         and re.search(r"(?m)^running 1 test$", stdout), ("wrong named test", name, stdout[-550:]))
    summary = ("FAILED. 0 passed; 1 failed" if negative else "ok. 1 passed; 0 failed")
    need("test result: " + summary in stdout, ("wrong test verdict", stdout[-550:]))
    if negative:
        need("workspace_folders.rs:" in output and "assertion " in output, "failure came from a different source")
        m = re.search(r'(?m)^\s*left: (".*")\s*\n\s*right: (".*")\s*$', output)
        need(m is not None and json.loads(m[2]) == WARNING and json.loads(m[1]) != WARNING,
             ("historical session did not fail on the warning assertion", output[-1500:]))
        return json.loads(m[1])
    return None


def compiler_arm(r, w, manifest, arm, env):
    if manifest is None:
        return env, FLAGS[arm], None, {"mode": "signed-profile-control", "rustc": str(w.SDK/"bin/rustc")}
    need(manifest["schema"] == "ohm-matched-rustcs-v1" and set(manifest["arms"]) == set(FLAGS),
         "unrecognized matched compiler manifest")
    spec = manifest["arms"][arm]
    root = Path(spec["root"]).resolve(strict=True)
    files = spec["files"]
    need("bin/rustc" in files and any("librustc_driver" in k for k in files)
         and any(Path(k).name.startswith("libLLVM") for k in files), "missing compiler/driver/LLVM attestation")
    for rel, value in files.items():
        f = root/rel
        need(not Path(rel).is_absolute() and ".." not in Path(rel).parts and f.resolve().is_relative_to(root)
             and re.fullmatch("[0-9a-f]{64}", value) and r.sha(f) == value, ("unverified compiler input", rel))
    cc = root/"bin/rustc"
    selected = {**env, "RUSTC": str(cc)}
    selected["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(root/"lib"), env.get("LD_LIBRARY_PATH", ""))))
    actual = subprocess.check_output([cc, "--print", "sysroot"], env=selected, text=True).strip()
    need(Path(actual).samefile(root), ("wrong selected codegen sysroot", actual, root))
    version = subprocess.check_output([cc, "-vV"], env=selected, text=True)
    loaded = subprocess.check_output(["ldd", cc], env=selected, text=True)
    for family in ("librustc_driver", "libLLVM"):
        matches = [Path(m[1]) for line in loaded.splitlines()
                   if family in line and (m := re.search(r"=> (/\S+) \(", line))]
        need(matches and all(any(p.samefile(root/f) for f in files) for p in matches),
             ("unanalyzed compiler library", family, loaded))
    return selected, [], cc, {"mode": "matched-rustc", "root": str(root), "files": files, "version": version,
                              "loaded_compiler_libraries": loaded}


def compiler_manifest(r, manifest):
    if manifest is not None and not isinstance(manifest, dict):
        manifest = r.read(Path(manifest))
    if manifest is not None:
        need(manifest["schema"] == "ohm-matched-rustcs-v1" and set(manifest["arms"]) == set(FLAGS),
             "unrecognized matched compiler manifest")
        def compiler_files(arm):
            return sorted(sha for rel, sha in manifest["arms"][arm]["files"].items()
                          if rel == "bin/rustc" or Path(rel).name.startswith(("librustc_driver", "libLLVM")))
        need(compiler_files("normal") != compiler_files("defer"), "identical compiler binaries cannot test treatment")
    return manifest


def run(r, args, w, registry, expected_registry, original_cargo, clock):
    """Use the already authenticated original study, signed toolchain, clock and four CPUs."""
    source, scratch, out = (v.resolve() for v in (args.e2e_source, args.scratch, args.results))
    need(not scratch.exists() and not out.exists()
         and all(not p.is_relative_to(q) and not q.is_relative_to(p)
                 for p in (scratch, out) for q in (source, args.original.resolve(), args.qa.resolve()))
         and not scratch.is_relative_to(out) and not out.is_relative_to(scratch), "test paths overlap")
    order = args.order.split(",")
    need(sorted(order) == sorted(FLAGS) and r.ARMS == FLAGS, "unknown treatment order")
    manifest = compiler_manifest(r, getattr(args, "e2e_rustcs", None))
    blobs = enroll(r, source, expected_registry)
    original_sdk = w.acquire.verify_sdk(w.SDK)
    scratch.mkdir()
    out.mkdir()
    work = scratch/"work"
    work.mkdir()
    repo = scratch/"ruff"
    refs = Path(r.git(source, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    subprocess.run(["git", "init", "--quiet", repo], check=True)
    (repo/".git/objects/info/alternates").write_text(str(refs/"objects")+"\n")
    r.git(repo, "checkout", "--quiet", "--detach", OLD)
    base_env = {**w.ENV, "CARGO_HOME": str(work/"cargo-home"), "CARGO_TARGET_DIR": str(work/"target"),
           "CARGO_BUILD_BUILD_DIR": str(work/"build")}
    profile = scratch/"profile.toml"
    study_mode = "matched-rustc" if manifest is not None else "signed-profile-control"
    r.put(out/"identity.json", {"schema": SCHEMA, "source": [OLD, NEW], "lock": LOCK,
          "driver": r.sha(Path(__file__)), "clock": r.sha(clock), "command": CARGO, "study_mode": study_mode,
          "order": order, "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
          "source_common_dir": str(refs), "warning": WARNING,
          "blobs": {v: {p: digest(b) for p, b in files.items()} for v, files in blobs.items()}})
    norm_graph = None
    catalogs, dirt, observed = {}, {}, []
    for ix, arm in enumerate(order):
        env, flags, compiler, identity = compiler_arm(r, w, manifest, arm, base_env)
        cli = CARGO
        if manifest is None and not (args.trace_unchanged and arm == "normal"):
            profile.write_text("[profile.test.package.ty_server]\nrustflags = " + json.dumps(flags) + "\n")
            cli = [*CARGO[:2], "-Zprofile-rustflags", "--config", str(profile), *CARGO[2:]]
        r.put(out/(arm+"-compiler.json"), identity)
        for history, phases in (("edit", EDIT), ("clean", CLEAN)):
            case = out/f"{ix}-{arm}-{history}"
            case.mkdir()
            source_state(r, repo, blobs, phases[0], write=True)
            with r.empty_roots(work, case):
                home = work/"cargo-home"
                (home/"registry").mkdir()
                for kind in ("index", "cache"):
                    r.run(["cp", "-a", "--reflink=auto", original_cargo/"registry"/kind, home/"registry"/kind],
                          repo, env, case/("prepare-"+kind), work, out)
                for name in ("config", "config.toml"):
                    if (original_cargo/name).is_file():
                        shutil.copy2(original_cargo/name, home/name)
                r.run(["cargo", "+ohm", "fetch", "--locked", "--offline"], repo, env, case/"fetch", work, out)
                need(registry(home) == expected_registry, "private registry custody")
                r.run([*cli[:2], "-Zunstable-options", *cli[2:], "--unit-graph"], repo, env, case/"graph", work, out)
                graph = r.read(case/"graph/outer.stdout")
                expected, owners = graph_units(graph, repo, flags)
                normalized = json.loads(json.dumps(graph))
                for u in normalized["units"]:
                    u["profile"].pop("rustflags", None)
                if norm_graph is None:
                    norm_graph = normalized
                need(normalized == norm_graph, "different test unit graph")
                r.put(case/"units.json", {"schema": SCHEMA, "owner_keys": owners, "inventory": expected})
                for phase in phases:
                    dest = case/phase
                    before = source_state(r, repo, blobs, phase, write=True)
                    verbose = phase == "clean-new"
                    count = r.run([*cli, "-vv"] if verbose else cli, repo, env, dest, work, out,
                                  exit_code=101 if phase == "invalid" else 0,
                                  clock=clock if history == "edit" else None)
                    need(before == source_state(r, repo, blobs, phase), "Cargo changed test sources")
                    r.put(dest/"source.json", before)
                    raw = (dest/"outer.stdout").read_bytes()
                    rows = r.cargo_rows(raw, graph) if verbose else r.cargo_rows(raw)
                    w.ownership.check_roots(rows, work)
                    dirty, keys, binary = products(rows, expected, owners, phase, work, repo)
                    if verbose:
                        r.put(dest/"actual-owner-argv.json", verbose_owners((dest/"outer.stderr").read_text(), repo, flags, compiler))
                    result = {"schema": SCHEMA, "arm": arm, "phase": phase, "history": history, "cargo": count,
                              "dirty": dirty, "artifact_keys": keys, "error": "E0308" if phase == "invalid" else None}
                    if binary:
                        binary_sha = r.sha(binary)
                        r.run([binary, "--list", "--format", "terse", "--color", "never"], repo, env, dest/"list", work, out)
                        names = test_names((dest/"list/outer.stdout").read_text())
                        version = "old" if phase == "old" else "new"
                        need((ADDED in names) == (version == "new"), ("stale executable", phase, binary))
                        if version in catalogs:
                            need(names == catalogs[version], "different native test catalog")
                        catalogs[version] = names
                        test = SIBLING if version == "old" else ADDED
                        negative = phase == "negative"
                        r.run([binary, "--exact", test, "--test-threads", "1", "--nocapture", "--format", "pretty",
                               "--color", "never"], repo, env, dest/"execute", work, out, exit_code=101 if negative else 0)
                        left = executed((dest/"execute/outer.stdout").read_text(), (dest/"execute/outer.stderr").read_text(),
                                        test, negative)
                        need(r.sha(binary) == binary_sha and before == source_state(r, repo, blobs, phase),
                             "running the original test changed its harness or tracked sources")
                        result.update(executable_sha256=binary_sha, executable_bytes=binary.stat().st_size,
                                      test_count=len(names), catalog_sha256=digest(("\n".join(names)+"\n").encode()),
                                      test=test, negative_left=left, expected_warning=WARNING if version == "new" else None)
                    result["dirty_owners"] = sorted(name for name, key in owners.items() if key in dirty)
                    if phase == "unchanged":
                        result["freshness_outcome"] = "forced-rebuild" if dirty else "fresh"
                    dirt.setdefault(phase, {})[arm] = dirty
                    observed.append(result)
                    r.put(dest/"qualified.json", result)
                if args.trace_unchanged and history == "edit" and arm == "normal":
                    import link_trace
                    import sys
                    need(manifest is None and cli == CARGO, "trace requires the ordinary signed compiler")
                    link_trace.collect(r, sys.modules[__name__], w, cli, repo, env, work, case/"link-trace",
                                       graph, expected, owners, blobs, dirt["unchanged"][arm], binary)
                need(registry(home) == expected_registry, "modified private registry")
        need(compiler_arm(r, w, manifest, arm, base_env)[3] == identity, "compiler changed during its histories")
    need(set(catalogs["new"]) - set(catalogs["old"]) == {ADDED}
         and set(catalogs["old"]).issubset(catalogs["new"]), "unexpected Ruff test inventory change")
    comparison = {}
    for arm in order:
        arm_rows = {q["phase"]: q for q in observed if q["arm"] == arm}
        need(set(arm_rows) == set(EDIT+CLEAN)
             and arm_rows["old"]["executable_sha256"] != arm_rows["new"]["executable_sha256"]
             and ("e2e" in arm_rows["unchanged"]["dirty_owners"]
                  or arm_rows["new"]["executable_sha256"] == arm_rows["unchanged"]["executable_sha256"]),
             "unexpected old/new/unchanged executable identity")
        comparison[arm] = {p: arm_rows[p]["executable_sha256"] == arm_rows["clean-new"]["executable_sha256"]
                           for p in ("new", "unchanged", "repair", "restored-new")}
    need(w.acquire.verify_sdk(w.SDK) == original_sdk and registry(original_cargo) == expected_registry
         and enroll(r, source, expected_registry) == blobs, "changed original inputs")
    r.put(out/"catalogs.json", catalogs)
    r.put(out/"observations.json", observed)
    r.put(out/"accepted.json", {"schema": SCHEMA, "phases": list(EDIT+CLEAN), "rows": len(observed),
                                "binary_matches_independent_clean": comparison, "study_mode": study_mode,
                                "dirty_arm_differences": {p: v for p, v in dirt.items() if v["normal"] != v["defer"]},
                                "unchanged_regression": bool(set(dirt["unchanged"]["defer"])
                                                              - set(dirt["unchanged"]["normal"])),
                                "observation_sha256": r.sha(out/"observations.json")})
