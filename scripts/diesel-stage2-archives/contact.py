"""One genuine focused collector, followed by four independently restored compiler inputs and a closed-FD control."""

import fcntl
import gzip
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "diesel-stage2-repeat")]
import capture
import jobserver
import products
import repeat as prior
from escrow import facts, free_guard, pack, safe_for_clone
from identity import PATCHED_B, Q, need, sha, write
from intake import BIND
from observe import graph_rows, physical
from worker import check_clone

ROLES = ("ordinary-1", "ordinary-2", "loaded", "cold", "closed-fds")


def read(p):
    return json.loads(p.read_bytes())


def validate_graphs(events, rustc):
    rows = prior.positive_rows(events, rustc)
    dest = events.parent
    profiles = {k: v for _, after in rows for k, v in after["profile_files"].items()}
    need({p.name for p in (dest / "native-profiles").iterdir()} == set(profiles), "native profile set changed")
    for name, expected in profiles.items():
        p = dest / "native-profiles" / name
        need([p.stat().st_size, sha(p)] == expected, "instrumented native profile changed")
    from eager_header import scan
    from graph_forensics import original, read as structural

    graphs = {}
    for before, after in rows:
        for info in before["graphs"] + after["graphs"]:
            digest = info["sha256"]
            if digest in graphs:
                continue
            p = dest / "graphs" / digest
            need(p.stat().st_size == info["size"] and sha(p) == digest, "graph digest does not match real compiler")
            with original(p) as data:
                eager = scan(data, 362)
                full = structural(data, 362)
            need(
                eager.get("all_node_headers_passed")
                and full.get("accepted")
                and full["version"] == 10
                and full["version_string"] == "rustc-perf",
                "rejected prior graph",
            )
            graphs[digest] = {"eager": eager, "full": full}
    return rows, graphs


def focused():
    _, root, r, _, _, kit = prior.work()
    arm = r / "archives/original"
    arm.mkdir(parents=True)
    write(
        arm / "workflow.json",
        {
            key: os.environ[key]
            for key in (
                "GITHUB_REPOSITORY",
                "GITHUB_SHA",
                "GITHUB_REF",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "RUNNER_OS",
                "RUNNER_ARCH",
            )
        },
    )
    gate = root / "archive-handoff"
    gate.mkdir(mode=0o700)
    # A dedicated read-only handoff crosses the Actions upload barrier. SCM_RIGHTS
    # transfers the original kernel pipe objects. No token is consumed by this broker.
    with (gate / "broker.log").open("x") as log:
        broker_env = {k: v for k, v in os.environ.items() if k in ("PATH", "LC_ALL", "RUNNER_TRACKING_ID")}
        broker = subprocess.Popen(
            [sys.executable, "-IB", HERE / "jobserver.py", "serve", root],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
            env=broker_env,
        )
    end = time.monotonic() + 8
    while not Path(jobserver.address(root)).exists() and broker.poll() is None and time.monotonic() < end:
        time.sleep(0.02)
    need(Path(jobserver.address(root)).is_socket() and broker.poll() is None, "jobserver handoff did not start")
    prior.lane("focused", observer=HERE / "capture.py")
    stages, graphs = validate_graphs(r / "focused/events", kit / "bin/rustc")
    before, after = stages[-1]
    literal = read(arm / "natural-B/members.json")
    need(
        literal["archive"] != read(arm / "seed.json")["initial_outputs"][Path(literal["paths"][0]).name]
        and literal["standalone_metadata"]
        != read(arm / "seed.json")["initial_outputs"][Path(literal["paths"][1]).name],
        "natural real edit did not replace both earlier products",
    )
    text = (r / "focused/events" / str(after["wrapper"]) / "rustc.stderr").read_bytes()
    need(b"failed to connect to jobserver" not in text, "natural rustc already had a bad jobserver")
    write(arm / "seed-graphs.json", graphs)
    write(
        arm / "completed.json",
        {
            "native_pid": after["pid"],
            "actual": [[a["source"], a["incremental"], b["pid"]] for a, b in stages],
            "before": before,
            "rustc": BIND["tools"]["rustc"],
            "driver": BIND["tools"]["driver"],
            "cargo": BIND["tools"]["cargo"],
            "archive": literal["archive"],
            "metadata": literal["standalone_metadata"],
            "prior_graph": before["graphs"],
            "collector": read(r / "focused/natural.json"),
            "natural_jobserver": read(arm / "natural-jobserver.json"),
        },
    )


