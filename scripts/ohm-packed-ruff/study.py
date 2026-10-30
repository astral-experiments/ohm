"""Run the registered Ruff branch history on physical Linux compiler images."""
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import resource
import shutil
import statistics
import subprocess
import sys
import tarfile
import threading
import time
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "harness"))
import compiler_counts
import count
import native_controls
import outputs
from omission import publish, require, sha

ROOT = Path(os.environ["RUNNER_TEMP"]).resolve() / "ohm-branch-object-qa"
OUT = ROOT / "logs"
SDK = ROOT / "sdk"
TREE = ROOT / "ruff"
WORK = ROOT / "work"
HOST = "x86_64-unknown-linux-gnu"
WILD = "lib/rustlib/" + HOST + "/bin/wild-ld/ld.bfd"
TOOLS = {"bin/cargo": "abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a",
         WILD: "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"}
REVS = {"A": "b5dba861cc38e3f7fb4524c9ceba3e01a474ea13", "B": "7b13f01ba1569887a25670820764b24c206da8e5"}
TREES = {"A": "2b61306d708a211b3725c8d920e7590be6da41ad", "B": "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c"}
NAMES = {"A": "historical-parent", "B": "historical-feature"}
ARMS = ("Off", "Full", "Packed")
CARGO = ["cargo", "+ohm", "build", "-p", "ruff_python_parser", "--locked", "--offline", "-j4", "--message-format=json"]
SELECTED = ["ruff_python_ast", "ruff_python_parser"]
PHASES = ("empty-A", "first-B", "return-A", "return-B", "unchanged-B", "dirty-B-as-A", "restored-B", "invalid", "recovery")
SWITCHES = ("first-B", "return-A", "return-B")


def git(*args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", TREE, *args], text=True).strip()


def record_run(argv, cwd, env, path, expected):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic_ns()
    child = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, capture_output=True)
    elapsed = time.monotonic_ns() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    path.with_suffix(".stdout").write_bytes(child.stdout)
    path.with_suffix(".stderr").write_bytes(child.stderr)
    publish(path.with_suffix(".json"), {"argv": list(map(str, argv)), "exit": child.returncode,
            "wall_ns": elapsed, "user_s": after.ru_utime - before.ru_utime, "sys_s": after.ru_stime - before.ru_stime})
    require(child.returncode == expected, (path, expected, child.returncode, child.stderr[-1600:]))
    return child


