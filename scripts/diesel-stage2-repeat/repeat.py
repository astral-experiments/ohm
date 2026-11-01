"""Two fresh collector executions. Only the second has a diagnostic Eprintln companion."""

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intake import BIND, free_guard, need, sha, write
from identity import ALLOW_ENV, BENCHES, ERROR, HEALTHY_A, HOST, PATCHED_B, PERF, PERF_DIESEL, Q, diagnosis, text
from escrow import GIB, keep_graphs, pack, safe_for_clone
from observe import graph_rows, registered
from worker import check_clone, check_paths, command

STAGE0 = "88d9e12ae178fab0fb5cc050a94da85685d449ea"
PAR = Path("source/rust/build")
TOKEN = b'                determinism_env(&mut cmd);\n                let status = cmd.status().expect("failed to spawn");\n                if !status.success() {'
PROBE = b"""                determinism_env(&mut cmd);
                let items: Vec<_> = cmd.get_args().collect();
                let diesel = items.windows(2).any(|a| a[0] == "--crate-name" && a[1] == "diesel")
                    && items.iter().any(|a| *a == "opt-level=3");
                let status = if diesel {
                    observe_diesel(&cmd, "before", 0, -1);
                    let mut child = cmd.spawn().expect("failed to spawn rustc");
                    let id = child.id();
                    observe_diesel(&cmd, "running", id, -1);
                    let status = child.wait().expect("wait for real rustc");
                    observe_diesel(&cmd, "after", id, status.code().unwrap_or(-1));
                    status
                } else {
                    cmd.status().expect("failed to spawn")
                };
                if !status.success() {"""


def read(path):
    return json.loads(path.read_bytes())


def patched_fake(raw):
    need(raw.count(TOKEN) == 1 and b"observe_diesel(" not in raw, "different Eprintln source")
    return raw.replace(TOKEN, PROBE) + (HERE / "witness.rs").read_bytes()


def work():
    w = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    root = Path(os.environ["RUNNER_TEMP"]).resolve() / "diesel-repeat"
    build = w / PAR
    return w, root, root / "reports", build, build / "opt-artifacts/rustc-perf", build / HOST / "stage2"


def source_env(build):
    env = {k: v for k, v in os.environ.items() if k in ALLOW_ENV and k != "GITHUB_STEP_SUMMARY"}
    return env | {
        "GITHUB_ACTIONS": "false",
        "DIST_TRY_BUILD": "0",
        "RUST_BACKTRACE": "1",
        "RUSTC_BOOTSTRAP": "1",
        "TERM": "dumb",
        "RUST_BOOTSTRAP_CONFIG": str(build / "ohm-release-bootstrap.toml"),
        "RUSTC": str(build / HOST / "stage0/bin/rustc"),
    }


def stage0_tools(root, released):
    result = {}
    for name in ("rustc", "cargo"):
        tool = root / "bin" / name
        with tool.open("rb") as f:
            magic = f.read(4)
        result[name] = [tool.stat().st_size, sha(tool)]
        need(
            magic == bytes.fromhex("cffaedfe") and result[name] == released[name]["binary"],
            "wrong published stage0 Mach-O " + name,
        )
    return result


