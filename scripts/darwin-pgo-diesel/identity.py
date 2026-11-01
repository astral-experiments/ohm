"""Validate the original opt-dist invocation, native failure and staged source."""

import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
HOST = "aarch64-apple-darwin"
RUST = "1bc7b35699479d5899a2935d79392b7bdaf7497d"
ALIGNED = "c5178286c2661c22ef4ed304d7213589483548ee"
TREE = "bbfe1faca29784b74e01830873eae7d8f27b52f0"
CARGO = "4591cf45cc10abb19d2456c40b99606e08167f29"
PERF = "0a054b0ead56e41a4584bfab6fdc1a5fad2aedc3"
BENCHES = "externs,ctfe-stress-5,cargo-0.87.1,token-stream-stress,match-stress,tuple-stress,diesel-2.2.10,bitmaps-3.2.1,serde-1.0.219-new-solver"
ERROR = "node_header.node().kind != DepKind::Null && node.kind == DepKind::Null"
Q = Path("src/query_dsl/mod.rs")
PERF_DIESEL = Path("collector/compile-benchmarks/diesel-2.2.10")
HEALTHY_A = "3016a57698d460cb43aa038cfe44d44ab64ec3d9f408b474c4feea49daac4202"
PATCHED_B = "88f069a69a62ed540f34441bba8b2567515470819ab36426bf1c4daeb969fa4a"
ALLOW_ENV = set(
    "PATH HOME RUST_BOOTSTRAP_CONFIG DIST_TRY_BUILD GITHUB_ACTIONS USER LOGNAME LANG LC_ALL LC_CTYPE TERM TMPDIR RUNNER_TEMP GITHUB_STEP_SUMMARY CARGO_HOME RUSTUP_HOME CC CXX AR RANLIB CFLAGS CXXFLAGS LDFLAGS DEVELOPER_DIR SDKROOT MACOSX_DEPLOYMENT_TARGET MACOSX_STD_DEPLOYMENT_TARGET __CF_USER_TEXT_ENCODING RUST_BACKTRACE".split()
)
SECTION = "Stage 1 (rustc + rustdoc + cargo + clippy + rustfmt PGO) > Gather rustc profiles"


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write(path, data):
    with Path(path).open("x") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def text(cmd):
    return subprocess.check_output(list(map(str, cmd)), text=True).strip()


def one(items, description):
    need(len(items) == 1, description + f" ({len(items)})")
    return items[0]


def extra(argv, key):
    i = one([i for i, a in enumerate(argv) if a == key], key)
    return argv[i + 1]


def trace(log):
    """Use the command emitted by opt-dist before running the collector."""
    raw = one(
        [
            line
            for line in log.splitlines()
            if "opt_dist::exec] Executing " in line
            and " --bin collector -- profile_local eprintln " in line
            and " --profiles Check,Debug,Opt " in line
            and "diesel-2.2.10" in line
        ],
        "rustc training command",
    )
    quoted = raw.split("Executing " + chr(96), 1)[1].removesuffix(chr(96)).split(" [at ", 1)
    need(len(quoted) == 2 and quoted[1].endswith("]"), "missing recorded collector cwd")
    cwd = Path(quoted[1][:-1])
    parts = shlex.split(quoted[0])
    expected_begin = ["run", "-p", "collector", "--bin", "collector", "--", "profile_local", "eprintln"]
    need(parts[4:12] == expected_begin, "different stage0/collector command")
    # bin/rustc -> bin -> stage2 -> <triple> -> build
    root = Path(parts[12])
    stage = root.parents[1]
    target = stage.parent
    build = target.parent
    need(target.name == HOST and stage.name == "stage2" and build.name == "build", "wrong native stage2")
    need(root == stage / "bin/rustc" and parts[3] == str(target / "stage0/bin/cargo"), "wrong stage executables")
    need(
        parts[13:]
        == [
            "--id",
            "Test",
            "--cargo",
            str(target / "stage2-tools-bin/cargo"),
            "--profiles",
            "Check,Debug,Opt",
            "--scenarios",
            "All",
            "--exact-match",
            BENCHES,
            "--jobs",
            "4",
        ],
        "different rustc-perf arguments or concurrency",
    )
    env = dict(a.split("=", 1) for a in parts[:3])
    need(
        env
        == {
            "LLVM_PROFILE_FILE": str(build / "opt-artifacts/rustc-pgo/default_%m_%p.profraw"),
            "RUSTC": str(target / "stage0/bin/rustc"),
            "RUSTC_BOOTSTRAP": "1",
        },
        "different opt-dist collector environment",
    )
    need(cwd == build / "opt-artifacts/rustc-perf", "wrong collector checkout")
    envlines = ("\n" + log).split("\nEnvironment values\n")
    need(len(envlines) == 2, "missing or duplicate opt-dist environment")
    values = dict(row.split("=", 1) for row in envlines[1].split("\n::endgroup::", 1)[0].splitlines())
    need(
        set(values) <= ALLOW_ENV
        and values["GITHUB_ACTIONS"] == "false"
        and values["DIST_TRY_BUILD"] == "0"
        and values["RUST_BOOTSTRAP_CONFIG"] == str(build / "ohm-release-bootstrap.toml"),
        "unexpected opt-dist environment",
    )
    return {
        "argv": parts[3:],
        "env": env,
        "base_env": values,
        "cwd": str(cwd),
        "stage": str(stage),
        "build": str(build),
    }


