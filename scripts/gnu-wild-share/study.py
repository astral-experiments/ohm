"""Bounded fourfix GNU unchanged Ruff diagnostic. All artifact and runtime oracles are external to counters."""

import gzip
import json
import os
from pathlib import Path
import re
from runpy import run_path
import shutil
import subprocess
import sys
import tomllib
import traceback

HERE = Path(__file__).resolve().parent
sys.path[:0] = [
    str(HERE),
    str(HERE.parent / "ruff-integration-structure"),
    str(HERE.parent / "branch-return-pmu"),
]
import calibration, contacts, selection, suite, processes
from kernel import (
    COMMAND,
    arguments,
    classify,
    digest,
    dump,
    identity,
    load,
    require,
    snapshot,
)
from calibration import observer_args, raw_visit

B = "7b13f01ba1569887a25670820764b24c206da8e5"
TREE = "97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c"
LOCK = "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"
BRANCH = "charlie/qa-ruff-gnu-wild-share-20261031"
RUST = "625207d26ce4449c9c95d871c88cfb50e904c09f"
CARGO = "4591cf45cc10abb19d2456c40b99606e08167f29"
NATIVE = {
    "cargo": "33b8a25b5277671b0ce95070f8e749801b4f6e643efcbabc0ff08e6086a9c219",
    "rustc": "8bfdc9779937e9cd2c9ef5db9f50cee9aab03ddec5672b37a3a3c9278cf1f5d0",
    "driver": "056d6ed56a45e6997be1a79aa4e96c7bdbaced2530aad04353c8bc11f8ed4e6c",
    "wild": "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5",
}
ORDERS = (("tree", "plain"), ("plain", "tree"), ("plain", "tree"), ("tree", "plain"))
ABSENT = "/__ohm_wild_share_required_missing_provider_e9b769f__"


def enrolled_verdict(receipts, donor):
    return run_path(str(HERE / "verify.py"))["verdict"](receipts, donor)


def check_git(p, *cmd):
    return subprocess.check_output(["git", "-C", p, *cmd], text=True).strip()