def prepare():
    w, root, r, build, perf, kit = work()
    need(platform.system() == "Darwin" and platform.machine() == "arm64", "not a native Apple silicon runner")
    need(
        text(["git", "-C", perf, "rev-parse", "HEAD"]) == PERF
        and not text(["git", "-C", perf, "status", "--porcelain", "--untracked-files=no"]),
        "different collector checkout",
    )
    for name, h in BIND["collector"]["source_members"].items():
        need(sha(perf / name) == h, "wrong collector/benchmark member " + name)
    for name, tree in BIND["trees"].items():
        need(text(["git", "-C", perf, "rev-parse", "HEAD:collector/compile-benchmarks/" + name]) == tree, name)
    rustc, cargo = (kit / "bin" / x for x in ("rustc", "cargo"))
    driver = kit / BIND["driver_member"]
    for role, p in (("rustc", rustc), ("cargo", cargo), ("driver", driver)):
        need([p.stat().st_size, sha(p)] == BIND["tools"][role], "wrong installed " + role)
    (build / HOST / "stage2-tools-bin").mkdir()
    os.link(cargo, build / HOST / "stage2-tools-bin" / "cargo")
    stage0 = Path(text(["rustup", "which", "rustc", "--toolchain", "1.98.0"])).parent.parent
    (build / HOST / "stage0").symlink_to(stage0, target_is_directory=True)
    bootstrap = (w / "release/bootstrap.toml").read_bytes()
    token = b'description = "Ohm"'
    need(bootstrap.count(token) == 1, "bootstrap description changed")
    config = build / "ohm-release-bootstrap.toml"
    # This describes the already-built instrumented runtime; no bootstrap is invoked.
    config.write_bytes(bootstrap.replace(token, b'description = "ohm-1.99.0-22"'))
    need(sha(config) == BIND["collector"]["bootstrap_config"], "different bootstrap config")
    env = source_env(build)
    env["LLVM_PROFILE_FILE"] = str(root / "identity_%m_%p.profraw")
    versions = {
        k: subprocess.check_output([kit / "bin" / k, "-vV"], env=env, text=True) for k in ("rustc", "cargo")
    }
    need(
        versions["rustc"] == BIND["versions"]["rustc"]
        and versions["cargo"].splitlines()[:5] == BIND["versions"]["cargo"].splitlines()[:5],
        "different toolchain versions",
    )
    need(
        Path(subprocess.check_output([rustc, "--print", "sysroot"], env=env, text=True).strip()).samefile(kit),
        "different runtime sysroot",
    )
    sections = text(["xcrun", "otool", "-l", driver])
    need(
        "sectname __llvm_prf_data" in sections and "sectname __llvm_prf_cnts" in sections, "uninstrumented driver"
    )
    stage0_identity = stage0_tools(stage0, BIND["stage0_distribution"]["installed_tools"])
    prior = text([stage0 / "bin/rustc", "-vV"])
    need(STAGE0 in prior and HOST in prior, "different collector host rustc")
    result = command(
        r / "collector-build",
        [build / HOST / "stage0/bin/cargo", "build", "--locked", "-p", "collector"],
        perf,
        env,
        20 * 60,
    )
    need(result == 0, "pinned collector did not build")
    prefix = perf / "target/debug"
    measured = {"collector": sha(prefix / "collector"), "rustc_fake": sha(prefix / "rustc-fake")}
    for name in ("collector", "rustc-fake"):
        shutil.copy2(prefix / name, root / ("pristine-" + name))
    write(
        r / "actors.json",
        {
            "source": PERF,
            "source_trees": BIND["trees"],
            "actual": measured,
            "matches_prior": {k: measured[k] == BIND["collector"][k] for k in measured},
            "sdk": BIND["tools"],
            "versions": versions,
            "stage0": prior,
            "stage0_bins": stage0_identity,
            "bootstrap": sha(config),
            "xcode": text(["xcodebuild", "-version"]),
            "sdk_path": text(["xcrun", "--sdk", "macosx", "--show-sdk-path"]),
            "clang": text([env["CC"], "--version"]),
            "host": platform.platform(),
            "boot": text(["sysctl", "-n", "kern.bootsessionuuid"]),
        },
    )
    (r / "driver-otool.txt").write_text(sections + "\n")


