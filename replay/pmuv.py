from pathlib import Path
import hashlib, json, os, re, shutil, subprocess, sys, time, resource, collections

wd = Path.cwd()
root = Path(os.environ["RUNNER_TEMP"]) / "replay"
root.mkdir()
out = wd / "counts"
out.mkdir()
inputs = wd / "scripts/session_replays"
path = inputs / "uv-rust-1.100.json"
assert (
    hashlib.sha256(path.read_bytes()).hexdigest()
    == "c170332ff7f94e271e16914f03346fe3a61f83f348f2af0906ff97ede7935158"
)
fixture = json.loads(path.read_text())
sdk = root / "sdk"
kit = wd / "kits"
source = wd / "source"
target = root / "targets/uv/ohm/0"
shared = root / "shared-build/uv/0"
uvcache = root / "uv-cache"
measured = sys.argv[1].endswith("p")

archives = {
    "4": next((kit/"4").rglob("*.tar.gz.sha256")).read_text().split()[0],
    "2": "a6a1621e4581940e93ff7f9720b6102f6589185539650633a4235410f0bbd26d",
    "3": "7fc3d21a5efad6bff7be654b14e0e60aa2fbbfd11db198582788f3cc4bcf7591",
}


def run(*args, **opts):
    subprocess.run(list(map(str, args)), check=True, **opts)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=source)


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def install(arm, selector):
    (tarball,) = list((kit / arm).rglob("*.tar.gz"))
    rustdir = "rust-1.100.0-dev-x86_64-unknown-linux-gnu"
    assert digest(tarball) == archives[arm]
    run("tar", "xzf", tarball, "-C", root)
    run(
        "sh",
        root / rustdir / "install.sh",
        "--prefix=" + str(sdk),
        "--disable-ldconfig",
        "--without=rust-docs",
    )
    shutil.rmtree(root / rustdir)
    run("rustup", "toolchain", "link", selector, sdk)
    return archives[arm]


def cache():
    sizes = collections.Counter()
    files = collections.Counter()
    for p in target.rglob("llvmcache-*"):
        if p.is_file():
            with p.open("rb") as f:
                name = f.read(8)
            family = "leaf" if name == b"OHMLEAF1" else "other"
            sizes[family] += p.stat().st_size
            files[family] += 1
    return dict(bytes=dict(sizes), files=dict(files))


def rusage():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime, usage.ru_stime


def arm(tag):
    selector = "ohm-1.100.0-" + tag
    archive = install(tag, selector)
    d = out / tag
    d.mkdir()
    git("reset", "--hard", fixture["base_revision"])
    for setup in fixture["setup_patches"]:
        patch = inputs / setup["patch"]
        assert digest(patch) == setup["sha256"]
        git("apply", str(patch))
    env = {
        k: os.environ[k]
        for k in (
            "PATH",
            "HOME",
            "USER",
            "LANG",
            "TMPDIR",
            "LOGNAME",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        )
        if k in os.environ
    }
    env.update(fixture["environment"])
    env.update(
        CARGO_BUILD_JOBS="8",
        RUSTUP_TOOLCHAIN=selector,
        MEASURE_CLIPPY=str(sdk / "bin/clippy-driver"),
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_BUILD_DIR=str(shared),
        CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST="all",
        CARGO_TERM_COLOR="never",
        UV_CACHE_DIR=str(uvcache),
        UV_PYTHON=sys.executable,
        UV_PYTHON_DOWNLOADS="never",
    )
    run(
        "cargo",
        "+" + selector,
        "fetch",
        "--locked",
        "--target",
        "x86_64-unknown-linux-gnu",
        env=env,
        cwd=source,
    )
    env["CARGO_NET_OFFLINE"] = "true"
    rows = []
    for idx, step in enumerate(fixture["warmup"] + fixture["steps"]):
        if step["kind"] == "edit":
            patch = (
                (inputs / step["patch"]).read_bytes()
                if "patch" in step
                else git("diff", "--binary", step["parent"], step["commit"])
            )
            run("git", "apply", "-", input=patch, cwd=source)
            continue
        assert step["program"] == "cargo"
        receipt = d / f"{idx}.tsv"
        cmd = ["cargo", "+" + selector, *step["args"]]
        print(tag, idx, cmd, flush=True)
        if measured:
            cmd = [wd / "meter", sdk / "bin/rustc", receipt, *cmd]
        path = receipt.with_suffix(".log")
        with path.open("w") as f:
            u0, s0 = rusage()
            t0 = time.perf_counter()
            proc = subprocess.run(
                cmd, cwd=source, env=env, stdout=f, stderr=subprocess.STDOUT
            )
            elapsed = time.perf_counter() - t0
            u1, s1 = rusage()
        log = path.read_text()
        if proc.returncode:
            print(log[-2000:], flush=True)
            proc.check_returncode()
        n = 0
        compiler = {}
        tests = []
        if measured:
            n = int(receipt.with_suffix(".tsv.tree").read_text().split()[0])
            for line in receipt.read_text().splitlines():
                pid, crate, kind, count, enabled, running, elapsed_image, cpu = (
                    line.split()
                )
                if kind == "test-tree":
                    tests.append(
                        dict(
                            test=crate,
                            instructions=int(count),
                            cpu=float(cpu),
                            elapsed=float(elapsed_image),
                        )
                    )
                else:
                    compiler[crate] = compiler.get(crate, 0) + int(count)
        count = sum(map(int, re.findall(r"running (\d+) tests?", log)))
        finished = re.findall(r"Finished .* target\(s\) in (.*)", log)
        crates = sorted(
            re.findall(r"^\s*(?:Checking|Compiling) (\S+) v", log, re.MULTILINE)
        )
        durations = [
            float(v) for v in re.findall(r"test result: .* finished in ([\d.]+)s", log)
        ]
        rows.append(
            dict(
                step=idx,
                label=step["label"],
                instructions=n,
                compiler=compiler,
                elapsed=elapsed,
                user=u1 - u0,
                system=s1 - s0,
                tests_started=count,
                test_trees=tests,
                finished=finished,
                test_durations=durations,
                crates=crates,
            )
        )
        (d / "rows.json").write_text(json.dumps(rows, indent=2))
    git("add", "-A")
    tree = git("write-tree").decode().strip()
    assert tree == "870eab48e6d8909e507cfddd75394fb5b4cd4bc3", tree
    assert [s["tests_started"] for s in rows[6:]] == [
        9,
        55,
        1,
        0,
        0,
        9,
        0,
        12,
        0,
        55,
        0,
        1,
        12,
        0,
    ]
    inventory = cache()
    for p in (sdk, target, shared, uvcache):
        if p.is_dir():
            shutil.rmtree(p)
    return dict(tree=tree, archive=archive, cache=inventory, rows=rows)


result = {t: arm(t) for t in sys.argv[1][:2]}
(out / "counts.json").write_text(json.dumps(result, indent=2))