def external_inputs(rec):
    args = rec["argv"]
    cwd = Path(rec["cwd"]).resolve(strict=True)
    result = {}
    for i, token in enumerate(args):
        if token == "--extern":
            name, path = args[i + 1].split("=", 1)
            p = Path(path)
            need(p.is_file() and p.resolve(strict=True).is_relative_to(cwd), "foreign explicit dependency")
            result[name] = {"path": str(p), "bytes": p.stat().st_size, "sha256": sha(p)}
    need("diesel_derives" in result, "missing native proc-macro dependency")
    return result


def cold_unit(cwd, rec):
    argv = rec["argv"]
    inc = cwd / "incremental-state"
    out = products.outputs(argv)[0].parent
    need(
        inc.resolve() == inc
        and inc.is_dir()
        and out.resolve() == out
        and out.is_relative_to(cwd / "target")
        and out.name == "out"
        and out.parent.parent.name == "diesel",
        "unsafe cold-unit cleanup",
    )
    previous, dirs = facts(inc)
    need(any(key.endswith("dep-graph.bin") for key in previous), "cold control had no warm input to remove")
    shutil.rmtree(inc)
    inc.mkdir()
    removed = []
    for p in sorted((cwd / "target").rglob("*")):
        if p.is_file() and (
            (p.name.startswith("libdiesel-") and p.suffix in (".rlib", ".rmeta"))
            or p.name in ("libdiesel.rlib", "libdiesel.rmeta")
            or p.parent == out
        ):
            need(not p.is_symlink() and p.resolve().is_relative_to(cwd), "foreign cold product")
            removed.append([str(p.relative_to(cwd)), p.stat().st_size, sha(p)])
            p.unlink()
    need(
        not list(inc.iterdir()) and not list(out.iterdir()) and all(not p.exists() for p in products.outputs(argv)),
        "cold reset incomplete",
    )
    return {
        "removed_incremental_paths": len(previous),
        "removed_incremental_unique_bytes": dirs,
        "removed_outputs": removed,
    }


def prepare_inputs(root, dest, seed):
    slot = root / "before-patched-B"
    safe_for_clone(slot)
    earlier = set()
    for role in ROLES:
        folder = dest / role
        folder.mkdir()
        staged = root / ("fresh-input-" + role)
        need(not staged.exists(), "old role input")
        free_guard(root, 1 << 30)
        subprocess.run(["/bin/cp", "-cRp", slot, staged], check=True)
        check_clone(slot, staged)
        manifest = folder / "incoming-files.json.gz"
        state = capture.clone_matches(slot, staged, manifest)
        need(state == seed["normalized"], "different source/physical session")
        rows = json.loads(gzip.decompress(manifest.read_bytes()))
        identities = {(v["dev"], v["ino"]) for v in rows.values() if v["type"] == "file"}
        need(not identities.intersection(earlier), "pristine inputs share a regular file inode")
        earlier.update(identities)


