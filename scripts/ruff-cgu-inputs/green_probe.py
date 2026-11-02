"""Build and audit the single, signed workspace compiler observation."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "cgu-probe"
DRIVER = "4c8ccf0072e8f382a3a3756fd60e46936a2bd206996201c55caffe58d29725db"


def require(test, reason):
    if not test:
        raise ValueError(reason)


def sha(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def environment(root, stage, work, signed):
    kit = root / "green-kit"
    return dict(
        OHM_CGUR_LOADER="LD_PRELOAD=" + str(kit / "launch.so"),
        VALGRIND_LIB=str(kit / "vglib"),
        OHM_CGUR_SIGNED=str(signed),
        OHM_CGUR_STAGE=str(stage),
        OHM_CGUR_WORK=str(work),
        OHM_CGUR_STORE=str(root / "logs/green-originals"),
        OHM_CGUR_SNAPSHOT=str(kit / "green_at_exec.py"),
    )


def build(root, sdk, env):
    driver = sdk / "lib/librustc_driver-b03bf00bec23bb9a.so"
    require(sha(driver) == DRIVER, "unexpected signed compiler layout")
    kit = root / "green-kit"
    kit.mkdir()
    sources = list(SOURCE.glob("*")) + [HERE / "green_inputs.py", HERE / "physical.py"]
    for src in sources:
        require(src.is_file() and not src.is_symlink(), "unexpected probe input")
        shutil.copyfile(src, kit / src.name)
    version = subprocess.check_output(
        ["/usr/bin/valgrind", "--version"], text=True, env=env
    ).strip()
    require(version.startswith("valgrind-3.22."), "unregistered Valgrind ABI")
    subprocess.run(["/bin/bash", kit / "build.sh"], cwd=kit, env=env, check=True)
    return dict(
        version=version,
        driver=DRIVER,
        sources={p.name: sha(p) for p in sources},
        binaries={
            n: sha(kit / n)
            for n in ("capture", "launch.so", "vglib/cgured-amd64-linux")
        },
    )


def records(owner):
    launch = json.loads((owner / "launch.json").read_bytes())
    proc = json.loads((owner / "process.json").read_bytes())
    raw = (owner / "original.nul").read_bytes()
    require(
        (owner / "observed.nul").read_bytes() == raw
        and launch["argc"] == raw.count(b"\0")
        and launch["argv_bytes"] == len(raw)
        and proc["pid"] == launch["pid"]
        and launch["env_sha256"] == (owner / "original-env.sha256").read_text()
        and proc["envc"] == [launch["envc"]] * 2,
        "original signed argv or environment changed",
    )
    lines = (owner / "cgu.log").read_text().splitlines()
    trace = [line[line.index("CGUR ") :].split() for line in lines if "CGUR " in line]
    started = [r for r in trace if r[1] == "DRIVER"]
    ends = [r for r in trace if r[1] == "END"]
    require(
        len(started) == len(ends) == 1
        and trace[-1] == ends[0]
        and int(ends[0][3]) == 0,
        "incomplete signed compiler trace",
    )
    decisions = int(ends[0][2])
    require(
        decisions > 0 and len([r for r in trace if r[1] == "NESTED"]) == 0,
        "unbalanced compiler decisions",
    )
    for event in ("E", "N", "X"):
        require(
            sorted(int(r[2]) for r in trace if r[1] == event)
            == list(range(1, decisions + 1)),
            "incomplete compiler decisions " + event,
        )
    guests = {int(r[2]): tuple(map(int, r[3:])) for r in trace if r[1] == "FD"}
    require(
        all(
            access in (0, 1, 2) and guests.get(fd) == (dev, ino, kind, access)
            for fd, dev, ino, kind, access in launch["fds"]
        )
        and not (owner / "original-fds.bin").exists(),
        "lost original descriptor in the signed compiler client",
    )
    require(
        (owner / "green-inputs-exec.json").is_file(),
        "missing stopped-compiler donor checkpoint",
    )
    return dict(
        decisions=decisions,
        log=sha(owner / "cgu.log"),
        argv=sha(owner / "original.nul"),
        original_fd_count=len(launch["fds"]),
        env=launch["env_sha256"],
        binary_trace_lines=len(trace),
    )


def classify(out, sdk):
    """Require the actual prior donor and cross-check against the independent table decoder."""
    from read_products import recorded_products
    import gzip
    import sys

    owner = out / "green-reasons/A/stage/ruff_workspace"
    before = json.loads((owner / "green-inputs-exec.json").read_bytes())
    after = json.loads((out / "green-reasons/A/green-inputs-after.json").read_bytes())
    require(
        before["original_argv_sha256"]
        == after["original_argv_sha256"]
        == sha(owner / "original.nul")
        and before["incremental"] == after["incremental"],
        "other arguments or incremental workspace",
    )
    old_sessions = {s["path"]: s for s in before["sessions"]}
    new_sessions = {
        s["path"]: s for s in after["sessions"] if s["path"] not in old_sessions
    }
    require(
        len(old_sessions) == len(new_sessions) == 1,
        "ambiguous old or newly completed workspace session",
    )
    old = next(iter(old_sessions.values()))
    new = next(iter(new_sessions.values()))
    old_files = {f["name"]: f for f in old["files"]}
    new_files = {f["name"]: f for f in new["files"]}
    require(
        old_files["dep-graph.bin"]["sha256"]
        == old_files["ohm-build-dep-graph.bin"]["sha256"],
        "prior ordinary graph differs from the native build checkpoint",
    )
    inputs = {
        "prior-graph": old_files["ohm-build-dep-graph.bin"],
        "current-graph": new_files["dep-graph.bin"],
        "work-products": old_files["work-products.bin"],
    }
    paths = {}
    for option, record in inputs.items():
        require(
            record["stored"] and record["stat"][2] <= 512 << 20, "unbounded graph input"
        )
        path = out / "green-originals" / (record["sha256"] + ".gz")
        with gzip.open(path, "rb") as src:
            h = hashlib.sha256()
            size = 0
            while chunk := src.read(1024 * 1024):
                h.update(chunk)
                size += len(chunk)
                require(size <= record["stat"][2], "oversized graph")
        require(
            size == record["stat"][2] and h.hexdigest() == record["sha256"],
            "changed graph or table bytes",
        )
        paths[option] = path
    args = [
        sys.executable,
        "-IB",
        SOURCE / "verify_trace.py",
        owner / "cgu.log",
        "--signed-driver",
        sdk / "lib/librustc_driver-b03bf00bec23bb9a.so",
    ]
    for option, path in paths.items():
        args.extend(["--" + option, path])
    result = json.loads(subprocess.check_output(args))
    with gzip.open(paths["work-products"], "rb") as src:
        table = recorded_products(src.read(), old_files)
    by_key = {"".join(f"{word:016x}" for word in p["words"]): p for p in table.values()}
    for decision in result["decisions"]:
        prior = by_key.get(decision["work_product_id"])
        decision["prior_saved_files"] = None if prior is None else prior["saved"]
        decision["prior_saved_files_present"] = (
            None if prior is None else prior["all_present"]
        )
        if decision["reason"] not in ("no-reconciled-donor", "incremental-disabled"):
            require(
                prior is not None
                and prior["all_present"]
                and prior["cgu"] == decision["cgu"],
                "accepted donor absent from the otherwise independent physical inventory",
            )
    return result


def coverage(emitted, comparable, decisions):
    """Match full physical module identities to the signed reuse call's work-product name."""
    import re
    from collections import Counter

    ids = {}
    crate_hashes = set()
    for identity in emitted:
        match = re.fullmatch(
            r"ruff_workspace\.([0-9a-f]{16})\.([a-z0-9]{25})", identity
        )
        require(
            match is not None and match[2] not in ids,
            "invalid or ambiguous native module",
        )
        crate_hashes.add(match[1])
        ids[match[2]] = identity
    require(len(crate_hashes) == 1, "multiple physical workspace crate identities")
    names = [row["cgu"] for row in decisions if row["actual_cgu_reuse"] == "No"]
    require(
        len(names) == len(set(names)) and set(names) == ids.keys(),
        "signed no-reuse decisions differ from the independently observed LLVM inputs",
    )
    targets = set(comparable)
    require(
        targets <= set(emitted),
        "an independently identical CGU has no observed LLVM input",
    )
    return dict(
        rejected=len(names),
        independently_identical_causes=dict(
            Counter(
                row["reason"] for row in decisions if ids.get(row["cgu"]) in targets
            )
        ),
    )