def roster(log, role):
    observed = sorted(re.findall(r"^Running [^:\n]+: (?:Check|Debug|Opt) \+ [^\n]+$", log, re.M))
    expected = [s for s in BIND["roster"] if role == "primary" or s.startswith("Running diesel-2.2.10: Opt ")]
    need(observed == expected, "different benchmark/profile/scenario/worker roster")
    n = 9 if role == "primary" else 1
    names = set(BIND["trees"]) if n == 9 else {"diesel-2.2.10"}
    for label in ("Executing", "Finished"):
        rows = re.findall(r"^" + label + r" benchmark ([^ ]+) \((\d+)/" + str(n) + r"\)$", log, re.M)
        need(
            len(rows) == n and {b for b, _ in rows} == names and {int(i) for _, i in rows} == set(range(1, n + 1)),
            "incomplete/duplicated " + label + " roster",
        )
    need(
        log.count("Profiling Test with Eprintln") == 1
        and re.findall(r"^Running with (\d+) job\(s\)$", log, re.M) == ["4" if n == 9 else "1"]
        and "collector error:" not in log,
        "contradictory collector status",
    )
    return observed


def instrument(root, r, perf, build):
    src = perf / "collector/src/bin/rustc-fake.rs"
    original = src.read_bytes()
    changed = patched_fake(original)
    env = source_env(build)
    try:
        src.write_bytes(changed)
        code = command(
            r / "observer-build",
            [build / HOST / "stage0/bin/cargo", "build", "--locked", "-p", "collector", "--bin", "rustc-fake"],
            perf,
            env,
            5 * 60,
        )
        need(code == 0, "failed to compile observed Eprintln companion")
        out = perf / "target/debug/rustc-fake"
        actor = {"source": sha(src), "binary": sha(out), "pristine": sha(root / "pristine-rustc-fake")}
        need(actor["pristine"] != actor["binary"], "observed helper not installed")
        write(r / "observer.json", actor)
    finally:
        src.write_bytes(original)
    need(
        not text(["git", "-C", perf, "status", "--porcelain", "--untracked-files=no"]),
        "collector checkout changed",
    )


def failure(tmp, out, logs, rustc):
    # ManuallyDrop in 0a054b0 keeps a FAILED timing root until the collector exits.
    # Capture the whole original before trying to parse or classify the failure.
    paths = sorted(
        p
        for p in tmp.glob(".tmp*")
        if p.is_dir() and not p.is_symlink() and (p / Q).is_file() and (p / "Cargo.toml").is_file()
    )
    write(out / "remaining-diesel-paths.json", list(map(str, paths)))
    saved = {}
    for i, p in enumerate(paths):
        dest = out / ("workspace-" + str(i))
        dest.mkdir()
        try:
            rows = keep_graphs(p, dest / "graphs")
        finally:
            archive = pack(p, dest / "original.tar.gz")
        saved[str(p.resolve())] = {"archive": archive, "graphs": rows, "source": sha(p / Q), "receipt": dest.name}
    write(out / "workspace-custody.json", saved)
    if ERROR not in logs:
        return {"matching_ice": False, "failed_workspace_count": len(saved)}
    original = diagnosis(logs, {"argv": [""] * 9 + [str(rustc)]})
    p = Path(original["cwd"]).resolve()
    need(str(p) in saved and saved[str(p)]["source"] == PATCHED_B, "exact failure workspace not recovered")
    check_paths(p, Path(original["inc"]), original["argv"], tmp)
    need(
        any(
            Path(row["path"]).name == "dep-graph.bin" and not Path(row["path"]).parent.name.endswith("-working")
            for row in saved[str(p)]["graphs"]
        )
        and ERROR in (p / "eprintln").read_text(errors="replace"),
        "failed input/diagnostics differ",
    )
    return {"matching_ice": True, "original": original, "failed_workspace_count": len(saved)}