def run_one(role, rec, seed, held, root, dest):
    folder = dest / role
    cwd = Path(rec["cwd"])
    slot = root / "before-patched-B"
    need(
        cwd.name.startswith(".tmp") and cwd.parent == (root / "focused-fresh/tmp").resolve() and not cwd.exists(),
        "wrong original logical path",
    )
    free_guard(root, 1 << 30)
    (root / ("fresh-input-" + role)).rename(cwd)
    try:
        current, _ = facts(cwd)
        staged = json.loads(gzip.decompress((folder / "incoming-files.json.gz").read_bytes()))
        need(current == staged, "parked inputs changed between their admission and their actual turn")
        state = capture.projection(current)
        need(state == seed["normalized"] and sha(cwd / Q) == PATCHED_B, "source/physical session changed")
        original = {p.name: [p.stat().st_size, sha(p)] for p in products.outputs(rec["argv"])}
        need(original == seed["initial_outputs"], "one replay inherited products from another")
        incoming = graph_rows(cwd, cwd / "incremental-state", root / "reports/focused/graphs")
        key = lambda r: (r["path"], r["size"], r["sha256"])
        need(
            list(map(key, incoming)) == list(map(key, rec["graphs"])) and len(incoming) == 1,
            "wrong previous A graph",
        )
        ext = external_inputs(rec)
        cold = cold_unit(cwd, rec) if role == "cold" else None
        need(external_inputs(rec) == ext, "cold reset changed compiler externs")
        write(
            folder / "incoming.json",
            {
                "normalized": state,
                "prior_A_graphs": incoming,
                "original_outputs": original,
                "externs": ext,
                "source": sha(cwd / Q),
                "cold_unit_reset": cold,
                "cwd": str(cwd),
            },
        )
        saved = folder / "input.json"
        write(saved, rec)
        expected = rec["argv"] + (["-Zassert-incr-state=loaded"] if role == "loaded" else [])
        proc, profiles = direct(role, saved, rec, held, folder)
        lib = products.save(expected, cwd, folder / "products")
        capture.emitted(expected, (folder / "stderr").read_bytes())
        message = b"failed to connect to jobserver" in (folder / "stderr").read_bytes()
        need(message == (role == "closed-fds"), "wrong jobserver acceptance or incidental warning")
        need(
            lib["paths"] == list(map(str, products.outputs(rec["argv"])))
            and all(
                old != new
                for old, new in zip(
                    (original[Path(x).name] for x in lib["paths"]),
                    (lib["archive"], lib["standalone_metadata"]),
                    strict=True,
                )
            ),
            "failed to regenerate active outputs",
        )
        need(external_inputs(rec) == ext and sha(cwd / Q) == PATCHED_B, "native input or fixture changed")
        outgoing = [
            {"path": str(p.relative_to(cwd)), "size": p.stat().st_size, "sha256": sha(p)}
            for p in sorted((cwd / "incremental-state").glob("diesel-*/s-*/dep-graph.bin"))
            if not p.parent.name.endswith("-working")
        ]
        need(outgoing and all(v["size"] for v in outgoing), "direct compiler did not publish a finalized graph")
        write(
            folder / "complete.json",
            {
                "role": role,
                "pid": proc,
                "profiles": profiles,
                "argv": expected,
                "cwd": str(cwd),
                "archive": lib["archive"],
                "metadata": lib["standalone_metadata"],
                "bad_jobserver_warning": message,
                "outgoing": outgoing,
            },
        )
    except BaseException:
        if cwd.is_dir():
            pack(cwd, folder / "failed-workspace.tar.gz")
        raise
    finally:
        # Each untouched role was already held independently before the first
        # compiler was invoked. Keep completed roles outside the active path.
        if (folder / "complete.json").exists():
            parked = root / ("comparison-complete-" + role)
            need(not parked.exists(), "completed role already parked")
            cwd.rename(parked)
    need(capture.projection(facts(slot)[0]) == seed["normalized"], "master snapshot was modified")