def environment(arm):
    env = {k: os.environ[k] for k in ("HOME", "PATH")}
    env.update(RUSTUP_HOME=str(ROOT / "rustup"), RUSTUP_AUTO_INSTALL="0", CARGO_HOME=str(ROOT / "cargo-home"),
               CARGO_TARGET_DIR=str(WORK / "target"), CARGO_BUILD_BUILD_DIR=str(WORK / "build"),
               CARGO_NET_OFFLINE="true", CARGO_TERM_COLOR="never", LC_ALL="C", LD_LIBRARY_PATH=str(SDK / "lib"),
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    if arm != "Off":
        env["CARGO_ENCODED_RUSTFLAGS"] = "-Zohm-branch-cache=yes"
    return env


def prepare():
    archive = ROOT / "ohm-1.99.0-20-x86_64-unknown-linux-gnu.tar.gz"
    require(archive.stat().st_size == 359585079 and sha(archive) ==
            "edb64a2ee39b2f2951614f98d53ec4e4197f55149ff794c911bd81bc7f870b15", "wrong release archive")
    expected = {"cargo/bin/cargo": "bin/cargo", "rustc/" + WILD: WILD}
    found = {}
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            parts = Path(member.name).parts
            subpath = "/".join(parts[1:])
            if subpath not in expected:
                continue
            name = expected[subpath]
            require(member.isfile() and name not in found and 0 < member.size < 50_000_000, member.name)
            target = SDK / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, target.open("xb") as sink:
                shutil.copyfileobj(src, sink)
            target.chmod(0o755)
            found[name] = sha(target)
    require(found == TOOLS, ("incorrect signed Cargo or Wild", found))
    capsule = ROOT / "capsule"
    records = {role: json.loads((capsule / (role + ".json")).read_bytes())["files"] for role in ("P", "C")}
    require(set(records["P"]) == set(records["C"]), "unmatched runtime paths")
    changed = [n for n in records["P"] if records["P"][n] != records["C"][n]]
    require(any(n.startswith("lib/librustc_driver-") for n in changed)
            and all(n == "bin/rustc" or n.startswith("lib/librustc_driver-") for n in changed),
            ("different bootstrap, std, linker, or LLVM runtimes", changed))
    for name, (key, size, mode) in records["P"].items():
        obj = capsule / "objects" / key
        require(obj.stat().st_size == size and sha(obj) == key, obj)
        path = SDK / name
        path.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(obj, path)
        path.chmod(mode)
    publish(OUT / "enrolled.json", {"changes": changed, "cargo_and_wild": found, "release": sha(archive)})
    tools = ROOT / "rustup/toolchains"
    tools.mkdir(parents=True)
    (tools / "ohm").symlink_to(SDK)
    shutil.copytree(HERE / "harness", ROOT / "harness")
    subprocess.run(["git", "init", "--quiet", "--template=", TREE], check=True)
    git("fetch", "--quiet", "--no-tags", "--depth=2", "https://github.com/astral-sh/ruff.git", REVS["B"])
    require(git("rev-parse", REVS["B"] + "^") == REVS["A"], "wrong Ruff parent")
    for tag, rev in REVS.items():
        require(git("rev-parse", rev + "^{tree}") == TREES[tag], tag)
        git("branch", NAMES[tag], rev)
    git("switch", "-q", NAMES["A"])
    require(sha(TREE / "Cargo.lock") == "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb", "different lockfile")
    env = environment("Off")
    del env["CARGO_NET_OFFLINE"]
    record_run(["cargo", "+ohm", "fetch", "--locked"], TREE, env, OUT / "fetch", 0)
    locks = {p["name"] + "-" + p["version"] + ".crate": p["checksum"]
             for p in tomllib.loads((TREE / "Cargo.lock").read_text())["package"] if "checksum" in p}
    archives = {p.name: sha(p) for p in (ROOT / "cargo-home/registry/cache").glob("*/*.crate")}
    require(len(locks) == 505 and locks == archives, ("locked registry coverage", len(archives), len(locks)))
    publish(OUT / "archives.json", archives)


def setup_arm(arm):
    role = "P" if arm == "Full" else "C"
    record = json.loads((OUT / (role + ".json")).read_bytes())["files"]
    changes = json.loads((OUT / "enrolled.json").read_bytes())["changes"]
    for name in changes:
        key, size, mode = record[name]
        path = SDK / name
        tmp = path.with_name(path.name + ".next")
        shutil.copyfile(ROOT / "capsule/objects" / key, tmp)
        tmp.chmod(mode)
        require(tmp.stat().st_size == size and sha(tmp) == key, name)
        os.replace(tmp, path)
    env = environment(arm)
    for name in ("cargo", "rustc"):
        actual = subprocess.check_output(["rustup", "which", "--toolchain", "ohm", name], env=env, text=True).strip()
        require(Path(actual).samefile(SDK / "bin" / name), actual)
    require((WORK / ".owned-by-packed-study").read_text() == str(ROOT), WORK)
    for name in ("target", "build"):
        path = WORK / name
        if path.exists():
            require(path.is_dir() and not path.is_symlink() and path.parent == WORK, path)
            shutil.rmtree(path)
        path.mkdir()
    return env


def source(phase, branch):
    if phase == "dirty-B-as-A":
        git("restore", "--source", REVS["A"], "--worktree", "--", ".")
        require(git("rev-parse", "HEAD") == REVS["B"] and
                len(git("diff", "--name-status").splitlines()) == 169, "expected the historical 169-file reversal")
        git("diff", "--exit-code", REVS["A"], "--", ".")
    elif phase in ("restored-B", "recovery"):
        git("restore", "--worktree", "--", ".")
    elif phase == "invalid":
        with (TREE / "crates/ruff_python_parser/src/lib.rs").open("ab") as edited:
            edited.write(b"\nconst ohm_branch_switch_invalid: () = 1u32;\n")
    else:
        require(not git("status", "--porcelain"), "unexpected Ruff working-tree change")
        git("switch", "-q", NAMES[branch])
    require(git("rev-parse", "HEAD") == REVS[branch], (phase, branch))


def measure(directory, phase, branch, arm, env, reference, *, create=False, trace=False, tracer=None):
    directory.mkdir()
    tick = time.monotonic_ns()
    source(phase, branch)
    git_ns = time.monotonic_ns() - tick
    command = CARGO
    profiled = tracer is not None and phase.startswith("return-")
    if profiled:
        command = compiler_counts.command(tracer, SDK, directory, CARGO)
    elif trace:
        command = ["strace", "-f", "-qq", "--seccomp-bpf", "-s", "65535", "-e", "trace=execve",
                   "-o", str(directory / "exec.log"), *CARGO]
    samples = []
    stop = threading.Event()
    def sample():
        while True:
            info = os.statvfs(WORK)
            samples.append((time.monotonic_ns(), (info.f_blocks - info.f_bfree) * info.f_frsize))
            if stop.wait(.005):
                break
    observer = threading.Thread(target=sample, daemon=True)
    observer.start()
    try:
        proc = record_run(command, TREE, env, directory / "cargo", 101 if phase == "invalid" else 0)
    finally:
        stop.set()
        observer.join()
    raw = json.loads((directory / "cargo.json").read_bytes())
    publish(directory / "samples.json.gz", samples)
    rows = list(map(json.loads, proc.stdout.splitlines()))
    require(rows[-1] == {"reason": "build-finished", "success": phase != "invalid"}, rows[-1])
    if phase == "invalid":
        require(any(m.get("message", {}).get("code") and m["message"]["code"]["code"] == "E0308" and
                    any("ohm_branch_switch_invalid" in item["text"] for span in m["message"]["spans"] for item in span["text"])
                    for m in rows), "missing error for the injected invalid statement")
        return {"invalid": True}
    dirty = sorted(m["target"]["name"] for m in rows if m["reason"] == "compiler-artifact" and not m["fresh"])
    if not create and (phase.startswith("return-") or phase in ("dirty-B-as-A", "restored-B")):
        require(dirty == SELECTED, (phase, dirty))
    if phase == "unchanged-B":
        require(not dirty, dirty)
    if trace:
        roster = outputs.native_execs(directory / "exec.log", SDK)
        actual = sorted(p["crate"] for p in roster["rustcs"])
        require(actual == ([] if phase == "unchanged-B" else SELECTED) and roster["wild"] == 0, (phase, actual))
        for p in roster["rustcs"]:
            require("-Zohm-check-relink-inputs" in p["argv"] and
                    ("-Zohm-branch-cache=yes" in p["argv"]) == (arm != "Off"), p)
        publish(directory / "native-execs.json.gz", roster)
        compiler_counts.compress(directory / "exec.log")
    raw["compiler_Ir"] = compiler_counts.read(directory, proc.stderr, "build") if profiled else None
    if profiled:
        for file in (directory / "callgrind").glob("rustc.*.argv"):
            args = file.read_bytes().split(b"\0")
            require(b"-Zohm-check-relink-inputs" in args and (b"-Zohm-branch-cache=yes" in args) == (arm != "Off"), file)
    footprint = count.census(WORK / "target", WORK / "build")
    companions = [p for name in ("target", "build") for p in (WORK / name).rglob("ohm-packed-object-*")]
    if phase in SWITCHES or phase == "unchanged-B":
        require(bool(companions) == (arm == "Packed"), (arm, phase, len(companions)))
    publish(directory / "allocated.json", footprint)
    logical = outputs.outputs(rows, directory, WORK, ROOT, env, TREE,
                              "A" if phase == "dirty-B-as-A" else branch, record_run)
    if create:
        publish(reference, logical)
    checked = outputs.compare(json.loads(gzip.decompress(reference.read_bytes())), logical)
    require(all(set(names) <= {"lib.rmeta"} for names in checked.values()), ("changed native archive payload", checked))
    raw.update(git_ns=git_ns, dirty=dirty, traced=trace, counted=profiled,
               allocated=footprint["target_and_build_bytes"], peak_fs=max(v for _, v in samples),
               packed_objects=len(companions), metadata_differences=checked, executable=logical["reader_sha256"],
               expr=logical["typed_size"], branch=branch)
    publish(directory / "result.json", raw)
    return raw


def reference_for(arm, phase, branch):
    key = "B-as-A" if phase == "dirty-B-as-A" else branch
    return OUT / "references" / (arm + "-" + key + ".json.gz")


def qualify():
    refs = OUT / "references"
    refs.mkdir()
    for arm in ARMS:
        for key in ("A", "B", "B-as-A"):
            env = setup_arm(arm)
            branch = "A" if key == "A" else "B"
            phase = "dirty-B-as-A" if key == "B-as-A" else "empty"
            git("switch", "-q", NAMES[branch])
            measure(refs / (arm + "-" + key), phase, branch, arm, env, reference_for(arm, phase, branch), create=True)
            git("restore", "--worktree", "--", ".")
        root = OUT / ("mechanism-" + arm)
        installation(arm, root, trace=True)
    guard = ROOT / "native-guard"
    guard.mkdir()
    env = setup_arm("Packed") | {"CARGO_TARGET_DIR": str(guard / "target"), "CARGO_BUILD_BUILD_DIR": str(guard / "build")}
    native_controls.native_controls(guard, OUT / "native-guard", env)


def installation(arm, path, *, trace=False, tracer=None):
    path.mkdir()
    env = setup_arm(arm)
    data = {}
    for phase in PHASES:
        branch = "A" if phase in ("empty-A", "return-A") else "B"
        data[phase] = measure(path / phase, phase, branch, arm, env, reference_for(arm, phase, branch),
                              trace=trace and phase in ("return-A", "return-B", "unchanged-B"), tracer=tracer)
    require(data["return-A"]["executable"] != data["return-B"]["executable"], (arm, "same native reader on two layouts"))
    publish(path / "installation.json", data)
    return data


def cohort(stage):
    folder = OUT / stage
    folder.mkdir()
    if stage == "confirm":
        orders = list(itertools.permutations(ARMS)) * 2
        random.Random(0x28335020).shuffle(orders)
    else:
        orders = [ARMS, tuple(reversed(ARMS))]
    tracer = compiler_counts.prepare(folder) if stage == "counter" else None
    publish(folder / "plan.json", {"orders": orders, "command": CARGO, "phases": PHASES})
    pairs = []
    for i, order in enumerate(orders):
        group = {}
        for arm in order:
            group[arm] = installation(arm, folder / f"triplet-{i + 1:02}-{arm}", tracer=tracer)
            print(f"Closed {stage} triplet {i + 1} {arm}", flush=True)
        pairs.append(group)
    projections = {}
    admitted = True
    for phase in ("return-A", "return-B"):
        def cost(group, arm):
            row = group[arm][phase]
            return sum(row["compiler_Ir"].values()) if tracer is not None else row["wall_ns"]
        ratios = [cost(group, "Off") / cost(group, "Packed") for group in pairs]
        lower = sorted(ratios)[2] if stage == "confirm" else min(ratios)
        admitted &= lower > 2
        projections[phase] = {"individual": ratios, "median": statistics.median(ratios), "lower": lower}
    disks = {phase: [group["Full"][phase]["allocated"] - group["Packed"][phase]["allocated"]
                     for group in pairs] for phase in SWITCHES}
    admitted &= all(v > 0 for column in disks.values() for v in column)
    combos = {}
    for name, phases in {"first-plus-return": ("first-B", "return-A"),
                         "same-branch-edit": ("dirty-B-as-A",), "restore": ("restored-B",)}.items():
        combos[name] = {arm: [sum(group[arm][phase]["wall_ns"] for phase in phases) for group in pairs]
                        for arm in ARMS} if tracer is None else None
    publish(folder / "result.json", {"admitted": admitted, "performance": projections, "storage_saved_bytes": disks,
            "cohort": stage, "metric": "complete rustc Ir" if tracer is not None else "whole Cargo ns",
            "secondary_wall_ns": combos})
    print(json.dumps({"stage": stage, "admitted": admitted, "return_ratios": projections, "disk": disks}, indent=2))


if __name__ == "__main__":
    action, = sys.argv[1:]
    if action == "prepare":
        prepare()
    elif action == "qualify":
        qualify()
    elif action in ("screen", "confirm", "counter"):
        if action != "screen":
            require(json.loads((OUT / "screen/result.json").read_bytes())["admitted"], "screen did not qualify")
        cohort(action)
    else:
        raise SystemExit("unknown phase")