def lane(role, observer=None):
    w, root, r, build, perf, kit = work()
    dest = r / role
    dest.mkdir()
    scratch = root / (role + "-fresh")
    scratch.mkdir()
    tmp = scratch / "tmp"
    tmp.mkdir()
    prof = scratch / "profiles"
    prof.mkdir()
    env = source_env(build) | {"TMPDIR": str(tmp), "LLVM_PROFILE_FILE": str(prof / "default_%m_%p.profraw")}
    rustc = kit / "bin/rustc"
    actor = perf / "target/debug/collector"
    pristine = read(r / "actors.json")["actual"]
    need(
        sha(actor) == pristine["collector"] and sha(perf / "target/debug/rustc-fake") == pristine["rustc_fake"],
        "original collector helpers not in place",
    )
    args = [
        "profile_local",
        "eprintln",
        rustc,
        "--id",
        "Test",
        "--cargo",
        build / HOST / "stage2-tools-bin/cargo",
        "--profiles",
        "Check,Debug,Opt" if role == "primary" else "Opt",
        "--scenarios",
        "All",
        "--exact-match",
        BENCHES if role == "primary" else "diesel-2.2.10",
        "--jobs",
        "4" if role == "primary" else "1",
    ]
    results = perf / "results"
    need(not results.exists(), "results from another timing root")
    if role == "primary":
        free_guard(root, 46 * GIB)
        run = [build / HOST / "stage0/bin/cargo", "run", "-p", "collector", "--bin", "collector", "--", *args]
    else:
        instrument(root, r, perf, build)
        need(sha(actor) == pristine["collector"], "collector changed outside Eprintln companion")
        (dest / "events").mkdir()
        env.update(
            OHM_DIESEL_WORK=str(root),
            OHM_DIESEL_RECORD=str(dest),
            OHM_DIESEL_PYTHON=sys.executable,
            OHM_DIESEL_OBSERVER=str(observer or HERE / "observe.py"),
            OHM_DIESEL_RUSTC=str(rustc),
        )
        run = [actor, *args]
    write(dest / "environment.json", env)
    code = None
    try:
        code = command(dest / "execution", run, perf, env, (49 if role == "primary" else 15) * 60)
    finally:
        if results.exists():
            shutil.move(results, dest / "eprintln-results")
        if role == "focused":
            shutil.copy2(root / "pristine-rustc-fake", perf / "target/debug/rustc-fake")
        if code != 0:
            streams = [dest / "execution/stderr", dest / "execution/stdout"]
            log = "\n".join(p.read_text(errors="replace") for p in streams if p.is_file())
            write(dest / "failure.json", failure(tmp, dest, log, rustc))
    if code != 0:
        raise ValueError("natural collector failed; preserve terminal originals, stop repetitions")
    logs = (
        (dest / "execution/stderr").read_text(errors="replace")
        + "\n"
        + (dest / "execution/stdout").read_text(errors="replace")
    )
    schedule = roster(logs, role)
    outputs = sorted((dest / "eprintln-results").glob("eprintln-*"))
    need(outputs, "collector did not write Eprintln outputs")
    files = {p.name: p.stat().st_size for p in sorted(prof.glob("*.profraw"))}
    need(files and all(files.values()), "missing raw instrumented profiles")
    write(dest / "profiles.json", files)
    need(not list(tmp.glob(".tmp*/incremental-state")), "unreported timing root after successful collector")
    profdata = kit / "lib/rustlib" / HOST / "bin/llvm-profdata"
    merged = dest / "gathered.profdata"
    need(
        command(dest / "merge", [profdata, "merge", "-o", merged, prof], perf, source_env(build), 10 * 60) == 0
        and merged.stat().st_size > 0,
        "bad merged instrumented profile",
    )
    write(
        dest / "natural.json",
        {
            "code": code,
            "source": PERF,
            "actor": sha(actor),
            "rustc": sha(rustc),
            "helper": pristine["rustc_fake"] if role == "primary" else read(r / "observer.json")["binary"],
            "roster": schedule,
            "eprintln": {p.name: [p.stat().st_size, sha(p)] for p in outputs},
            "profiles": len(files),
            "raw_bytes": sum(files.values()),
            "merged": [merged.stat().st_size, sha(merged)],
            "llvm_profdata": sha(profdata),
        },
    )
    # Keep the full profile stream for failures. A completed merge closes this job-owned input.
    if role == "primary":
        shutil.rmtree(prof)