def direct(role, record, rec, high, folder):
    fds = () if role == "closed-fds" else tuple(high)
    receipt = folder / "exec.json"
    argv = [sys.executable, "-IB", HERE / "jobserver.py", "exec", record, receipt, role, *map(str, fds)]
    exe = Path(rec["argv"][0])
    expectation = [exe.stat().st_dev, exe.stat().st_ino, exe.stat().st_size, sha(exe)]
    need(expectation[2:] == BIND["tools"]["rustc"], "different restored rustc")
    active = None
    deadline = time.monotonic() + 5 * 60
    with (folder / "stdout").open("xb") as out, (folder / "stderr").open("xb") as err:
        proc = subprocess.Popen(
            argv,
            cwd=rec["cwd"],
            env=rec["environment"],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
            pass_fds=fds,
        )
        try:
            while proc.poll() is None:
                if active is None:
                    p = physical(proc.pid)
                    if p.get("path") and Path(p["path"]).samefile(exe):
                        need(
                            [p[k] for k in ("dev", "ino", "size", "sha256")] == expectation,
                            "native exec identity changed",
                        )
                        active = {"kernel": p, "observed_fds": jobserver.process_list(proc.pid)}
                need(time.monotonic() < deadline, "independent compiler timed out")
                free_guard(folder)
                time.sleep(0.02 if active is None else 0.15)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    write(folder / "actual-process.json", {"pid": proc.pid, "code": proc.returncode, "physical": active})
    need(proc.returncode == 0 and active and receipt.is_file(), "failed or unattributed actual compiler")
    start = read(receipt)
    expected = rec["argv"] + (["-Zassert-incr-state=loaded"] if role == "loaded" else [])
    need(
        start["pid"] == proc.pid
        and start["cwd"] == rec["cwd"]
        and start["env"] == rec["environment"]
        and start["argv"] == expected,
        "different actual startup",
    )
    if fds:
        need(
            jobserver.identity(start["fds"]) == jobserver.identity(jobserver.describe(fds)),
            "lost original open file descriptions",
        )
    else:
        need(start["fds"] is None, "dead FD control acquired a live jobserver")
    prof = Path(rec["environment"]["LLVM_PROFILE_FILE"]).parent
    profiles = {p.name: [p.stat().st_size, sha(p)] for p in prof.glob("*_" + str(proc.pid) + ".profraw")}
    required = {
        "default_" + m + "_" + str(proc.pid) + ".profraw"
        for m in BIND["prior_evidence"]["runtime_profile_signatures"]
    }
    need(
        required <= profiles.keys() and all(v[0] > 0 for v in profiles.values()),
        "missing physical instrumented module for native PID",
    )
    snapshot = folder / "profiles"
    snapshot.mkdir()
    for name in profiles:
        os.link(prof / name, snapshot / name)
    return proc.pid, profiles


def trials():
    _, root, r, _, _, kit = prior.work()
    arm = r / "archives"
    orig = arm / "original"
    dest = arm / "replays"
    dest.mkdir()
    finished = read(orig / "completed.json")
    seed = read(orig / "seed.json")
    rec = finished["before"]
    for name, key in (("bin/rustc", "rustc"), ("bin/cargo", "cargo"), (BIND["driver_member"], "driver")):
        p = kit / name
        need([p.stat().st_size, sha(p)] == BIND["tools"][key], "changed tool " + key)
    held, fds = jobserver.exchange(root, "claim")
    need(
        len(fds) == 2
        and jobserver.identity(held) == jobserver.identity(finished["natural_jobserver"]["descriptors"]),
        "fresh or different pipe",
    )
    high = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, max(jobserver.numbers(rec["environment"])) + 32) for fd in fds]
    for fd in fds:
        os.close(fd)
    write(
        dest / "claimed.json",
        {"original": finished["natural_jobserver"], "claim": held, "same_file_descriptions": True},
    )
    try:
        prepare_inputs(root, dest, seed)
        for role in ROLES:
            run_one(role, rec, seed, high, root, dest)
    finally:
        for fd in high:
            os.close(fd)
    inv = {"natural": read(orig / "natural-B/members.json")}
    inv.update({role: read(dest / role / "products/members.json") for role in ROLES})
    comparison = {
        a + " vs " + b: products.compare(x, inv[b])
        for i, (a, x) in enumerate(inv.items())
        for b in list(inv)[i + 1 :]
    }
    write(dest / "comparison.json", comparison)
    bodies = {"natural": (orig / "natural-B" / Path(inv["natural"]["paths"][0]).name).read_bytes()}
    bodies.update(
        {role: (dest / role / "products" / Path(inv[role]["paths"][0]).name).read_bytes() for role in ROLES}
    )
    proof = {
        a + " vs " + b: products.suffix_proof(bodies[a], bodies[b], x, inv[b])
        for i, (a, x) in enumerate(inv.items())
        for b in list(inv)[i + 1 :]
    }
    write(dest / "name-proof.json", proof)


if __name__ == "__main__":
    if sys.argv[1:] == ["focused"]:
        focused()
    elif sys.argv[1:] == ["trials"]:
        trials()
    elif sys.argv[1:] == ["stop"]:
        _, root, *_ = prior.work()
        path = root / "archive-handoff/sock"
        if path.exists():
            jobserver.exchange(root, "stop")
    else:
        raise SystemExit(2)
