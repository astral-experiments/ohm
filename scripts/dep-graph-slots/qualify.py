"""Verify the precise fork delta, bootstrap it, and run the native and PGO protocols."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import layout

BIND = json.loads((HERE / "source.json").read_bytes())
GIB = 1 << 30
PARENT = BIND["historical_distribution_source"]
CHILD = BIND["candidate"]
ANCHOR = "b6f12f6fc37410de9896f4cca4a03f8cb76a35ec"
TEST = "tests/run-make/incremental-missing-query-cache"
HOSTS = {"Linux": "x86_64-unknown-linux-gnu", "Darwin": "aarch64-apple-darwin"}
BRANCH = "charlie/qa-rc22-gnu-link-inputs-20261101"


def need(cond, message):
    if not cond:
        raise ValueError(message)


def checksum(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def native_stdout(binary, expected_sha):
    if os.access(binary, os.X_OK):
        return subprocess.check_output([binary], timeout=4)
    # GitHub's artifact ZIP strips executable permissions. Keep the archived file untouched.
    with tempfile.TemporaryDirectory() as tmp:
        executable = Path(tmp) / "fixture"
        shutil.copyfile(binary, executable)
        need(checksum(executable) == expected_sha, "copied native image differs")
        executable.chmod(0o700)
        return subprocess.check_output([executable], timeout=4)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def save(p, record):
    p.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")


def guard():
    w = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    e = os.environ
    host = HOSTS[platform.system()]
    need(
        host == e["OHM_TARGET"]
        and platform.machine() == ("arm64" if host.startswith("aarch64") else "x86_64"),
        "foreign native host",
    )
    need(
        e["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and e["GITHUB_REF"] == "refs/heads/" + BRANCH
        and e["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and e["GITHUB_RUN_ATTEMPT"] == "1"
        and e["GITHUB_JOB"] == "native"
        and e["GITHUB_SHA"] == e["REVIEWED_HEAD"] == git(w, "rev-parse", "HEAD")
        and git(w, "rev-parse", "HEAD^") == ANCHOR,
        "unregistered source or job",
    )
    need(len(git(w, "status", "--porcelain", "--untracked-files=no")) == 0, "modified coordinator files")
    temp = Path(e["RUNNER_TEMP"]).resolve(strict=True)
    expected = (
        [("gnu-media", "f303f8a74c44879280427bef5dc5a0cd7dfbd39c")]
        if platform.system() == "Linux"
        else [("apple-media", "87d296ac3b05648c082193fdb91d1145652797ff")]
    )
    for name, revision in expected:
        need(git(w / name, "rev-parse", "HEAD") == revision, "foreign SDK verifier")
    return w, w / "source/rust", w / "source/reports", temp, host


def source_catalog(repo):
    q = BIND
    graph = q["graph_candidate"]
    need(
        git(repo, "rev-parse", CHILD + "^", CHILD + "^{tree}", graph + "^", graph + "^{tree}", q["parent"] + "^{tree}").splitlines()
        == [graph, q["candidate_full_tree"], q["parent"], q["graph_candidate_tree"], q["parent_full_tree"]],
        "wrong complete Rust trees",
    )
    previous = q["previous_slot_parent"]
    need(
        git(
            repo, "rev-parse", q["parent"] + "^", q["previous_slot_candidate"] + "^", previous + "^2"
        ).splitlines()
        == [previous, previous, PARENT]
        and git(repo, "rev-parse", previous + "^{tree}") == git(repo, "rev-parse", PARENT + "^{tree}"),
        "wrong historically qualified compiler sources",
    )
    old_cargo = git(repo, "rev-parse", PARENT + ":src/tools/cargo")
    for old, new, before, after in [
        (previous, q["parent"], old_cargo, q["shipped_cargo"]),
        (q["previous_slot_candidate"], graph, old_cargo, q["shipped_cargo"]),
        (graph, CHILD, q["shipped_cargo"], q["trees"]["src/tools/cargo"]),
    ]:
        raw = f":160000 160000 {before} {after} M\tsrc/tools/cargo"
        need(
            git(repo, "diff-tree", "--no-commit-id", "--no-abbrev", "-r", "--raw", old, new) == raw,
            "rebase changed more than the Cargo gitlink",
        )
    need(
        git(repo, "diff", "--name-only", q["parent"], graph).splitlines() == sorted(q["files"]),
        "unexpected changed files",
    )
    for name, row in q["files"].items():
        data = subprocess.check_output(["git", "-C", repo, "show", CHILD + ":" + name])
        need(
            git(repo, "rev-parse", q["parent"] + ":" + name, CHILD + ":" + name).splitlines()
            == [row["parent"], row["child"]]
            and len(data) == row["bytes"]
            and hashlib.sha256(data).hexdigest() == row["sha256"],
            "invalid " + name,
        )
    for name, tree in q["trees"].items():
        need(git(repo, "rev-parse", CHILD + ":" + name) == tree, "wrong " + name + " source")
    return q


def cargo_catalog(repo):
    """Check the complete four child commits and the only two changed Cargo blobs."""
    q = BIND
    shipped = q["shipped_cargo"]
    child = q["trees"]["src/tools/cargo"]
    need(git(repo, "rev-parse", shipped + "^{tree}", child + "^{tree}").splitlines() ==
         [q["shipped_cargo_tree"], q["cargo_tree"]], "different Cargo root tree")
    need(git(repo, "rev-list", "--reverse", shipped + ".." + child).splitlines() == q["cargo_commits"],
         "wrong native-input source history")
    parent = shipped
    for commit in q["cargo_commits"]:
        need(git(repo, "rev-list", "--parents", "-1", commit).split() == [commit, parent],
             "unexpected Cargo ancestry")
        parent = commit
    files = q["cargo_changed_blobs"]
    need(git(repo, "diff", "--name-only", shipped, child).splitlines() == sorted(files),
         "unregistered Cargo source file")
    for name, pair in files.items():
        need(git(repo, "rev-parse", shipped + ":" + name, child + ":" + name).splitlines() == pair,
             "different Cargo source blob in " + name)


def install_source(w, repo, r):
    need(git(repo, "rev-parse", "HEAD") == PARENT, "wrong reconstructed source donor")
    pack = HERE / "source.pack"
    raw = pack.read_bytes()
    need(
        len(raw) == BIND["pack"]["bytes"]
        and hashlib.sha256(raw).hexdigest() == BIND["pack"]["sha256"]
        and raw[:4] == b"PACK"
        and int.from_bytes(raw[8:12], "big") == BIND["pack"]["objects"],
        "unverified source transport",
    )
    subprocess.run(["git", "-C", repo, "index-pack", "--strict", "--stdin"], input=raw, check=True)
    assets = HERE / "release-22"
    for name, (length, digest) in BIND["release_files"].items():
        p = assets / name
        need(
            p.is_file() and p.stat().st_size == length and checksum(p) == digest,
            "different release input: " + name,
        )
    cargo = repo / "src/tools/cargo"
    for directory, name in [
        (repo, "rust-rebase.pack"),
        (cargo, "cargo-stack.pack"),
        (cargo, "cargo-fix.pack"),
        (repo, "rust-cargo-pin.pack"),
        (cargo, "cargo-native-resolution.pack"),
    ]:
        with (assets / name).open("rb") as stream:
            subprocess.run(
                ["git", "-C", directory, "index-pack", "--strict", "--stdin"], stdin=stream, check=True
            )
    source_catalog(repo)
    cargo_catalog(cargo)
    git(repo, "checkout", "--quiet", "--detach", BIND["parent"])
    git(cargo, "checkout", "--quiet", "--detach", BIND["shipped_cargo"])
    need(git(cargo, "rev-parse", "HEAD^{tree}") == BIND["shipped_cargo_tree"], "different shipped Cargo tree")
    # The unchanged release verifier authenticates the relative schema and the versioned path.
    with tempfile.TemporaryDirectory() as manifest_root:
        root = Path(manifest_root)
        schema = w / "toolchains/manifest.schema.json"
        need(
            git(w, "hash-object", schema) == "47956809e9a9942075dae8456c757f5516f41950",
            "different release schema",
        )
        (root / "manifest.schema.json").symlink_to(schema)
        (root / "1.99.0").mkdir()
        manifest = root / "1.99.0/22.json"
        shutil.copyfile(assets / "22.json", manifest)
        subprocess.run(
            [
                w / "scripts/verify-release-sources.sh",
                manifest,
                repo,
                cargo,
                repo / "src/tools/clippy",
                repo / "src/tools/rustfmt",
            ],
            check=True,
        )
    subprocess.run(["git", "-C", repo, "checkout", "--quiet", "--detach", CHILD], check=True)
    git(cargo, "checkout", "--quiet", "--detach", BIND["trees"]["src/tools/cargo"])
    # The production installer replaces two tracked Rust subtrees with separately pinned
    # release tool repositories. Keep the outer view before validating the complete layout.
    status = layout.git(repo, "status", "--porcelain", "-z", "--untracked-files=no", "--ignore-submodules=all")
    (r / "slot-outer-source-status.bin").write_bytes(status)
    composite = layout.checked(repo, CHILD, BIND["candidate_full_tree"], layout.TOOLS)
    observed = {os.fsdecode(row[3:]) for row in status.split(b"\0")[:-1]}
    differences = composite["authorized_differences"]
    rows = json.dumps(differences, sort_keys=True, separators=(",", ":")).encode()
    need(
        hashlib.sha256(rows).hexdigest() == "f6773fc213181fa54b43cbfbf781fe685b33e665992a1eb082c805ba81b87eb9",
        "release tool changes differ from the verified full-source rehearsal",
    )
    expected = {p for p, (old, _) in differences.items() if old is not None}
    need(observed == expected, ("unaccounted outer paths", sorted(observed ^ expected)))
    save(r / "slot-source-layout.json", composite)
    need(
        git(repo / "src/tools/cargo", "rev-parse", "HEAD") == BIND["trees"]["src/tools/cargo"],
        "wrong actual Cargo checkout",
    )
    save(
        r / "slot-source.json",
        {
            "qa": git(w, "rev-parse", "HEAD"),
            "run": int(os.environ["GITHUB_RUN_ID"]),
            "attempt": 1,
            "job": os.environ["GITHUB_JOB"],
            "target": os.environ["OHM_TARGET"],
            "source": BIND,
        },
    )


def verify_live(repo):
    need(git(repo, "rev-parse", "HEAD") == CHILD, "wrong native source")
    need(
        git(repo / "src/tools/cargo", "rev-parse", "HEAD", "HEAD^{tree}").splitlines()
        == [BIND["trees"]["src/tools/cargo"], BIND["cargo_tree"]],
        "wrong release Cargo before execution",
    )
    for name, row in BIND["files"].items():
        need(checksum(repo / name) == row["sha256"], "changed source before execution: " + name)


def rmake(w, repo, r, host):
    verify_live(repo)
    flags = [
        "--ci",
        "false",
        "--set",
        "build.submodules=false",
        "--set",
        "rust.channel=dev",
        "--set",
        "rust.omit-git-hash=false",
        "--set",
        "rust.debug-assertions=false",
        "--set",
        "rust.lto=off",
        "--set",
        "llvm.download-ci-llvm=true",
    ]
    # Never rewrite the Darwin PGO stage2 after it has been frozen. Run the native compiler test
    # through the bootstrap driver after all observations of the instrumented stage2.
    if platform.system() == "Darwin":
        flags += ["--config", str(repo / "build/ohm-release-bootstrap.toml")]
    args = [
        "./x",
        *flags,
        "--set",
        "rust.verbose-tests=true",
        "test",
        "--stage",
        "1",
        "-j8",
        "--host",
        host,
        "--target",
        host,
        TEST,
    ]
    need(
        shutil.disk_usage(repo).free > (8 if platform.system() == "Darwin" else 32) * GIB,
        "insufficient room for bootstrap test",
    )
    log = r / "slot-run-make.log"
    save(r / "slot-run-make-argv.json", args)
    with log.open("wb") as file:
        status = subprocess.run(args, cwd=repo, stdout=file, stderr=subprocess.STDOUT).returncode
    lines = log.read_text(errors="replace").splitlines()
    named = [l for l in lines if TEST in l and " ok" in l]
    footer = [l for l in lines if re.search(r"test result: ok\. 1 passed; 0 failed", l)]
    save(
        r / "slot-run-make.json",
        {"argv": args, "exit": status, "sha256": checksum(log), "named": named, "footers": footer},
    )
    if status or len(named) != 1 or not footer:
        print("\n".join(lines[-100:]), file=sys.stderr)
        raise ValueError("named native compiler test did not pass")
    return repo / "build" / host / "stage1"


def mac_identity(w, repo, r):
    verify_live(repo)
    sys.path.insert(0, str(w / "scripts/darwin-pgo-diesel"))
    import worker, identity

    work = r / "diesel-pgo"
    t = json.loads((work / "native-training.json").read_bytes())
    need(
        json.loads((work / "before-replay.json").read_bytes())["outcome"]
        == "original 9-benchmark training completed",
        "Darwin natural PGO did not finish",
    )
    log = (work / "original-opt-dist.log").read_text(errors="replace")
    worker.finished(log)
    b = json.loads((w / "apple-media/scripts/diesel-stage2-repeat/enrollment.json").read_bytes())
    roster = [
        line for line in log.splitlines() if line.startswith("Running ") and "FrontendThreads(" in line
    ]
    need(
        len(roster) == 27 and sorted(roster) == sorted(b["roster"]),
        "incomplete primary collector scenarios",
    )
    worker.collector_source(w, work, t)
    sdk = Path(t["stage"])
    need(sdk == repo / "build" / identity.HOST / "stage2", "wrong natural compiler at capture")
    cargo = Path(identity.extra(t["argv"], "--cargo"))
    (driver,) = (sdk / "lib").glob("librustc_driver-*.dylib")
    paths = {"rustc": sdk / "bin/rustc", "driver": driver, "cargo": cargo}
    profile_root = Path(os.environ["RUNNER_TEMP"]) / "slot-identity-profiles"
    profile_root.mkdir()
    env = t["base_env"] | {"LLVM_PROFILE_FILE": str(profile_root / "id_%m_%p.profraw")}
    tools = {}
    for name, p in paths.items():
        st = p.stat()
        tools[name] = {"path": str(p), "sha256": checksum(p), "ino": st.st_ino, "bytes": st.st_size}
        if name != "driver":
            vv = subprocess.check_output([p, "-vV"], env=env, text=True)
            need(
                "commit-hash: " + (CHILD if name == "rustc" else BIND["trees"]["src/tools/cargo"])
                in vv.splitlines()
                and "host: " + identity.HOST in vv.splitlines(),
                "foreign " + name,
            )
            tools[name]["vV"] = vv
    raw_otool = subprocess.check_output(["xcrun", "otool", "-l", driver], text=True)
    need(
        "sectname __llvm_prf_cnts" in raw_otool and "sectname __llvm_prf_data" in raw_otool,
        "uninstrumented driver",
    )
    (work / "slot-driver-otool.txt").write_text(raw_otool)
    need(
        any(p.stat().st_size > 0 for p in profile_root.glob("*.profraw")),
        "instrumented identity produced no profile",
    )
    save(work / "tool-identity.json", {"tools": tools})
    worker.focused(w, work)
    f = work / "focused-collector"
    q = json.loads((f / "result.json").read_bytes())
    logs = (f / "stdout").read_text(errors="replace") + (f / "stderr").read_text(errors="replace")
    need(
        q["code"] == 0
        and q["fresh_actual_collector"]
        and not q["matching_ice"]
        and q["profraw_files"] > 0
        and len(
            [
                s
                for s in logs.splitlines()
                if s.startswith("Running diesel-2.2.10: Opt + [Full, IncrFull, IncrUnchanged, IncrPatched]")
            ]
        )
        == 1
        and "Finished benchmark diesel-2.2.10 (1/1)" in logs,
        "focused Diesel Opt did not finish",
    )
    save(
        work / "slot-natural.json",
        {"primary_roster": sorted(roster), "source": CHILD, "kit": tools, "focused": q},
    )


def controls(w, repo, r, tmp, host):
    verify_live(repo)
    sdk = repo / "build" / host / ("stage2" if platform.system() == "Darwin" else "stage1")
    old = tmp / ("slot-old-apple/sdk" if platform.system() == "Darwin" else "packaged-linux-50/sdk-22")
    for label, role, kit, revision, extra in [
        ("previous", "parent", old, PARENT, []),
        ("candidate", "candidate", sdk, CHILD, []),
        (
            "previous-to-candidate",
            "candidate",
            sdk,
            CHILD,
            ["--producer-sdk", str(old), "--producer-commit", PARENT],
        ),
    ]:
        need(shutil.disk_usage(tmp).free > 4 * GIB, "less than 4 GiB free before native probes")
        cmd = [
            sys.executable,
            "-IB",
            HERE / "native.py",
            "--mode",
            role,
            "--compiler",
            kit / "bin/rustc",
            "--sdk",
            kit,
            "--commit",
            revision,
            "--out",
            r / ("slots-" + label),
            "--work",
            tmp / ("slots-" + label + "-work"),
            *extra,
        ]
        subprocess.run(cmd, check=True)
        folder = r / ("slots-" + label)
        save(folder / "verified.json", validate_native(folder, role, bool(extra)))


def validate_native(folder, role, mixed, allow_proxy=False, execute=True):
    q = json.loads((folder / "native.json").read_bytes())
    need(
        q["complete"] is True and q["mode"] == role and q["forced_collector_stamp"] == mixed,
        "missing terminal",
    )
    sources = {
        "A": "60008915cd3436c76f060f0de3cacffcc4caf6c77ef2825b6624ab21df47207f",
        "B": "203f8e97d05b1247676099bd077bb3e6b5cff5e4a23f10e567f7068bb978660d",
        "invalid": "ab37a2cda3ef4da6661431d7395240265a756a1e38bebba77a025bd507b95fd3",
    }
    need(
        {k: hashlib.sha256(v.encode()).hexdigest() for k, v in q["sources"].items()} == sources,
        "changed fixture source",
    )
    table = {r["name"]: r for r in q["steps"]}
    ordinary_bad = ["null", "duplicate", "range"]
    expected = {
        "cold-A",
        "loaded-reordered-A",
        "empty-B",
        "empty-invalid",
        "stage-build-A",
        "stage-check-A",
    }
    if mixed:
        expected.add("producer-cold-A")
    for label in [*ordinary_bad, "trailer"]:
        if role == "parent" and label != "trailer":
            expected.add(label + "-parent")
        else:
            expected.update(label + x for x in ("-require-loaded", "-invalid", "-repair-B", "-loaded-B"))
    for label in ["stage-only", "canonical-only", "both"]:
        expected.update([label + "-repair-B", label + "-loaded-B"])
    need(set(table) == expected and len(q["steps"]) == len(expected), "omitted or duplicated native sample")
    need(
        (
            q["producer"]["driver_sha256"] != q["consumer"]["driver_sha256"]
            if mixed
            else q["producer"] == q["consumer"]
        ),
        "driver role mismatch",
    )
    need(
        f"commit-hash: {CHILD if role=='candidate' else PARENT}" in q["consumer"]["vV"].splitlines(),
        "wrong native image",
    )
    need(
        table["loaded-reordered-A"]["elf"] == table["cold-A"]["elf"],
        "reordered A differs from independently cold A",
    )
    if mixed:
        switches = q["role_changes"]
        need(
            {v["producer"] for v in switches} == {False, True}
            and len({(v["device"], v["inode"], v["path"]) for v in switches}) == 1
            and {v["physical"] for v in switches} == {q["consumer"]["sysroot"], q["producer"]["sysroot"]},
            "did not preserve one native sysroot directory with each role's real standard library",
        )
    need(
        set(q["ordinary"]) == {"null", "duplicate", "range", "trailer"}
        and set(q["stage"]) == {"stage-only", "canonical-only", "both"},
        "missing physical interventions",
    )
    for name, row in table.items():
        role_src = "invalid" if name.endswith("invalid") else ("A" if name.endswith("-A") else "B")
        need(row["source_sha256"] == sources[role_src], "wrong source bytes at " + name)
        err = (folder / (name + ".stderr")).read_bytes()
        need(
            checksum(folder / (name + ".stderr")) == row["stderr_sha256"]
            and checksum(folder / (name + ".stdout")) == row["stdout_sha256"],
            "raw capture differs",
        )
        expected_tool = (
            q["producer"]
            if mixed and name in ("producer-cold-A", "stage-build-A", "stage-check-A")
            else q["consumer"]
        )
        cmd = expected_tool["command"]
        need(
            row["argv"][: len(cmd)] == cmd
            and "-Zincremental-verify-ich" in row["argv"]
            and (
                (len(cmd) == 1 and Path(cmd[0]).resolve() == Path(expected_tool["rustc"]))
                or (allow_proxy and len(cmd) == 2 and Path(cmd[0]).name == "rustc" and cmd[1] == "+ohm")
            ),
            "different enrolled invocation",
        )
        if name.endswith("-parent"):
            key = b"index out of bounds" if name.startswith("range") else b"serialized.rs:382"
            need(
                row["code"] == 101 and key in err and b"the compiler unexpectedly panicked" in err,
                "original fault not exercised",
            )
        elif name.endswith("invalid") or name.endswith("require-loaded"):
            needle = (
                b"error[E0308]"
                if name.endswith("invalid")
                else b"should be successfully loaded, but it was not"
            )
            need(
                row["code"] == 1 and needle in err and b"unexpectedly panicked" not in err,
                "wrong diagnostic",
            )
        else:
            need(
                row["code"] == 0 and b"unused variable: `unused`" in err, "accepted wrong native invocation"
            )
            if name != "stage-check-A":
                expected_text = "17\n" if name.endswith("-A") else "83\n"
                binary = folder / (row["elf"] + ".native")
                need(
                    row["native"] == expected_text
                    and checksum(binary) == row["elf"]
                    and binary.read_bytes()[:4] in (b"\x7fELF", b"\xcf\xfa\xed\xfe"),
                    "different native output",
                )
                if execute:
                    need(
                        native_stdout(binary, row["elf"]) == expected_text.encode(),
                        "wrong native replay",
                    )
                if expected_text == "83\n":
                    need(row["elf"] == table["empty-B"]["elf"], "not own clean B")
    sys.path.insert(0, str(HERE.parent / "darwin-pgo-diesel"))
    from graph_forensics import read
    from eager_header import scan

    def body(h):
        needle = folder / "bodies" / (h + ".gz")
        need(needle.stat().st_size < 4 << 20, "unexpected fixture payload size")
        with gzip.open(needle, "rb") as f:
            raw = f.read((8 << 20) + 1)
        need(len(raw) <= 8 << 20 and hashlib.sha256(raw).hexdigest() == h, "different physical cache input")
        return raw

    reordered = q["reordered"]
    first = body(reordered["before"])
    second = body(reordered["after"])
    need(
        first != second
        and read(first)["accepted"]
        and read(second)["accepted"]
        and scan(second)["all_node_headers_passed"],
        "not a valid reordered graph",
    )
    causes = {
        "null": "incoming Null",
        "duplicate": "duplicate node index",
        "range": "destination index out of range",
    }
    for kind, group in q["ordinary"].items():
        graph, cache = group["mutations"]
        need(
            graph["before"] == reordered["after"] and body(graph["before"]) != body(graph["after"]),
            "wrong directed intervention",
        )
        if kind in causes:
            need(scan(body(graph["after"]))["failure"] == causes[kind], "wrong physical slot failure")
        else:
            need(body(graph["before"])[:-1] == body(graph["after"])[:-1], "different trailer control")
        need(
            body(cache["after"])[-21:-13] == bytes([255]) * 8
            and body(cache["after"])[:-21] == body(cache["before"])[:-21],
            "not the enrolled independently poisoned query cache",
        )
        need(
            group["unusable_workproducts"] and all(body(h) for _, h in group["unusable_workproducts"]),
            "missing hardware object",
        )
    for rows in q["stage"].values():
        for row in rows:
            if "cause" in row:
                need(body(row["before"]) != body(row["after"]), "unchanged stage input")
                if row["cause"] in causes:
                    need(scan(body(row["after"]))["failure"] == causes[row["cause"]], "wrong stage defect")
            elif "removed" in row:
                need(
                    row["removed"] == "query-cache.bin" and body(row["sha"]), "wrong prior canonical query"
                )
            else:
                need(
                    row["unusable_workproducts"] and all(body(h) for _, h in row["unusable_workproducts"]),
                    "missing stage objects",
                )
    return {
        "mode": role,
        "mixed": mixed,
        "visits": len(table),
        "native_json": checksum(folder / "native.json"),
        "consumer": q["consumer"],
        "producer": q["producer"],
        "B": table["empty-B"]["elf"],
        "native_reexecuted": execute,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["source", "catalog", "rmake", "mac", "native", "read"])
    p.add_argument("repo", type=Path, nargs="?")
    p.add_argument("--role", choices=["parent", "candidate"])
    p.add_argument("--mixed", action="store_true")
    p.add_argument("--bytes-only", action="store_true")
    p.add_argument("--local-ohm-proxy", action="store_true")
    a = p.parse_args()
    if a.action == "read":
        need(a.role and a.repo, "read needs explicit input and role")
        print(
            json.dumps(
                validate_native(
                    a.repo, a.role, a.mixed, allow_proxy=a.local_ohm_proxy, execute=not a.bytes_only
                ),
                sort_keys=True,
                indent=2,
            )
        )
    elif a.action == "catalog":
        print(json.dumps(source_catalog(a.repo), indent=2, sort_keys=True))
    else:
        w, repo, r, tmp, host = guard()
        if a.action == "source":
            install_source(w, repo, r)
        elif a.action == "rmake":
            rmake(w, repo, r, host)
        elif a.action == "mac":
            mac_identity(w, repo, r)
        else:
            controls(w, repo, r, tmp, host)