def positive_rows(events, rustc):
    rows = []
    for folder in events.iterdir():
        a, running, b = (read(folder / (x + ".json")) for x in ("before", "running", "after"))
        need(
            a["wrapper"] == b["wrapper"] == running["wrapper"] == int(folder.name)
            and a["pid"] == 0
            and b["pid"] == running["pid"] > 0
            and b["code"] == 0
            and a["code"] == -1
            and a["monotonic_ns"] < b["monotonic_ns"],
            "incomplete native invocation",
        )
        need(
            all(a[k] == b[k] for k in ("argv", "cwd", "source", "source_sha256", "incremental"))
            and Path(a["argv"][0]).samefile(rustc)
            and running["process"]["path"]
            and Path(running["process"]["path"]).samefile(rustc)
            and [running["process"][k] for k in ("dev", "ino", "size", "sha256")]
            == [rustc.stat().st_dev, rustc.stat().st_ino, rustc.stat().st_size, sha(rustc)],
            "parent argv, PID, observed physical compiler or source differs",
        )
        registered(a["argv"], a["environment"])
        need(
            a["source_sha256"] == {"A": HEALTHY_A, "B": PATCHED_B}[a["source"]], "different recorded source bytes"
        )
        signatures = {
            k.removeprefix("default_").removesuffix(f"_{b['pid']}.profraw")
            for k, v in b["profile_files"].items()
            if k.endswith(f"_{b['pid']}.profraw") and v[0] > 0
        }
        need(
            set(BIND["prior_evidence"]["runtime_profile_signatures"]) <= signatures,
            "instrumented modules not witnessed for the actual rustc PID",
        )
        need(
            {Path(k).suffix for k, v in b["outputs"].items() if v[0] > 0} == {".rmeta", ".rlib"},
            "missing successful full Diesel products",
        )
        rows.append((a, b))
    rows.sort(key=lambda r: r[0]["monotonic_ns"])
    first = [(r["source"], r["incremental"]) for r, _ in rows]
    natural = [("A", False), ("A", True), ("B", True)]
    need(first in (natural, natural[:2] + [("A", True)] + natural[2:]), "unexpected actual native phase sequence")
    need(
        len({r["cwd"] for r, _ in rows}) == 1 and len({r["pid"] for _, r in rows}) == len(rows),
        "different physical timing roots or reused native PIDs",
    )
    for i, (a, b) in enumerate(rows):
        if not a["incremental"]:
            continue
        need(bool(b["graphs"]) and (i != 1 or not a["graphs"]), "first incremental A was not an empty seed")
        if i > 1:
            need(
                a["graphs"] == rows[i - 1][1]["graphs"] and a["monotonic_ns"] > rows[i - 1][1]["monotonic_ns"],
                "later rustc did not receive the preceding real compiler's exact finalized graphs",
            )
    need(len(rows[-1][0]["graphs"]) == 1, "ambiguous previous graph in the loaded-B proof")
    return rows