def hex_json(x):
    import hashlib

    return hashlib.sha256(
        json.dumps(x, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stage(base, kit, source, out):
    q = load(kit / "qualified.json")
    require(
        q["qualified"]
        and q["members"] == 2473
        and q["source"]["run"] == 41212542603
        and q["source"]["artifact"]["id"] == 13046543047,
        "foreign source kit",
    )
    verified = q["source"]["registration"]
    require(
        verified["rust"] == RUST
        and verified["fixed"]["source"] == CARGO
        and verified["fixed"]["tree"] == "a2c9a62722e1ef849cb68874e79617c92d165a8b",
        "source pair",
    )
    home = base / "home"
    home.mkdir()
    sdk = base / "sdk"
    native = kit / "installed"
    original = native / "sdk"
    files = [f for f in original.rglob("*") if f.is_file()]
    require(
        len(files) == 2471 and not any(p.is_symlink() for p in files),
        "installed SDK layout",
    )
    for f in files:
        rel = f.relative_to(original)
        p = sdk / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        os.link(native / "roles/fourfix/cargo" if rel == Path("bin/cargo") else f, p)
    rustup = home / ".rustup/toolchains/ohm"
    rustup.parent.mkdir(parents=True)
    rustup.symlink_to(sdk, True)
    cargo_proxy = Path(shutil.which("cargo")).resolve(strict=True)
    proxy = home / ".cargo/bin"
    proxy.mkdir(parents=True)
    for command in ("cargo", "rustc", "rustdoc", "rustup"):
        (proxy / command).symlink_to(cargo_proxy)
    env = {
        "HOME": str(home),
        "PATH": str(proxy) + ":/usr/local/bin:/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "RUSTUP_HOME": str(home / ".rustup"),
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_HOME": str(home / ".cargo"),
        "CARGO_TARGET_DIR": str(base / "work/target"),
        "CARGO_BUILD_BUILD_DIR": str(base / "work/build"),
        "CARGO_NET_OFFLINE": "true",
        "CARGO_CACHE_AUTO_CLEAN_FREQUENCY": "never",
        "CARGO_TERM_COLOR": "never",
        "TMPDIR": str(base / "tmp"),
    }
    (base / "tmp").mkdir()
    (driver,) = (sdk / "lib").glob("librustc_driver-*.so")
    wild = sdk / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    cc = Path("/usr/bin/cc")
    c2 = subprocess.check_output([cc, "-print-prog-name=collect2"], text=True).strip()
    ids = {
        n: identity(p)
        for n, p in {
            "cargo": sdk / "bin/cargo",
            "rustc": sdk / "bin/rustc",
            "wild": wild,
            "cc": cc,
            "collect2": c2,
            "proxy": cargo_proxy,
        }.items()
    }
    require(
        all(ids[n]["sha256"] == NATIVE[n] for n in ("cargo", "rustc", "wild"))
        and digest(driver) == NATIVE["driver"],
        "SDK hashes",
    )
    for n, rev in (("cargo", CARGO), ("rustc", RUST)):
        require(
            "commit-hash: " + rev
            in subprocess.check_output(
                [n, "+ohm", "-vV"], env=env, text=True
            ).splitlines(),
            "source stamp",
        )
        tool = subprocess.check_output(
            ["rustup", "which", "--toolchain", "ohm", n], env=env, text=True
        ).strip()
        require(Path(tool).samefile(sdk / "bin" / n), "rustup selection")
    require(
        Path(
            subprocess.check_output(
                ["rustc", "+ohm", "--print", "sysroot"], env=env, text=True
            ).strip()
        ).samefile(sdk),
        "foreign sysroot",
    )
    require(
        check_git(source, "rev-parse", "HEAD") == B
        and check_git(source, "rev-parse", "HEAD^{tree}") == TREE
        and not check_git(source, "status", "--porcelain")
        and digest(source / "Cargo.lock") == LOCK,
        "historical Ruff",
    )
    subprocess.run(
        ["cargo", "+ohm", "fetch", "--locked"],
        env=env
        | {
            "CARGO_NET_OFFLINE": "false",
            "CARGO_TARGET_DIR": str(base / "fetch-only-target"),
            "CARGO_BUILD_BUILD_DIR": str(base / "fetch-only-build"),
        },
        cwd=source,
        check=True,
    )
    pins = {
        v["name"] + "-" + v["version"] + ".crate": v["checksum"]
        for v in tomllib.loads((source / "Cargo.lock").read_text())["package"]
        if "checksum" in v
    }
    archives = list((home / ".cargo/registry/cache").glob("*/*.crate"))
    require(
        len(archives) == len(pins) == 505
        and {f.name: digest(f) for f in archives} == pins,
        "locked registry",
    )
    dump(
        out / "inputs.json",
        {
            "rust": RUST,
            "cargo": CARGO,
            "sdk_source": q["source"],
            "ids": ids,
            "driver": identity(driver),
            "ruff": B,
            "tree": TREE,
            "lock": LOCK,
            "archives": pins,
            "source": str(source),
            "environment": env,
        },
    )
    return env, ids


def stamp(source):
    require(
        check_git(source, "rev-parse", "HEAD") == B
        and digest(source / "Cargo.lock") == LOCK
        and not check_git(source, "status", "--porcelain"),
        "changed source",
    )


def ordinary(d, env, src, expected=0, links=None):
    d.mkdir()
    argv = COMMAND
    if links is not None:
        argv = [
            "strace",
            "-f",
            "-qq",
            "--seccomp-bpf",
            "-s",
            "262144",
            "-e",
            "trace=execve,execveat",
            "-o",
            str(d / "exec.txt"),
            *COMMAND,
        ]
    p = subprocess.run(
        argv,
        cwd=src,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=1600,
    )
    for n, data in (("stdout", p.stdout), ("stderr", p.stderr)):
        (d / (n + ".gz")).write_bytes(gzip.compress(data, compresslevel=1, mtime=0))
    dump(d / "call.json", {"argv": argv, "cwd": str(src), "code": p.returncode})
    if links is not None:
        expected_wild, outputs = links
        processes.compact(d / "exec.txt", d / "exec.gz")
        with gzip.open(d / "exec.gz", "rt") as trace:
            phases = [
                (pid, exe, args)
                for pid, exe, args in processes.execs(trace)
                if Path(exe).name
                in {"ld", "ld.bfd", "ld.gold", "rust-lld", "ld.lld", "mold", "wild"}
                and "-o" in args
            ]
        require(
            len(phases) == 2
            and all(
                Path(exe).resolve(strict=True) == Path(expected_wild)
                for _, exe, _ in phases
            )
            and {arguments(a, "-o") for _, _, a in phases} == outputs,
            "provider did not link both genuine executables",
        )
        dump(d / "links.json", phases)
    require(p.returncode == expected, (d.name, p.returncode, p.stderr[-1000:]))
    return p.stdout


def artifacts(raw, src, work, cold=False):
    rows = [json.loads(l) for l in raw.splitlines()]
    require(
        rows[-1] == {"reason": "build-finished", "success": True},
        "incomplete Cargo command",
    )
    roster, dirty = selection.roster(rows, src)
    require(
        len(roster) == 390
        and hex_json(roster) == load(HERE / "structural.json")["roster_sha256"],
        "different real graph",
    )
    require(
        len(dirty) == 390
        if cold
        else sorted(x["name"] for x in dirty) == ["integration_test", "ruff"],
        "wrong dirty units",
    )
    return selection.selected_paths(rows, src, work)


def runtime(d, src, env, products, reference=None):
    d.mkdir()
    images = {
        k: {"size": p.stat().st_size, "sha256": digest(p)} for k, p in products.items()
    }
    if reference is not None:
        require(images == reference, "whole clean executable mismatch")
    verdict = suite.exercise(
        products["harness"],
        products["cli"],
        src,
        env,
        d,
        suite.permission_prefix(d),
        processes,
    )
    require(
        len(verdict["names"]) == 96 and verdict["inventory"] == suite.LIST_SHA,
        "test verdict",
    )
    dump(d / "images.json", images)
    return images


def trace_outputs(tr, paths, work, where):
    selected, owners = {}, {}
    for row in tr["rows"]:
        if row["name"] != "rustc":
            continue
        a = row["argv"]
        tag = arguments(a, "--crate-name")
        (path,) = [Path(v).with_suffix("") for v in a if v.endswith(".rlink")]
        role = {"ruff": "cli", "integration_test": "harness"}[tag]
        require(
            path.resolve(strict=True).is_relative_to(work)
            and str(path) == str(path.resolve())
            and digest(path) == digest(paths[role])
            and tag not in selected,
            "selected CLI/harness must equal Wild's actual output",
        )
        selected[tag] = str(path)
        owners[tag] = {
            "link_output": identity(path),
            "cargo_output": identity(paths[role]),
        }
    dump(where / "owners.json", owners)
    return selected


def run_four_pairs(out, src, work, env, ids, ref):
    packet = []
    for pair, order in enumerate(ORDERS, 1):
        v = {}
        for mode in order:
            stamp(src)
            where = out / f"pair-{pair}-{mode}"
            where.mkdir()
            tr = where / "trace"
            tr.mkdir()
            args = observer_args(out / "tools/observe", tr, mode, ids, COMMAND)
            raw = raw_visit(where, args, env, src)
            products = artifacts(raw, src, work)
            k = snapshot(tr, mode, ids)
            expected = trace_outputs(k, products, work, where) if mode == "tree" else {}
            v[mode] = classify(k, expected, "ruff")
            dump(where / "expected.json", expected)
            runtime(where / "native", src, env, products, ref)
            if mode == "tree":
                found = []
                for r in (r for r in k["rows"] if r["name"] == "wild"):
                    ds = [
                        Path(t[2:])
                        for t in r["argv"]
                        if t.startswith("-L") and t != "-L"
                    ]
                    (p,) = [d for d in ds if d.name == "out" and "psm" in d.parts]
                    require(
                        len(ds) == 13 and p.is_relative_to(work) and p.resolve() == p,
                        "unsafe provider challenge path",
                    )
                    found.append(str(p))
                require(len(set(found)) == 1, "different first native search")
                dump(where / "search.json", found)
        packet.append(v)
    return packet


def needed(path, tag):
    output = subprocess.check_output(["/usr/bin/readelf", "-dW", path], text=True)
    return re.findall(r"\(" + tag + r"\)[^\n]*?\[([^\]]+)\]", output)


def challenge(out, src, work, env, ref, ids):
    d = out / "native-challenge"
    d.mkdir()
    common = [load(out / f"pair-{i}-tree/expected.json") for i in range(1, 5)]
    require(all(s == common[0] for s in common), "target names changed")
    links = (ids["wild"]["path"], set(common[0].values()))
    dirs = {p for i in range(1, 5) for p in load(out / f"pair-{i}-tree/search.json")}
    require(len(dirs) == 1 and not Path(ABSENT).exists(), "unstable higher provider")
    high = Path(dirs.pop()) / "libgcc_s.so"
    require(
        high.parent.resolve() == high.parent
        and high.parent.is_relative_to(work)
        and not os.path.lexists(high),
        "provider occupied",
    )
    system = Path("/usr/lib/x86_64-linux-gnu/libgcc_s.so.1")
    body = system.read_bytes()
    orig = "libgcc_s.so.1"
    require(
        needed(system, "SONAME") == [orig] and body.count(orig.encode() + b"\0") == 1,
        "unrecognized GNU runtime",
    )
    loader = d / "loader"
    loader.mkdir()
    runtime_env = env | {"LD_LIBRARY_PATH": str(loader)}
    payload = {}
    for n in ("libgca_s.so.1", "libgcb_s.so.1"):
        payload[n] = body.replace(orig.encode() + b"\0", n.encode() + b"\0")
        (loader / n).write_bytes(payload[n])
        require(needed(loader / n, "SONAME") == [n], "provider name")
    fail = ("INPUT ( " + ABSENT + " )\n").encode().ljust(len(body), b" ")
    phases = [
        ("appeared", 0, "libgca_s.so.1"),
        ("same-stat", 0, "libgcb_s.so.1"),
        ("malformed", 101, None),
        ("repaired", 0, "libgcb_s.so.1"),
    ]
    rows = {}
    fd = os.open(high, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o644)
    ns = 1_700_000_300_000_000_000
    try:
        for label, status, n in phases:
            data = payload[n] if n else fail
            require(
                os.path.samestat(os.fstat(fd), high.stat())
                and os.pwrite(fd, data, 0) == len(body),
                "exclusive provider lost",
            )
            os.fsync(fd)
            os.utime(fd, ns=(ns, ns))
            st = os.fstat(fd)
            coord = [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]
            require(st.st_size == len(body) and st.st_mtime_ns == ns, "provider stat")
            raw = ordinary(d / label, env, src, status, links)
            rr = {
                "tuple": coord,
                "provider": digest(high),
                "expected": n,
                "code": status,
            }
            if n:
                files = artifacts(raw, src, work)
                rr["needed"] = {
                    role: needed(path, "NEEDED") for role, path in files.items()
                }
                require(
                    all(
                        v.count(n) == 1 and orig not in v for v in rr["needed"].values()
                    ),
                    "stale dynamic provider",
                )
                rr["images"] = runtime(d / label / "native", src, runtime_env, files)
                if label in ("appeared", "same-stat"):
                    need_space = shutil.disk_usage(d).free
                    require(need_space >= 3 * 2**30, "native custody floor")
                    for role, path in files.items():
                        subprocess.run(
                            [
                                "zstd",
                                "-q",
                                "-T2",
                                "-3",
                                path,
                                "-o",
                                d / label / (role + ".zst"),
                            ],
                            check=True,
                        )
            else:
                messages = [json.loads(l) for l in raw.splitlines()]
                detail = "\n".join(
                    m["message"].get("rendered", "")
                    for m in messages
                    if m.get("reason") == "compiler-message"
                )
                require(
                    messages[-1] == {"reason": "build-finished", "success": False}
                    and ABSENT
                    in detail
                    + gzip.decompress((d / label / "stderr.gz").read_bytes()).decode(),
                    "wrong malformed-provider diagnostic",
                )
            rows[label] = rr
    finally:
        if os.path.lexists(high) and os.path.samestat(os.fstat(fd), high.stat()):
            high.unlink()
        os.close(fd)
    require(not os.path.lexists(high), "provider was replaced")
    raw = ordinary(d / "removed", env, src, links=links)
    rows["removed"] = {
        "images": runtime(
            d / "removed/native", src, env, artifacts(raw, src, work), ref
        )
    }
    require(
        len({tuple(rows[n]["tuple"]) for n, _, _ in phases}) == 1
        and all(
            rows["appeared"]["images"][k] != rows["same-stat"]["images"][k] for k in ref
        )
        and rows["repaired"]["images"] == rows["same-stat"]["images"],
        "provider challenge mismatch",
    )
    dump(d / "result.json", rows)


def main(role_root, src, donor):
    run = os.environ
    base = Path(run["RUNNER_TEMP"]) / "ohm-fourfix-wild-share"
    out = base / "receipts"
    require(
        not sys.flags.optimize
        and not base.exists()
        and shutil.disk_usage(base.parent).free >= 32 * 2**30
        and run["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and run["GITHUB_RUN_ATTEMPT"] == "1"
        and run["GITHUB_REF"] == "refs/heads/" + BRANCH
        and check_git(HERE, "rev-parse", "HEAD")
        == run["REVIEWED_HEAD"]
        == run["GITHUB_SHA"],
        "run identity or capacity",
    )
    base.mkdir()
    out.mkdir()
    try:
        cpus = sorted(os.sched_getaffinity(0))[:4]
        require(len(cpus) == 4, "four real CPUs")
        os.sched_setaffinity(0, cpus)
        dump(
            out / "run.json",
            {
                "run": run["GITHUB_RUN_ID"],
                "head": run["GITHUB_SHA"],
                "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "cpus": cpus,
                "mount_namespace": os.readlink("/proc/self/ns/mnt"),
                "uname": list(os.uname()),
                "cpu_model": next(
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                "filesystem": subprocess.check_output(
                    ["findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS", "--target", base],
                    text=True,
                ).strip(),
                "paranoid": Path("/proc/sys/kernel/perf_event_paranoid")
                .read_text()
                .strip(),
                "plan": digest(HERE / "PLAN.md"),
            },
        )
        calibration.prepare(donor, out)
        calibration.controls(donor, out)
        env, ids = stage(base, role_root, src, out)
        work = base / "work"
        work.mkdir()
        for key in ("target", "build"):
            (work / key).mkdir()
        contact = out / "real-small-links"
        contact.mkdir()
        ci, cr, ct = contacts.real(
            contact,
            Path(ids["rustc"]["path"]),
            Path(ids["wild"]["path"]),
            out / "tools/observe",
        )
        contacts.mutate(contact, ci, cr, ct)
        ref = None
        for phase in ("reference-empty", "study-empty"):
            stamp(src)
            require(
                all(not any((work / k).iterdir()) for k in ("target", "build"))
                and shutil.disk_usage(work).free >= 12 * 2**30,
                "empty target/capacity",
            )
            raw = ordinary(out / phase, env, src)
            paths = artifacts(raw, src, work, True)
            old = runtime(out / phase / "native", src, env, paths, ref)
            if ref is None:
                ref = old
                for role, p in paths.items():
                    subprocess.run(
                        [
                            "zstd",
                            "-q",
                            "-T2",
                            "-3",
                            p,
                            "-o",
                            out / (role + "-clean.zst"),
                        ],
                        check=True,
                    )
                for key in ("target", "build"):
                    (work / key).rename(base / ("owned-reference-" + key))
                    (work / key).mkdir()
        run_four_pairs(out, src, work, env, ids, ref)
        challenge(out, src, work, env, ref, ids)
        stamp(src)
        for n in ids:
            require(identity(ids[n]["path"]) == ids[n], "native image changed")
        born = load(out / "inputs.json")
        require(identity(born["driver"]["path"]) == born["driver"], "driver changed")
        archives = sorted(
            (Path(env["CARGO_HOME"]) / "registry/cache").glob("*/*.crate")
        )
        require(
            len(archives) == 505
            and {p.name: digest(p) for p in archives} == born["archives"],
            "registered source archives changed",
        )
        dump(out / "qualified.json", enrolled_verdict(out, donor))
    except BaseException:
        (out / "refused.txt").write_text(traceback.format_exc())
        raise


if __name__ == "__main__":
    main(*(Path(p).resolve() for p in sys.argv[1:]))