def diagnosis(log, training, exact=True):
    message = "command did not complete successfully: "
    options = [
        shlex.split(line[len(message) :])
        for line in log.splitlines()
        if line.startswith(message) and '"--crate-name" "diesel"' in line
    ]
    v = one(options, "failed real Diesel invocation")
    need(
        v[:2] == ["RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER=rustc-perf", "RUSTC_FORCE_RUSTC_VERSION=rustc-perf"]
        and v[2] == training["argv"][9],
        "wrong compiler/harness stamps",
    )
    args = v[2:]
    need(
        extra(args, "--crate-name") == "diesel"
        and "src/lib.rs" in args
        and extra(args, "--crate-type") == "lib"
        and "--emit=dep-info,metadata,link" in args
        and "opt-level=3" in args
        and "-Zincremental-verify-ich" in args
        and [a for a in args if a.startswith("-Zthreads=")][-1:] == ["-Zthreads=1"],
        "different failed Rust command",
    )
    inc = Path(one([a.partition("=")[2] for a in args if a.startswith("incremental=")], "incremental state"))
    need(
        inc.is_absolute()
        and inc.name == "incremental-state"
        and re.fullmatch(r"\.tmp[A-Za-z0-9]+", inc.parent.name),
        "wrong collector timing directory",
    )
    dirs = re.findall(r"^stderr=\s+Compiling diesel v2\.2\.10 \((.+)\)$", log, re.MULTILINE)
    cwd = Path(one(dirs, "failed Cargo manifest directory"))
    need(cwd.name == inc.parent.name, "two different timing roots")
    if exact:
        need(
            "serialized.rs:382:13" in log
            and ERROR in log
            and "SerializedDepGraph>::decode" in log
            and "setup_dep_graph" in log,
            "another Rust failure",
        )
        need(
            "collector/src/compile/benchmark/mod.rs:527" in log
            and "Failed to profile 'diesel-2.2.10' with Eprintln" in log,
            "different collector phase",
        )
    return {"argv": args, "explicit_env": dict(t.split("=", 1) for t in v[:2]), "inc": str(inc), "cwd": str(cwd)}


def host_sources(work):
    manifest = json.loads((work / "toolchains/1.99.0/22.json").read_bytes())
    aligned = json.loads((HERE / "aligned-manifest.json").read_bytes())
    need(
        sha(HERE / "aligned-manifest.json") == "03d0d484c81c5ed7ad28c95285bc111657a8c2a79f477eb6b74db4a6b463ec28",
        "different aligned manifest",
    )
    need(
        manifest["sources"]["rust"]["revision"] == RUST and aligned["sources"]["rust"]["revision"] == ALIGNED,
        "different release pins",
    )
    aligned["sources"]["rust"]["revision"] = RUST
    need(manifest == aligned, "release manifests differ elsewhere")
    body = (HERE / "aligned-rust.commit").read_bytes()
    need(
        hashlib.sha1(b"commit " + str(len(body)).encode() + b"\0" + body).hexdigest() == ALIGNED
        and body.splitlines()[0] == ("tree " + TREE).encode(),
        "invalid aligned complete tree",
    )
    rust = work / "source/rust"
    for name, exp in [(rust, RUST), (rust / "src/tools/cargo", CARGO)]:
        need(text(["git", "-C", name, "rev-parse", "HEAD"]) == exp, "wrong release compiler or Cargo source")
    need(
        text(["git", "-C", rust, "rev-parse", "HEAD^{tree}"]) == TREE
        and text(["git", "-C", rust, "rev-parse", "HEAD:src/tools/rustc-perf"]) == PERF,
        "wrong product tree or collector pin",
    )
    for name, check in {
        "scripts/build-optimized-dist.sh": "8c18058724d2135950706543ddfcc489d641bbd644ff063ab4124c3752817c4c",
        "release/bootstrap.toml": "5822d2ae682a27193ef413f013281b0849797c88c78545607ab563ea48f87684",
    }.items():
        need(sha(work / name) == check, "different release build configuration")
