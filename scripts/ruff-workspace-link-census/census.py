"""Count actual native links in the historic Ruff workspace under signed Ohm 1.99.0-22."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-default-owner-pmu"))
import acquire
import common

RUFF = "93526150df078af7dd8fc4226cdcc469539d2001"
LOCK = "c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf"
COMMAND = [
    "cargo",
    "+ohm",
    "test",
    "--workspace",
    "--no-run",
    "--locked",
    "--offline",
    "-j8",
    "--message-format=json",
]
TEST = "workspace_folders::single_file_workspace"


def put(path, value):
    with path.open("x") as out:
        json.dump(value, out, indent=2)
        out.write("\n")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def sha(path):
    with path.open("rb") as inp:
        return hashlib.file_digest(inp, "sha256").hexdigest()


def paths():
    work = Path(os.environ["RUNNER_TEMP"]).resolve() / "ohm-ruff-whole-census"
    return work, work / "evidence", work / "rustup/toolchains/ohm"


def install():
    work, evidence, sdk = paths()
    assert git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
    assert (
        os.environ["GITHUB_REPOSITORY"] == common.REPO and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
    )
    assert os.environ["GITHUB_REF_NAME"] == "charlie/qa-ruff-workspace-link-census-20261102"
    work.mkdir()
    evidence.mkdir()
    tag = "ohm-1.99.0-22"
    asset = common.SDK["asset"]
    public = json.loads(
        subprocess.check_output(["gh", "api", "repos/" + common.REPO + "/releases/tags/" + tag])
    )
    (row,) = [x for x in public["assets"] if x["id"] == asset["id"]]
    assert public["tag_name"] == tag and not public["draft"] and row["name"] == asset["name"]
    assert row["size"] == asset["size"] and row["digest"] == "sha256:" + asset["sha256"]
    package = work / "signed.tar.gz"
    with package.open("xb") as out:
        subprocess.run(
            [
                "gh",
                "api",
                "-H",
                "Accept: application/octet-stream",
                "repos/" + common.REPO + "/releases/assets/" + str(asset["id"]),
            ],
            stdout=out,
            check=True,
        )
    manifest = acquire.extract(package, sdk)
    acquire.verify_sdk(sdk)
    put(
        evidence / "identity.json",
        {
            "run": int(os.environ["GITHUB_RUN_ID"]),
            "sha": os.environ["GITHUB_SHA"],
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "worker": os.environ["RUNNER_NAME"],
            "sdk": manifest,
            "release_asset": asset,
            "ruff": RUFF,
            "lock": LOCK,
        },
    )


def environment(work, sdk):
    proxy = Path(shutil.which("rustup")).absolute().parent
    env = {
        "HOME": str(work / "home"),
        "PATH": str(proxy) + ":/usr/bin:/bin",
        "RUSTUP_HOME": str(work / "rustup"),
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_HOME": str(work / "cargo"),
        "CARGO_TARGET_DIR": str(work / "target"),
        "CARGO_BUILD_BUILD_DIR": str(work / "build"),
        "LD_LIBRARY_PATH": str(sdk / "lib"),
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    for tool in ("cargo", "rustc"):
        selected = Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "ohm", tool], env=env, text=True
            ).strip()
        )
        assert (
            selected.samefile(sdk / "bin" / tool)
            and sha(selected) == common.SDK["members"]["bin/" + tool][3]
        )
        assert "ohm-1.99.0-22" in subprocess.check_output([tool, "+ohm", "-vV"], env=env, text=True)
    return env


def cargo_phase(phase, cli, source, env, work, evidence):
    folder = evidence / phase
    folder.mkdir()
    start = time.monotonic_ns()
    with (folder / "stdout.jsonl").open("xb") as out, (folder / "stderr").open("xb") as err:
        proc = subprocess.run(cli, cwd=source, env=env, stdout=out, stderr=err, timeout=3600)
    put(
        folder / "command.json",
        {
            "argv": list(map(str, cli)),
            "returncode": proc.returncode,
            "elapsed_ns": time.monotonic_ns() - start,
        },
    )
    assert proc.returncode == 0, (phase, (folder / "stderr").read_bytes()[-2500:])
    rows = [json.loads(l) for l in (folder / "stdout.jsonl").read_bytes().splitlines()]
    assert (
        rows[-1] == {"reason": "build-finished", "success": True}
        and sum(x["reason"] == "build-finished" for x in rows) == 1
    )
    arts = [x for x in rows if x["reason"] == "compiler-artifact"]
    assert len(arts) >= 500
    products = []
    native = {}
    ron = []
    for x in arts:
        files = [Path(p) for p in x["filenames"]]
        assert all(p.is_file() and p.resolve().is_relative_to(work) for p in files)
        key = (
            x["package_id"],
            x["target"]["name"],
            tuple(x["target"]["kind"]),
            x["profile"]["test"],
            tuple(sorted(map(str, files))),
        )
        products.append({"key": key, "fresh": x["fresh"]})
        if x.get("executable"):
            p = Path(x["executable"])
            assert p.is_file() and p.resolve().is_relative_to(work)
            native[str(p)] = sha(p)
        if x["target"]["name"] == "ron":
            ron.extend(
                {
                    "path": str(p),
                    "sha256": sha(p),
                    "size": p.stat().st_size,
                    "mtime_ns": p.stat().st_mtime_ns,
                }
                for p in files
            )
    inventory = sorted(json.dumps(x["key"]) for x in products)
    dirty = sorted(json.dumps(x["key"]) for x in products if not x["fresh"])
    tests = [
        Path(x["executable"])
        for x in arts
        if x.get("executable")
        and x["target"]["name"] == "e2e"
        and x["target"]["src_path"].startswith(str(source / "crates/ty_server"))
    ]
    assert len(tests) == 1
    test = subprocess.run(
        [tests[0], "--exact", TEST, "--nocapture"],
        cwd=source,
        env=env,
        capture_output=True,
        timeout=45,
    )
    (folder / "native.stdout").write_bytes(test.stdout)
    (folder / "native.stderr").write_bytes(test.stderr)
    assert (
        test.returncode == 0
        and ("test " + TEST + " ... ok").encode() in test.stdout
        and b"1 passed" in test.stdout
    )
    summary = {
        "count": len(arts),
        "dirty": dirty,
        "inventory": inventory,
        "native": native,
        "ron": ron,
        "ty_e2e": str(tests[0]),
        "test": TEST,
    }
    put(folder / "result.json", summary)
    return summary


def genealogy(folder):
    parents = {}
    processes = []
    for path in sorted(folder.glob("exec.[0-9]*")):
        pid = int(path.suffix[1:])
        for line in path.read_text(errors="replace").splitlines():
            child = re.search(
                r"^(?:clone3?\(|fork\(|vfork\(|<\.\.\. (?:clone3?|fork|vfork) resumed>).* = (\d+)\s*$",
                line,
            )
            if child:
                ident = int(child[1])
                assert parents.get(ident, pid) == pid
                parents[ident] = pid
            if not re.search(r" = 0\s*$", line):
                continue
            exe = re.match(r'^(?:execve\(|execveat\([^,]+, )"([^"\\]+)"', line)
            if not exe:
                continue
            name = Path(exe[1]).name
            owner = re.search(r'"--crate-name", "([^"\\]+)"', line)
            processes.append(
                {
                    "pid": pid,
                    "path": exe[1],
                    "name": name,
                    "owner": owner[1] if owner and name == "rustc" else None,
                    "link_only": bool(re.search(r'"(?:-Z)?link-only(?:[="]|$)', line)),
                    "linker": name
                    in {"ld", "ld.wild", "wild", "rust-lld", "ld.lld", "ld.bfd", "ld.gold", "mold"}
                    or name.endswith(("-ld", "-ld.wild", "-ld.bfd", "-ld.lld", "-ld.gold")),
                }
            )
    owners = {r["pid"]: r for r in processes if r["owner"]}
    assert any(r["name"] == "cargo" for r in processes)
    for r in processes:
        if not r["linker"]:
            continue
        pid = r["pid"]
        seen = set()
        while pid not in owners and pid in parents:
            assert pid not in seen
            seen.add(pid)
            pid = parents[pid]
        r["owning_rustc"] = owners.get(pid)
    return {
        "parents": parents,
        "processes": processes,
        "linkers": [r for r in processes if r["linker"]],
    }


def study(source):
    work, evidence, sdk = paths()
    assert git(source, "rev-parse", "HEAD") == RUFF and not git(source, "status", "--porcelain=v1")
    lock = (source / "Cargo.lock").read_bytes()
    assert hashlib.sha256(lock).hexdigest() == LOCK and not any(
        k in os.environ
        for k in ("GH_TOKEN", "GITHUB_TOKEN", "RUSTFLAGS", "RUSTC_WRAPPER", "LD_PRELOAD")
    )
    (work / "home").mkdir()
    env = environment(work, sdk)
    expected = {
        p["name"] + "-" + p["version"] + ".crate": p["checksum"]
        for p in tomllib.loads(lock.decode())["package"]
        if "source" in p
    }
    assert len(expected) == 498
    with (evidence / "fetch.log").open("wb") as log:
        subprocess.run(
            ["cargo", "+ohm", "fetch", "--locked"],
            cwd=source,
            env=env,
            stdout=log,
            stderr=log,
            check=True,
            timeout=900,
        )
    archives = list((Path(env["CARGO_HOME"]) / "registry/cache").glob("*/*.crate"))
    assert len(archives) == len(expected) and {p.name: sha(p) for p in archives} == expected
    put(evidence / "registry.json", expected)
    assert shutil.disk_usage(work).free >= 40 * 1024**3
    results = {}
    for name in ("cold", "ordinary", "traced", "fingerprint"):
        argv = COMMAND
        extra = env
        if name == "traced":
            argv = [
                "strace",
                "-ff",
                "-qq",
                "-v",
                "-e",
                "trace=%process",
                "-e",
                "signal=none",
                "-s",
                "4096",
                "-o",
                str(evidence / name / "exec"),
                "--",
                *argv,
            ]
        elif name == "fingerprint":
            extra = dict(env, CARGO_LOG="cargo::compiler::fingerprint=trace")
        results[name] = cargo_phase(name, argv, source, extra, work, evidence)
        if name != "cold":
            assert results[name]["inventory"] == results["cold"]["inventory"] and set(
                results[name]["native"]
            ) == set(results["cold"]["native"]), name
            diff = {
                p: [results["cold"]["native"][p], v]
                for p, v in results[name]["native"].items()
                if results["cold"]["native"][p] != v
            }
            put(evidence / name / "changed-native.json", diff)
        if name == "traced":
            tree = genealogy(evidence / name)
            put(evidence / "native-processes.json", tree)
    traces = results["traced"]
    ordinary = results["ordinary"]
    fingerprint = results["fingerprint"]
    assert ordinary["dirty"] == traces["dirty"] == fingerprint["dirty"]
    logs = (evidence / "fingerprint/stderr").read_bytes()
    assert b"cargo::compiler::fingerprint" in logs
    sys.path.insert(0, str(HERE.parent / "ruff-workspace-remat"))
    import link_trace

    (evidence / "fingerprints").mkdir()
    link_trace.dependency_markers(
        type("Files", (), {"sha": staticmethod(sha), "put": staticmethod(put)}), work, evidence
    )
    assert not git(source, "status", "--porcelain=v1")
    put(
        evidence / "qualified.json",
        {
            "command": COMMAND,
            "products": ordinary["count"],
            "dirty": len(ordinary["dirty"]),
            "executables": len(ordinary["native"]),
            "ron": ordinary["ron"],
            "native_link_executions": len(tree["linkers"]),
            "owners": Counter(
                (r.get("owning_rustc") or {}).get("owner", "unattributed") for r in tree["linkers"]
            ),
            "trace_matches_uninstrumented": True,
            "fingerprint_lines": sum(
                b"cargo::compiler::fingerprint" in l for l in logs.splitlines()
            ),
        },
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["install"]:
        install()
    else:
        study(Path(sys.argv[1]).resolve(strict=True))