def witness():
    _, root, r, _, _, kit = work()
    dest = r / "focused"
    read(r / "primary/natural.json")
    read(dest / "natural.json")
    rows = positive_rows(dest / "events", kit / "bin/rustc")
    from eager_header import scan
    from graph_forensics import original, read as read_structure

    native_profiles = {name: info for _, after in rows for name, info in after["profile_files"].items()}
    need(
        set(native_profiles) == {p.name for p in (dest / "native-profiles").iterdir()},
        "native profile inventory changed",
    )
    for name, info in native_profiles.items():
        p = dest / "native-profiles" / name
        need([p.stat().st_size, sha(p)] == info, "native profile no longer matches the child PID")
    raw = {row["sha256"]: row["size"] for pair in rows for event in pair for row in event["graphs"]}
    need(raw and {p.name for p in (dest / "graphs").iterdir()} == set(raw), "missing or extra graph file")
    readings = {}
    for digest, size in sorted(raw.items()):
        graph = dest / "graphs" / digest
        need(
            graph.stat().st_size == size and sha(graph) == digest,
            "physical graph disagrees with recorded PID digest",
        )
        with original(graph) as mapped:
            eager = scan(mapped, 362)
            full = read_structure(mapped, 362)
        readings[digest] = {"eager": eager, "full": full}
    write(r / "graph-structure.json", readings)
    need(
        all(
            v["eager"].get("all_node_headers_passed") is True
            and v["full"].get("accepted") is True
            and v["full"]["version"] == 10
            and v["full"]["version_string"] == "rustc-perf"
            for v in readings.values()
        ),
        "physical instrumented graph failed source-bound decoding",
    )
    record = rows[-1][0]
    cwd = Path(record["cwd"])
    slot = root / "before-patched-B"
    inc = cwd / "incremental-state"
    need(
        cwd.parent == (root / "focused-fresh/tmp").resolve() and not cwd.exists() and slot.is_dir(),
        "cannot reuse the original B logical path",
    )
    safe_for_clone(slot)
    subprocess.run(["/bin/cp", "-cRp", slot, cwd], check=True)
    check_clone(slot, cwd)
    incoming = graph_rows(cwd, inc, dest / "graphs")

    def bodyset(xs):
        return [(x["path"], x["size"], x["sha256"]) for x in xs]

    need(
        bodyset(incoming) == bodyset(record["graphs"]) and sha(cwd / Q) == PATCHED_B,
        "different B source or prior data",
    )
    argv = record["argv"]
    need(not any("assert-incr-state" in x for x in argv), "observer accidentally enabled in natural workload")
    output = Path(argv[argv.index("--out-dir") + 1])
    need(output.resolve().is_relative_to(cwd) and output.is_dir(), "reader output escapes preserved root")
    for n in output.glob("libdiesel-*"):
        if n.suffix in (".rmeta", ".rlib"):
            n.unlink()
    profiles = root / "loaded-reader-profiles"
    profiles.mkdir()
    env = record["environment"] | {"LLVM_PROFILE_FILE": str(profiles / "default_%m_%p.profraw")}
    code = command(r / "loaded-B-export", [*argv, "-Zassert-incr-state=loaded"], cwd, env, 5 * 60)
    products = {
        p.name: [p.stat().st_size, sha(p)]
        for p in output.glob("libdiesel-*")
        if p.is_file() and p.suffix in (".rmeta", ".rlib")
    }
    need(
        code == 0 and {Path(k).suffix for k, v in products.items() if v[0] > 0} == {".rmeta", ".rlib"},
        "restored B did not load the observed prior session and re-emit its library",
    )
    write(
        r / "graph-witness.json",
        {
            "actual_rustcs": [
                {
                    "pid": b["pid"],
                    "source": a["source"],
                    "before": a["graphs"],
                    "after": b["graphs"],
                    "outputs": b["outputs"],
                    "profiles": b["profile_files"],
                }
                for a, b in rows
            ],
            "unmodified_unchanged_rustc_observed": len(rows) == 4,
            "incoming": incoming,
            "source_sha256": sha(cwd / Q),
            "loaded_control": products,
            "matches_observed_B": products == rows[-1][1]["outputs"],
            "source": BIND["head"],
            "sdk_zip_sha256": BIND["official"]["digest"],
        },
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["prepare"]:
        prepare()
    elif sys.argv[1:] in (["primary"], ["focused"]):
        lane(sys.argv[1])
    elif sys.argv[1:] == ["witness"]:
        witness()
    else:
        raise SystemExit("repeat.py prepare | primary | focused | witness")
