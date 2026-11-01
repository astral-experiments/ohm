"""Measure the two release-built compilers on a real Ruff edit and its first unchanged repeat."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import resource
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib

import direct

HERE = Path(__file__).resolve().parent
P = json.loads((HERE / "protocol.json").read_bytes())
W = Path(os.environ["GITHUB_WORKSPACE"])
WORK = Path(os.environ["RUNNER_TEMP"]) / "rc23-cross-benchmark"
SRC = W / "ruff-source"
OUT = W / "cross-results"
ACTIVE = WORK / "sdk"
SLOT = WORK / "state"
DEPS = WORK / "registry"
HOST = "x86_64-unknown-linux-gnu"
ARMS = ("base", "cross")


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def record(path, data):
    with gzip.open(path, "wb", compresslevel=3) as destination:
        destination.write(data)
    return hashlib.sha256(data).hexdigest()


def git(*args, data=None):
    return subprocess.check_output(["git", "-C", SRC, *args], input=data)


def switch(arm):
    ACTIVE.unlink(missing_ok=True)
    ACTIVE.symlink_to(WORK / ("sdk-" + arm), target_is_directory=True)


def install(kind):
    target = P["cases"][kind]["target"]
    meta = json.loads((W / "cross-media.json").read_bytes())
    selected = {
        a["name"]: a
        for a in meta["artifacts"]
        if a["name"] in {"rc23-cross-sdk-base", "rc23-cross-sdk-cross"}
    }
    assert len(selected) == 2
    installed = {}
    for arm in ARMS:
        name = "rc23-cross-sdk-" + arm
        producer = P["producers"][arm]
        details = selected[name]
        assert (
            not details["expired"]
            and details["workflow_run"]["id"] == producer["run"]
            and details["workflow_run"]["head_sha"] == producer["head"]
            and details["id"] == producer["artifact_id"]
            and details["digest"] == producer["artifact_digest"]
        )
        media = W / "cross-media" / name
        identity = json.loads((media / "source.json").read_bytes())
        assert (
            identity["arm"] == arm
            and identity["published_coordinator"] == P["published_coordinator"]
            and identity["published_manifest_sha256"] == P["published_manifest_sha256"]
            and int(identity["run"]) == producer["run"]
            and identity["workflow"] == producer["head"]
            and int(identity["attempt"]) == producer["attempt"]
        )
        pins = {k: v["revision"] for k, v in identity["sources"]["sources"].items()}
        assert pins == dict(P["component_commits"], rust=P["compilers"][arm]["commit"])
        seals = {}
        for line in (media / "SHA256SUMS").read_text().splitlines():
            digest, relative = line.split("  ", 1)
            leaf = Path(relative)
            assert leaf.parent == Path(".") and re.fullmatch(r"[0-9a-f]{64}", digest)
            assert sha(media / leaf) == digest
            seals[leaf.name] = digest
        assert seals == producer["payload_sha256"]
        components = ["rust-1.99.0-dev-" + HOST, "rust-std-1.99.0-dev-" + target]
        assert set(seals) == {
            "rust-1.99.0-dev-" + HOST + ".tar.gz",
            *(
                "rust-std-1.99.0-dev-" + P["cases"][c]["target"] + ".tar.gz"
                for c in P["cases"]
            ),
        }
        sdk = WORK / ("sdk-" + arm)
        for i, component in enumerate(components):
            extraction = WORK / "extraction"
            extraction.mkdir()
            with tarfile.open(media / (component + ".tar.gz")) as archive:
                archive.extractall(extraction, filter="data")
            location = extraction / component
            assert list(extraction.iterdir()) == [location]
            args = [
                location / "install.sh",
                "--prefix=" + str(sdk),
                "--disable-ldconfig",
            ]
            if i == 0:
                args.append("--components=rustc,cargo,rust-std-" + HOST)
            subprocess.run(args, check=True)
            shutil.rmtree(extraction)
        compiler = subprocess.check_output([sdk / "bin/rustc", "-vV"], text=True)
        cargo = subprocess.check_output([sdk / "bin/cargo", "-Vv"], text=True)
        assert (
            "commit-hash: " + pins["rust"] in compiler
            and "commit-hash: " + pins["cargo"] in cargo
        )
        assert (
            Path(
                subprocess.check_output(
                    [sdk / "bin/rustc", "--print", "sysroot"], text=True
                ).strip()
            ).resolve()
            == sdk.resolve()
        )
        std = list((sdk / "lib/rustlib" / target / "lib").glob("libstd-*.rlib"))
        assert len(std) == 1
        driver = list((sdk / "lib").glob("librustc_driver-*.so"))
        assert len(driver) == 1
        installed[arm] = {
            "artifact": details,
            "source": identity,
            "archives": seals,
            "compiler": compiler,
            "cargo": cargo,
            "driver": sha(driver[0]),
            "target_std": sha(std[0]),
        }
    assert installed["base"]["driver"] != installed["cross"]["driver"]
    (WORK / "bin").mkdir()
    (WORK / "bin/cargo").symlink_to(WORK / "sdk-base/bin/cargo")
    dump(OUT / "installed.json", installed)
    return target


def affinity():
    allowed = sorted(os.sched_getaffinity(0))
    physical = {}
    for n in allowed:
        topology = Path(f"/sys/devices/system/cpu/cpu{n}/topology")
        key = tuple(
            (topology / file).read_text().strip()
            for file in ["physical_package_id", "core_id"]
        )
        physical.setdefault(key, n)
    selected = (list(physical.values()) if len(physical) >= P["jobs"] else allowed)[
        : P["jobs"]
    ]
    assert len(selected) == P["jobs"]
    os.sched_setaffinity(0, selected)
    dump(
        OUT / "host.json",
        dict(
            boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            machine=platform.machine(),
            affinity=selected,
            lscpu=subprocess.check_output(["lscpu", "--json"], text=True),
            cpu_max=Path("/sys/fs/cgroup/cpu.max").read_text()
            if Path("/sys/fs/cgroup/cpu.max").exists()
            else None,
        ),
    )
    return set(selected)


def env(target, fetch=False):
    linker = "aarch64-linux-gnu-gcc" if target.startswith("aarch64") else "musl-gcc"
    return {
        "HOME": str(WORK / "home"),
        "TMPDIR": str(WORK / "tmp"),
        "PATH": f"{WORK / 'bin'}:{ACTIVE / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        "CARGO_HOME": str(DEPS if fetch else SLOT / "cargo"),
        "CARGO_TERM_COLOR": "never",
        "CARGO_CACHE_AUTO_CLEAN_FREQUENCY": "never",
        "CARGO_TARGET_DIR": str(SLOT / "target"),
        "CARGO_BUILD_BUILD_DIR": str(SLOT / "shared"),
        "RUSTC": str(ACTIVE / "bin/rustc"),
        "RUSTDOC": str(ACTIVE / "bin/rustdoc"),
        "CARGO_TARGET_" + target.upper().replace("-", "_") + "_LINKER": shutil.which(
            linker
        ),
        "CC_" + target.replace("-", "_"): shutil.which(linker),
        "AR_" + target.replace("-", "_"): shutil.which(
            "aarch64-linux-gnu-ar" if target.startswith("aarch64") else "ar"
        ),
        "CARGO_NET_RETRY": "3",
        "TZ": "UTC",
        "LC_ALL": "C",
    }


def prepare(case):
    assert git("rev-parse", case["child"] + "^").decode().strip() == case["parent"]
    delta = git(
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        case["parent"],
        case["child"],
    )
    (OUT / "ruff.patch").write_bytes(delta)
    assert set(
        git("diff", "--name-only", case["parent"], case["child"]).decode().splitlines()
    ) == set(case["files"])
    for key in ("parent", "child"):
        git("checkout", "--quiet", "--detach", case[key])
        assert git("rev-parse", "HEAD^{tree}").decode().strip() == case[key + "_tree"]
        subprocess.run(
            [WORK / "bin/cargo", "fetch", "--locked"],
            cwd=SRC,
            env=env(case["target"], True),
            check=True,
        )
        lockfile = SRC / "Cargo.lock"
        packages = tomllib.loads(lockfile.read_text())["package"]
        verified = {}
        fetched = []
        for dep in packages:
            if not dep.get("source", "").startswith("registry+"):
                continue
            filename = f"{dep['name']}-{dep['version']}.crate"
            matches = list((DEPS / "registry/cache").glob("*/" + filename))
            if not matches:
                # Cargo can omit an optional crate that a cross-target build later requests offline.
                assert dep["source"] == "registry+https://github.com/rust-lang/crates.io-index"
                assert re.fullmatch(r"[A-Za-z0-9_-]+", dep["name"])
                assert re.fullmatch(r"[A-Za-z0-9.+-]+", dep["version"])
                cache, = (DEPS / "registry/cache").glob("index.crates.io-*")
                archive = cache / filename
                partial = archive.with_suffix(".crate.partial")
                url = f"https://static.crates.io/crates/{dep['name']}/{filename}"
                subprocess.run(["curl", "--fail", "--silent", "--show-error", "--retry", "3",
                                "--output", str(partial), url], check=True)
                assert sha(partial) == dep["checksum"], filename
                partial.replace(archive)
                matches.append(archive)
                fetched.append(filename)
            assert len(matches) == 1 and sha(matches[0]) == dep["checksum"], filename
            verified[filename] = dep["checksum"]
        dump(OUT / ("prefetch-" + key + ".json"), {"lock": sha(lockfile), "packages": verified, "filled_from_crates_io": fetched})
    git("checkout", "--quiet", "--detach", case["parent"])
    return delta


def old(case):
    git("reset", "--quiet", "--hard", case["parent"])
    assert git("rev-parse", "HEAD^{tree}").decode().strip() == case[
        "parent_tree"
    ] and not git("status", "--porcelain")


def edit(case, delta):
    git("apply", "--index", "--binary", "-", data=delta)
    assert git("write-tree").decode().strip() == case["child_tree"]
    git("reset", "--quiet", "--mixed", case["parent"])
    assert git("diff", "--binary", "--full-index", "--no-ext-diff", "HEAD") == delta


def new_state():
    if SLOT.exists():
        assert SLOT.parent == WORK and not SLOT.is_symlink()
        shutil.rmtree(SLOT)
    (SLOT / "cargo").mkdir(parents=True)
    for n in ("registry", "git"):
        if (DEPS / n).is_dir():
            (SLOT / "cargo" / n).symlink_to(DEPS / n, target_is_directory=True)


def cpu(mask):
    names = {f"cpu{n}" for n in mask}
    return [
        s for s in Path("/proc/stat").read_text().splitlines() if s.split()[0] in names
    ]


def build(phase, case, kind, folder, mask):
    if kind == "gnu":
        cmd = ["build", "--locked", "--offline", "-p", "ruff", "--bin", "ruff"]
    else:
        cmd = [
            "test",
            "--locked",
            "--offline",
            "-p",
            "ruff_python_ast",
            "--lib",
            "--no-run",
        ]
    argv = [
        str(WORK / "bin/cargo"),
        *cmd,
        "--target",
        case["target"],
        "-j4",
        "--message-format=json",
    ]
    assert os.sched_getaffinity(0) == mask
    cpu0 = cpu(mask)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t = time.monotonic_ns()
    res = subprocess.run(
        argv, cwd=SRC, env=env(case["target"]), capture_output=True, timeout=3600
    )
    stop = time.monotonic_ns()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu1 = cpu(mask)
    out = folder / phase
    out.mkdir()
    row = dict(
        argv=argv,
        exit=res.returncode,
        start_ns=t,
        end_ns=stop,
        elapsed_ns=stop - t,
        user_s=after.ru_utime - before.ru_utime,
        sys_s=after.ru_stime - before.ru_stime,
        cpu_before=cpu0,
        cpu_after=cpu1,
        stdout_sha256=record(out / "stdout.gz", res.stdout),
        stderr_sha256=record(out / "stderr.gz", res.stderr),
    )
    dump(out / "command.json", row)
    assert res.returncode == 0, (phase, res.stderr[-2500:])
    messages = [json.loads(s) for s in res.stdout.splitlines()]
    assert messages[-1] == dict(reason="build-finished", success=True)
    units = [m for m in messages if m["reason"] == "compiler-artifact"]
    name = "ruff" if kind == "gnu" else "ruff_python_ast"
    chosen = [m for m in units if m["target"]["name"] == name and m.get("executable")]
    assert len(chosen) == 1
    graph = sorted(
        json.dumps(
            [m[k] for k in ("package_id", "target", "features", "profile")],
            sort_keys=True,
            separators=(",", ":"),
        )
        for m in units
    )
    artifact = Path(chosen[0]["executable"]).resolve(strict=True)
    assert artifact.is_relative_to(SLOT / "target")
    result = dict(
        elapsed_ns=row["elapsed_ns"],
        cpu_s=row["user_s"] + row["sys_s"],
        graph_sha256=hashlib.sha256(json.dumps(graph).encode()).hexdigest(),
        units=len(units),
        dirty=sorted(m["target"]["name"] for m in units if not m["fresh"]),
        product=sha(artifact),
    )
    dump(out / "graph.json", graph)
    dump(out / "result.json", result)
    return result, artifact


def behavior(kind, case, file, changed, path):
    path.mkdir()

    def run(name, argv, stdin=b""):
        p = subprocess.run(
            argv,
            cwd=SRC,
            env=env(case["target"]),
            input=stdin,
            capture_output=True,
            timeout=150,
        )
        dump(
            path / (name + ".json"),
            dict(
                argv=list(map(str, argv)),
                exit=p.returncode,
                stdout=record(path / (name + ".stdout.gz"), p.stdout),
                stderr=record(path / (name + ".stderr.gz"), p.stderr),
            ),
        )
        return p

    raw = file.open("rb").read(20)
    assert raw[:6] == b"\x7fELF\x02\x01" and int.from_bytes(raw[18:20], "little") == (
        183 if kind == "gnu" else 62
    )
    if kind == "gnu":
        for name, source, want in [
            (
                "starred",
                "a = (1, 2, 3)\nprint((*a, 9)[2])\n",
                [] if changed else ["PLE0643"],
            ),
            ("out-of-bounds", "print([1, 2, 3][3])\n", ["PLE0643"]),
            ("valid", "print([1, 2, 3][0])\n", []),
        ]:
            p = run(
                name,
                [
                    "qemu-aarch64",
                    "-L",
                    "/usr/aarch64-linux-gnu",
                    file,
                    "check",
                    "--no-cache",
                    "--select",
                    "PLE0643",
                    "--output-format",
                    "json",
                    "-",
                ],
                source.encode(),
            )
            assert (
                p.returncode == (1 if want else 0)
                and [d["code"] for d in json.loads(p.stdout)] == want
            ), (name, p.returncode, p.stdout[-1500:], p.stderr[-1500:])
    else:
        elf = run("readelf", ["readelf", "-lhWd", file])
        assert (
            elf.returncode == 0
            and b"INTERP" not in elf.stdout
            and b"(NEEDED)" not in elf.stdout
        )
        listing = run("inventory", [file, "--list"])
        names = {
            s[:-6] for s in listing.stdout.decode().splitlines() if s.endswith(": test")
        }
        added = set(case["added_tests"])
        assert (
            listing.returncode == 0
            and len(names) == (53 if changed else 49)
            and names & added == (added if changed else set())
            and case["anchor"] in names
        )
        full = run("tests", [file, "--test-threads=1"])
        assert (
            full.returncode == 0
            and f"{len(names)} passed; 0 failed;".encode() in full.stdout
        )


def negative(kind, case, folder):
    leaf = next(
        p
        for p in case["files"]
        if (
            p.endswith("/potential_index_error.rs")
            if kind == "gnu"
            else p == "crates/ruff_python_ast/src/script.rs"
        )
    )
    src = SRC / leaf
    saved = src.read_bytes()
    src.write_bytes(saved + b"\nconst OHM_RC23_BROKEN: () = ohm_rc23_missing_symbol;\n")
    cmd = (
        ["build", "--locked", "--offline", "-p", "ruff", "--bin", "ruff"]
        if kind == "gnu"
        else [
            "test",
            "--locked",
            "--offline",
            "-p",
            "ruff_python_ast",
            "--lib",
            "--no-run",
        ]
    )
    argv = [
        str(WORK / "bin/cargo"),
        *cmd,
        "--target",
        case["target"],
        "-j4",
        "--message-format=json",
    ]
    try:
        p = subprocess.run(
            argv, cwd=SRC, env=env(case["target"]), capture_output=True, timeout=3600
        )
        json_messages = [json.loads(s) for s in p.stdout.splitlines()]
        dump(
            folder / "intentional-failure.json",
            dict(
                argv=argv,
                exit=p.returncode,
                stdout_sha256=record(
                    folder / "intentional-failure.stdout.gz", p.stdout
                ),
                stderr_sha256=record(
                    folder / "intentional-failure.stderr.gz", p.stderr
                ),
            ),
        )
        assert p.returncode == 101 and json_messages[-1] == dict(
            reason="build-finished", success=False
        )
        assert any(
            x["reason"] == "compiler-message"
            and (x["message"].get("code") or {}).get("code") == "E0425"
            and "ohm_rc23_missing_symbol" in x["message"]["message"]
            for x in json_messages
        )
    finally:
        src.write_bytes(saved)


def trial(arm, index, case, kind, delta, mask, canonical):
    folder = OUT / (index + "-" + arm)
    folder.mkdir()
    switch(arm)
    new_state()
    old(case)
    cold, old_binary = build("cold", case, kind, folder, mask)
    behavior(kind, case, old_binary, False, folder / "old-behavior")
    settled, _ = build("settled-parent", case, kind, folder, mask)
    assert settled["product"] == cold["product"]
    edit(case, delta)
    edited, binary = build("edit", case, kind, folder, mask)
    behavior(kind, case, binary, True, folder / "edited-behavior")
    repeated, binary = build("repeat", case, kind, folder, mask)
    assert (
        edited["product"] == repeated["product"]
        and cold["product"] != edited["product"]
    )
    if index == "warmup":
        negative(kind, case, folder)
        repaired, binary = build("repaired", case, kind, folder, mask)
        assert repaired["product"] == edited["product"]
        new_state()
        clean, binary = build("empty-edited", case, kind, folder, mask)
        behavior(kind, case, binary, True, folder / "empty-edited-behavior")
        assert (
            clean["product"] == edited["product"]
            and clean["graph_sha256"] == edited["graph_sha256"]
        )
        canonical[arm] = {"old": cold["product"], "edit": clean["product"]}
    assert (
        cold["product"] == canonical[arm]["old"]
        and edited["product"] == canonical[arm]["edit"]
    )
    return {"cold": cold, "parent-repeat": settled, "edit": edited, "repeat": repeated}


def main():
    kind, cohort = sys.argv[1], int(sys.argv[2])
    assert kind in P["cases"] and 1 <= cohort <= P["cohorts"]
    assert (
        os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
        and platform.machine() == "x86_64"
    )
    WORK.mkdir()
    OUT.mkdir()
    (WORK / "home").mkdir()
    (WORK / "tmp").mkdir()
    case = P["cases"][kind]
    mask = affinity()
    target = install(kind)
    switch("base")
    for arm in ARMS:
        direct.verify(
            arm,
            target,
            WORK / ("sdk-" + arm),
            WORK / ("direct-" + arm),
            OUT / ("direct-" + arm),
        )
    delta = prepare(case)
    canonical = {}
    groups = list(
        [*ARMS] if i % 2 == 0 else list(reversed(ARMS))
        for i in range(P["pairs_per_cohort"])
    )
    random.Random(case["seeds"][cohort - 1]).shuffle(groups)
    dump(OUT / "protocol.json", P)
    dump(OUT / "order.json", groups)
    for arm in ARMS:
        trial(arm, "warmup", case, kind, delta, mask, canonical)
    dump(OUT / "empty-controls.json", canonical)
    pairs = []
    for n, group in enumerate(groups, 1):
        data = {}
        for arm in group:
            data[arm] = trial(arm, f"{n:02}", case, kind, delta, mask, canonical)
        for ph in ("cold", "parent-repeat", "edit", "repeat"):
            assert (
                data["base"][ph]["graph_sha256"] == data["cross"][ph]["graph_sha256"]
                and data["base"][ph]["units"] == data["cross"][ph]["units"]
            )
        pairs.append(data)
        dump(OUT / "pairs.json", pairs)
        print(kind, cohort, "pair", n, "complete", flush=True)
    old(case)
    dump(
        OUT / "complete.json",
        dict(
            run=os.environ["GITHUB_RUN_ID"],
            attempt=os.environ["GITHUB_RUN_ATTEMPT"],
            head=os.environ["GITHUB_SHA"],
            kind=kind,
            cohort=cohort,
            pairs=len(pairs),
            raw_pairs_sha256=sha(OUT / "pairs.json"),
            control_sha256=sha(OUT / "empty-controls.json"),
        ),
    )


if __name__ == "__main__":
    main()
