"""Run unqualified release-14 Ruff workspace commands after complete historical edits."""

import argparse, hashlib, importlib.util, json, os, resource, shutil, subprocess, time, threading
from pathlib import Path

here = Path(__file__).resolve().parent
base = here.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


proc = load("historical_processes", here / "historical-processes.py")
dr = load("dr", base / "dr-holdout.py")
n = load("native", base / "full-toolchain-preflight.py")
p = load("protocol", base / "measure.py")
GIB = 1 << 30


def timed_capture(repo, env, command, directory, target):
    assert shutil.disk_usage(target).free > n.FLOOR_GIB * n.GIB
    directory.mkdir()
    out = directory / "stdout.jsonl"
    with out.open("wb") as f, (directory / "stderr").open("wb") as err:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter_ns()
        rc = subprocess.run(
            [
                "cargo",
                "+ohm",
                *command,
                "--locked",
                "--offline",
                "--message-format=json",
            ],
            cwd=repo,
            env=env,
            stdout=f,
            stderr=err,
        ).returncode
        end = time.perf_counter_ns()
        used = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert rc == 0, (directory, (directory / "stderr").read_text()[-200:])
    assert shutil.disk_usage(target).free > n.FLOOR_GIB * n.GIB
    n.save(
        directory / "time.json",
        dict(
            elapsed_ns=end - start,
            child_cpu_seconds=(used.ru_utime - usage.ru_utime)
            + (used.ru_stime - usage.ru_stime),
        ),
    )
    graph = []
    outputs = {}
    dirty = []
    for line in out.read_text().splitlines():
        x = json.loads(line)
        if x["reason"] != "compiler-artifact":
            continue
        t = x["target"]
        key = json.dumps(
            [x["package_id"], t["name"], t["kind"], x["features"], x["profile"]],
            separators=(",", ":"),
            sort_keys=True,
        )
        graph.append(key)
        if not x["fresh"]:
            dirty.append(t["name"])
        if x["executable"]:
            path = Path(x["executable"])
            assert key not in outputs
            outputs[key] = {
                "file": str(path),
                "sha256": n.sha(path),
                "bytes": path.stat().st_size,
            }
    r = {"graph": sorted(graph), "outputs": outputs, "dirty": dirty}
    n.save(directory / "result.json", r)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["build", "test"])
    ap.add_argument("action", choices=["native", "count-audit", "measure", "wall"])
    ap.add_argument("--control", type=Path, required=True)
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--middle", type=Path)
    ap.add_argument("--replicate", type=int, choices=[0, 1], default=0)
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--state", type=Path, required=True)
    a = ap.parse_args()
    mode = a.mode
    prior = a.state.resolve()
    config = json.loads((prior / "paths.json").read_text())
    out = prior / "results"
    out.mkdir(exist_ok=True)
    linker = prior / "ld.bfd"
    driver = prior / "clang"
    repo = Path(config["ruff"])
    run = lambda *v: subprocess.check_output(["git", *v], cwd=repo).decode().strip()
    assert run("rev-parse", "HEAD") == n.RUFF and not run("status", "--porcelain")
    corpus = prior / "fixtures"
    (fixture,) = [
        x
        for x in json.loads((corpus / "manifest.json").read_text())["fixtures"]
        if x["label"] == a.fixture
    ]
    patch = corpus / (a.fixture + ".patch")
    assert n.sha(patch) == fixture["patch_sha256"]
    paths = [repo / x for x in fixture["paths"]]
    assert all(p.exists() for p in paths)
    original = {p: p.read_bytes() for p in paths}
    run("apply", "--reverse", "--check", str(patch))
    run("apply", "--reverse", str(patch))
    historical = {p: (p.read_bytes() if p.exists() else None) for p in paths}
    run("apply", "--check", str(patch))
    run("apply", str(patch))
    assert all(v == p.read_bytes() for p, v in original.items())
    raw = {"original": original, "changed": historical}
    state = "original"
    env = dict(
        os.environ,
        RUSTUP_HOME=str(prior / "rustup"),
        CARGO_HOME=config["cargo_home"],
        CARGO_BUILD_BUILD_DIR=config["shared"],
        CARGO_TARGET_DIR=config["target"],
        CARGO_BUILD_JOBS="4",
        CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=str(driver),
        CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST="all",
        CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST="all",
        CARGO_TERM_COLOR="never",
        RUSTUP_AUTO_INSTALL="0",
        SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt",
        SSL_CERT_DIR="/etc/ssl/certs",
    )
    collector = prior / ("historical-collectors-" + mode)
    env.update(
        RUSTC=str(prior / "rustup/toolchains/ohm/bin/rustc"),
        RUSTC_WRAPPER=str(collector / "rustc-wrapper"),
    )
    env.update(OHM_DRRUN=config["drrun"], OHM_PIDCOUNTER=config["pidcounter"])
    target = Path(config["target"])
    runtime = Path(config["toolchain"])
    inputs = {
        "rustc": runtime / "bin/rustc",
        "driver": next((runtime / "lib").glob("librustc_driver*.so")),
        "cargo": prior / "rustup/toolchains/ohm/bin/cargo",
    }
    ids = n.identities(inputs)
    assert (
        n.sha(inputs["cargo"])
        == "211465de4b9e4589da2be06871acd9304dd3b94c849c1304f723484cb4f71dfc"
    )
    assert "--ld-path=" + str(linker) in driver.read_text()
    actual = n.sha(linker)
    previous = next(
        x
        for x in [a.control, a.middle, a.candidate]
        if x and x.exists() and n.sha(x) == actual
    )
    tool = {"control": a.control.resolve()}
    tool.update({"candidate": a.candidate.resolve()} if a.candidate else {})
    tool.update({"middle": a.middle.resolve()} if a.middle else {})
    cmd = ["build"] if mode == "build" else ["test", "--no-run"]
    num, exes = (501, 6) if mode == "build" else (619, 102)

    def invoke(label, arm, edit, method="native"):
        nonlocal state
        assert n.identities(inputs) == ids
        if n.sha(linker) != n.sha(tool[arm]):
            p.replace(tool[arm], linker)
        if state != edit:
            run("apply", *(["--reverse"] if edit == "changed" else []), str(patch))
            state = edit
        assert all(
            (path.read_bytes() if path.exists() else None) == data
            for path, data in raw[state].items()
        )
        dest = out / label
        prefix = []
        if method == "trace":
            prefix = [
                "strace",
                "-f",
                "-qq",
                "-e",
                "trace=execve",
                "-s",
                "300",
                "-o",
                str(dest / "execs"),
            ]
        local = dict(env)
        stop = threading.Event()
        seen = {}
        monitor = None
        if method == "counter":
            prefix = [here / "counter-cargo"]
            local["OHM_HIST_IR"] = str(dest)
            monitor = threading.Thread(
                target=dr.observe_maps,
                args=(dest, stop, seen, {"cargo": inputs["cargo"]}),
                daemon=True,
            )
            monitor.start()
        try:
            r = (
                timed_capture(repo, local, cmd, dest, target)
                if method == "wall"
                else n.capture(repo, local, cmd, dest, target, prefix=prefix)
            )
        finally:
            stop.set()
            if monitor:
                monitor.join()
        if method == "counter":
            n.save(
                dest / "observed-cargo-maps.json",
                {key: sorted(value) for key, value in seen.items()},
            )
            clang = Path(shutil.which("clang"))
            reference = proc.native_roster(
                out / ("native-control-" + edit),
                inputs["cargo"],
                inputs["rustc"],
                clang,
                linker,
            )
            counts = proc.observations(
                dest,
                reference,
                inputs["cargo"],
                inputs["rustc"],
                clang,
                linker,
                inputs["driver"],
                seen,
            )
            n.save(dest / "processes.json", counts)
        assert n.identities(inputs) == ids and (len(r["graph"]), len(r["outputs"])) == (
            num,
            exes,
        )
        print(label, "dirty", len(r["dirty"]), r["dirty"][:16], flush=True)
        return r

    def oracle(r, edit):
        ref = json.loads(
            (out / ("native-control-" + edit) / "result.json").read_bytes()
        )
        d = n.compare(ref, r)
        assert not d, (
            edit,
            [(json.loads(x["target"])[1] if "target" in x else "graph") for x in d],
        )
        assert sorted(ref["dirty"]) == sorted(r["dirty"])

    def retain(label):
        folder = out / label
        if folder.exists():
            archive = out / "interrupted-attempts"
            archive.mkdir(exist_ok=True)
            folder.rename(
                archive / (str(time.time_ns()) + "-" + label.replace("/", "-"))
            )

    try:
        if a.action == "native":
            if not (out / "native-control-original/result.json").exists():
                invoke("native-control-warm", "control", "original")
                for e in ["changed", "original"]:
                    invoke("native-control-" + e, "control", e, "trace")
            for extra in ["middle", "candidate"]:
                if extra in tool:
                    for e in ["changed", "original"]:
                        label = "native-" + extra + "-" + e
                        done = out / label / "result.json"
                        if done.exists():
                            oracle(json.loads(done.read_bytes()), e)
                            continue
                        retain(label)
                        other = "changed" if e == "original" else "original"
                        reset = invoke(
                            "prime-native-" + str(time.time_ns()), extra, other
                        )
                        assert not n.compare(
                            json.loads(
                                (
                                    out / ("native-control-" + other) / "result.json"
                                ).read_bytes()
                            ),
                            reset,
                        )
                        r = invoke(label, extra, e, "trace")
                        oracle(r, e)
        elif a.action in ["wall", "measure"]:
            if a.action == "measure":
                assert json.loads((out / "count-audit.json").read_text())[
                    "passed"
                ] == sorted(tool)
            assert len(tool) == 3 and all(
                (out / ("native-" + arm + "-" + e) / "result.json").is_file()
                for arm in tool
                for e in raw
            )
            plan_path = out / ("wall-plan-" + str(a.replicate) + ".json")
            plan = json.loads(plan_path.read_bytes())
            assert plan["hashes"] == {arm: n.sha(z) for arm, z in tool.items()}
            assert plan["patch"] == fixture["patch_sha256"] and len(
                plan["affinity"]
            ) == len(os.sched_getaffinity(0))
            kind = "ir" if a.action == "measure" else "wall"
            method = "counter" if a.action == "measure" else "wall"
            L = out / (kind + "-" + str(a.replicate))
            L.mkdir(exist_ok=True)
            warm = invoke(
                kind + "-" + str(a.replicate) + "/warm-" + str(time.time_ns()),
                "control",
                "original",
                "native",
            )
            assert not n.compare(
                json.loads((out / "native-control-original/result.json").read_bytes()),
                warm,
            )
            data = L / "observations.jsonl"
            saved = (
                [json.loads(line) for line in data.read_text().splitlines()]
                if data.exists()
                else []
            )
            with data.open("a", buffering=1) as observations:
                for i, block in enumerate(plan["blocks"]):
                    for j, arm in enumerate(block["arms"]):
                        edit = block["edit"]
                        other = "changed" if edit == "original" else "original"
                        tag = kind + "-" + str(a.replicate) + f"/{i:02d}-{j}"
                        k = i * 3 + j
                        if k < len(saved):
                            priorrow = saved[k]
                            assert (
                                priorrow["block"],
                                priorrow["position"],
                                priorrow["arm"],
                                priorrow["edit"],
                            ) == (i, j, arm, edit)
                            rr = json.loads((out / tag / "result.json").read_bytes())
                            oracle(rr, edit)
                            details = json.loads(
                                (
                                    out
                                    / tag
                                    / (
                                        "processes.json"
                                        if method == "counter"
                                        else "time.json"
                                    )
                                ).read_bytes()
                            )
                            assert all(
                                priorrow[key] == val
                                for key, val in details.items()
                                if key != "processes"
                            )
                            continue
                        retain(tag + "-reset")
                        retain(tag)
                        reset = invoke(tag + "-reset", arm, other, "native")
                        assert not n.compare(
                            json.loads(
                                (
                                    out / ("native-control-" + other) / "result.json"
                                ).read_bytes()
                            ),
                            reset,
                        )
                        r = invoke(tag, arm, edit, method)
                        oracle(r, edit)
                        more = json.loads(
                            (
                                out
                                / tag
                                / (
                                    "processes.json"
                                    if method == "counter"
                                    else "time.json"
                                )
                            ).read_bytes()
                        )
                        more.pop("processes", None)
                        row = dict(
                            block=i,
                            position=j,
                            edit=edit,
                            arm=arm,
                            units=len(r["graph"]),
                            dirty=sorted(r["dirty"]),
                            executables=len(r["outputs"]),
                            outputs_sha256=hashlib.sha256(
                                json.dumps(
                                    sorted(
                                        (k, v["sha256"])
                                        for k, v in r["outputs"].items()
                                    ),
                                    separators=(",", ":"),
                                ).encode()
                            ).hexdigest(),
                            **more,
                        )
                        print(json.dumps(row), file=observations)
                        print(
                            tag,
                            arm,
                            row.get("total", row.get("elapsed_ns")),
                            flush=True,
                        )
        elif a.action == "count-audit":
            assert all(
                (out / ("native-" + z + "-original/result.json")).exists() for z in tool
            )
            for arm in ["control", "middle", "candidate"]:
                if (out / ("count-" + arm + "-changed/processes.json")).exists():
                    oracle(
                        json.loads(
                            (
                                out / ("count-" + arm + "-changed/result.json")
                            ).read_bytes()
                        ),
                        "changed",
                    )
                    continue
                retain("count-" + arm + "-reset")
                retain("count-" + arm + "-changed")
                r = invoke("count-" + arm + "-reset", arm, "original", "native")
                assert not n.compare(
                    json.loads(
                        (out / "native-control-original/result.json").read_bytes()
                    ),
                    r,
                )
                r = invoke("count-" + arm + "-changed", arm, "changed", "counter")
                oracle(r, "changed")
            n.save(
                out / "count-audit.json", {"passed": sorted(tool), "true_native": True}
            )
    finally:
        if state == "changed":
            run("apply", str(patch))
        assert all(
            data == path.read_bytes() for path, data in original.items()
        ) and not run("status", "--porcelain")
        if n.sha(linker) != actual:
            p.replace(previous, linker)


if __name__ == "__main__":
    main()
