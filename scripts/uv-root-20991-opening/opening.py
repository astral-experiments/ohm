"""One actual unscored root opening. Keep ordinary, traced, diagnostic and cold visits separate."""

from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import unquote
from zipfile import ZipFile, ZIP_DEFLATED
import gzip, hashlib, importlib.util, json, os, platform, re, shutil, subprocess, sys, tempfile, tomllib, traceback

H = Path(__file__).resolve().parent
sys.path.insert(0, str(H))
import sdk, native, trace as scoped
from sdk import CFG, read, save, sha, check

ROOT = Path("/tmp/uv-workflow-search")
SRC = ROOT / "uv"
TARGET = ROOT / "target"
SDK = ROOT / "sdk"
HOME = ROOT / "home"
CARGO_HOME = ROOT / "cargo"
RUSTC = SDK / "bin/rustc"
ENV = CFG["workload_environment"]
PLAIN = CFG["unscored_argv"]
DIAG = [*PLAIN, "--timings", "--message-format=json-render-diagnostics", "-vv"]
CASE = CFG["case"]
B = CASE["B"]
C = CASE["C"]
REG = {"source": CFG["full_source"]}
GIB = 1 << 30


def load(n, p):
    spec = importlib.util.spec_from_file_location(n, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def initialize(folder):
    check(
        sha(H / "readers.zip") == CFG["reader_sha256"]
        and sha(H / "reference.json") == CFG["reference_sha256"],
        "portable sources or exact compiler input reference changed",
    )
    folder.mkdir()
    with ZipFile(H / "readers.zip") as z:
        check(
            len(z.infolist()) == 14
            and z.testzip() is None
            and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in z.namelist()),
            "untrusted reader layout",
        )
        z.extractall(folder)
    m = load("opening_oracle", folder / "oracle.py")
    o = m.Opening(folder)
    source = load("source", folder / "check-root-20261101/second-edit-20991/source.py")
    sys.modules["source"] = source

    def git(env, *args, input=None):
        return subprocess.check_output(["git", "-C", SRC, *args], env=env, input=input)

    o.arm.core = NS(READ=read, LANE=ROOT, SRC=SRC, TARGET=TARGET, SDK=SDK, RUSTC=RUSTC, git=git)
    o.arm.a = NS(save=save, sha=sha)
    return m, o, source


def rm(p):
    if not p.exists():
        return
    assert p.parent == ROOT and p.name in (
        "home",
        "uv",
        "target",
        "cargo",
        "sdk",
        "frozen-B",
        "witness-target",
        "fixture-runtime",
    )
    assert not p.is_symlink()
    shutil.rmtree(p)


def cp(src, dst):
    assert src.is_dir() and not dst.exists()
    subprocess.run(["/usr/bin/cp", "-a", "--reflink=auto", src, dst], check=True)


def used(p):
    return int(subprocess.check_output(["/usr/bin/du", "-s", "-B1", p], text=True).split()[0])


def capacity(out, name, paths, floors):
    vals = {
        str(p): {"real": str(p.resolve()), "device": p.stat().st_dev, "free": shutil.disk_usage(p).free}
        for p in paths
    }
    save(out / (name + ".json"), vals)
    assert all(vals[str(p)]["free"] >= n for p, n in zip(paths, floors, strict=True)), (
        "insufficient scratch",
        name,
        vals,
        floors,
    )


def env_proof(out):
    assert (
        os.uname().machine == "x86_64"
        and sys.version_info[:2] == (3, 12)
        and sys.executable == "/usr/bin/python3.12"
    )
    v = subprocess.check_output(
        ["/usr/bin/python3.12", "-ISB", "-c", "import sys;print(sys.executable);print(sys.version)"],
        env=scoped.CLEAN,
        text=True,
    )
    assert v.startswith("/usr/bin/python3.12\n3.12.")
    s = subprocess.check_output(["/usr/bin/strace", "--version"], env=scoped.CLEAN, text=True)
    cpus = {}
    for i in sorted(os.sched_getaffinity(0)):
        t = Path("/sys/devices/system/cpu") / f"cpu{i}" / "topology"
        key = tuple((t / k).read_text().strip() for k in ("physical_package_id", "core_id"))
        cpus.setdefault(key, i)
    assert len(cpus) >= 8
    chosen = sorted(cpus.values())[:8]
    os.sched_setaffinity(0, chosen)
    return {
        "python": v,
        "python_sha256": sha(Path("/usr/bin/python3.12")),
        "strace": s.splitlines()[0],
        "strace_sha256": sha(Path("/usr/bin/strace")),
        "cpus": chosen,
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "score": False,
    }


def early():
    sdk.configure()
    w = sdk.workspace()
    out = w / "trait-results"
    out.mkdir(exist_ok=True)
    tmp = Path(os.environ["RUNNER_TEMP"])
    capacity(out, "initial-capacity", [Path("/tmp"), w, tmp], [CFG["minimum_before_GiB"] * GIB] * 3)
    save(out / "enrollment.json", {"coordinator_commit": os.environ["GITHUB_SHA"], "run_id": int(os.environ["GITHUB_RUN_ID"]), "run_attempt": 1, "protocol": sha(H / "case.json"), "reference": sha(H / "reference.json"), "previous_verified_job": 124964011210, "authors_selected_source": [B,C], "scoring": False})
    save(out / "host.json", env_proof(out))
    scoped.calibrate(out / "scoped-control")
    save(out / "trace-negative-controls.json", scoped.mutations(out / "scoped-control"))


def activate(signed, subject, out, role):
    rm(SDK)
    cp(subject, SDK)
    if role == "rebased":
        here = SDK / "bin/cargo"
        assert sha(here) == CFG["sdk"][role]["cargo"]
        here.unlink()
        shutil.copy2(signed / "bin/cargo", here)
    common = CFG["sdk"]["signed"]["cargo"]
    inv = read(out / ("installed-" + role + "-components.json"))
    assert len(inv) == 142 and sha(SDK / "bin/cargo") == common
    for n, v in inv.items():
        p = SDK / n
        assert p.resolve(strict=True) == p and (
            sdk.core_receipt(p) == v if n != "bin/cargo" else sha(p) == common
        )
    full = subprocess.check_output(["ldd", RUSTC], env=ENV, text=True)
    actual = {}
    for k in ("librustc_driver", "libLLVM"):
        matches = [
            Path(p).resolve(strict=True)
            for n, p in re.findall(r"^\s*(\S+) => (\S+)", full, re.M)
            if n.startswith(k)
        ]
        assert len(matches) == 1 and matches[0].is_relative_to(SDK)
        actual[k] = [str(matches[0]), sha(matches[0])]
    assert actual["librustc_driver"][1] == CFG["sdk"][role]["driver"]
    assert (
        Path(subprocess.check_output([RUSTC, "--print", "sysroot"], env=ENV, text=True).strip()).resolve()
        == SDK
    )
    banners = {
        n: subprocess.check_output([SDK / "bin" / n, "-Vv"], env=ENV, text=True) for n in ("rustc", "cargo")
    }
    assert (
        "commit-hash: " + CFG["sdk"][role]["rust"] in banners["rustc"]
        and "commit-hash: " + sdk.P["signed"]["cargo"] in banners["cargo"]
    )
    save(
        out / ("active-" + role + ".json"),
        {
            "input_inventory": sha(out / ("installed-" + role + "-components.json")),
            "common_cargo": common,
            "loader": actual,
            "banners": banners,
            "only_active_overlay_replacement": "bin/cargo" if role == "rebased" else None,
        },
    )


def code_state(source, core, rev, binary):
    receipt = source.worktree(core, ENV, REG, B, rev, binary)
    # A temporary index proves every tracked worktree blob, without altering the real index.
    fd, path = tempfile.mkstemp(dir=ROOT, prefix="verify-index-")
    os.close(fd)
    os.unlink(path)
    try:
        tmp = ENV | {"GIT_INDEX_FILE": path}
        core.git(tmp, "read-tree", B)
        core.git(tmp, "add", "-u")
        assert core.git(tmp, "write-tree").decode().strip() == CASE[("B" if rev == B else "C") + "_tree"]
    finally:
        Path(path).unlink(missing_ok=True)
    return receipt


def git_history(path):
    expected = CFG["uv_git_history"]
    def git(*args):
        return subprocess.check_output(["git", "-C", path, *args], env=ENV)
    tag = expected["tag_ref"]
    tag_commit = git("rev-parse", "--verify", tag).decode().strip()
    assert git("cat-file", "-t", tag).strip() == b"commit"
    blobs = git("rev-parse", B + ":crates/uv-cli/build.rs", C + ":crates/uv-cli/build.rs").decode().splitlines()
    assert len(blobs) == 2 and blobs[0] == blobs[1]
    chain = git("rev-list", "--parents", "--topo-order", tag + ".." + C)
    lines = chain.decode().splitlines()
    assert len(lines) == 16 and lines[0].split() == [C, B] and lines[-1].split()[1] == tag_commit
    assert all(len(x.split()) == 2 for x in lines)
    info = {"tag_ref": tag, "tag_commit": tag_commit, "build_rs_blob": blobs[0],
            "linear_range_sha256": hashlib.sha256(chain).hexdigest(),
            "git_describe_lines": {rev: git("log", "-1", "--date=short", "--abbrev=9",
                "--format=%H %h %cd %(describe:tags)", rev).decode().strip() for rev in (B, C)}}
    assert info == expected, ("historical uv release tag or build-script Git input changed", info)
    return info


def checkout(src, source, core, delta=None):
    assert not SRC.exists()
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "clone", "--no-checkout", src.resolve().as_uri(), SRC],
        check=True,
        env=ENV,
        stdout=subprocess.DEVNULL,
    )
    core.git(ENV, "checkout", "-q", "--detach", B)
    git_history(SRC)
    assert core.git(ENV, "rev-parse", C + "^").decode().strip() == B
    assert [core.git(ENV, "rev-parse", r + "^{tree}").decode().strip() for r in (B, C)] == [
        CASE["B_tree"],
        CASE["C_tree"],
    ]
    bc = core.git(ENV, "diff", "--binary", "--full-index", B, C)
    assert hashlib.sha256(bc).hexdigest() == CASE["patch"] and (delta is None or bc == delta)
    assert core.git(ENV, "diff", "--name-only", B, C).decode().splitlines() == CASE["files"]
    assert (
        source.fixture_text(core.git(ENV, "show", C + ":" + source.TEST), True) == CASE["snapshot"]
        and source.fixture_text(core.git(ENV, "show", B + ":" + source.TEST), False) is None
    )
    code_state(source, core, B, b"")
    return bc


def registry(cargo):
    lock = SRC / "Cargo.lock"
    assert sha(lock) == CASE["lock"]
    packages = tomllib.loads(lock.read_text())["package"]
    (cache,) = (cargo / "registry/cache").iterdir()
    (index,) = (cargo / "registry/index").iterdir()
    accepted = []
    for q in packages:
        if "source" not in q:
            continue
        assert q["source"] == "registry+https://github.com/rust-lang/crates.io-index"
        n = q["name"]
        v = q["version"]
        k = n.lower()
        rel = (
            "1/" + k
            if len(k) == 1
            else (
                "2/" + k
                if len(k) == 2
                else "3/" + k[0] + "/" + k if len(k) == 3 else k[:2] + "/" + k[2:4] + "/" + k
            )
        )
        data = (index / ".cache" / rel).read_bytes().split(b"\0")
        matches = [j for x in data if x.startswith(b"{") and (j := json.loads(x))["vers"] == v]
        assert (
            len(matches) == 1
            and matches[0]["name"] == n
            and matches[0]["cksum"] == q["checksum"] == sha(cache / (n + "-" + v + ".crate"))
        )
        accepted.append([n, v, q["checksum"]])
    receipt = {
        "archives_and_sparse_index_rows": len(accepted),
        "sha256": hashlib.sha256(json.dumps(sorted(accepted), separators=(",", ":")).encode()).hexdigest(),
    }
    assert receipt == CFG["registry"]
    return receipt


def reset(src, reg, source, core, bc=None):
    for p in (SRC, TARGET, HOME, CARGO_HOME):
        rm(p)
    HOME.mkdir()
    CARGO_HOME.mkdir()
    cp(reg, CARGO_HOME / "registry")
    return checkout(src, source, core, bc)


def apply(source, core, bc):
    assert code_state(source, core, B, b"")
    core.git(ENV, "apply", "--whitespace=nowarn", "-", input=bc)
    return code_state(source, core, C, bc)


def command(path, args):
    path.mkdir()
    so = path / "cargo.stdout"
    se = path / "cargo.stderr"
    with so.open("xb") as a, se.open("xb") as b:
        p = subprocess.run(args, cwd=SRC, env=ENV, stdout=a, stderr=b, timeout=1250)
    assert p.returncode == 0, (args, p.returncode, se.read_bytes()[-1200:])
    return so.read_bytes(), se.read_bytes()


def packlogs(path):
    for n in ("cargo.stdout", "cargo.stderr"):
        native.gzip_file(path / n)


def product(path, shape, o):
    ws = shape[1]
    items = {}
    raw = path / "workspace-rmeta.zip"
    with ZipFile(raw, "x", ZIP_DEFLATED, compresslevel=2) as z:
        for rel in sorted(ws):
            f = TARGET / rel
            assert f.resolve(strict=True) == f and f.is_relative_to(TARGET)
            assert 0 < f.stat().st_size < 40 << 20
            items[rel] = sdk.core_receipt(f)
            z.write(f, rel)
    save(path / "workspace-products.json", items)
    (rel,) = [k for k, i in ws.items() if i["name"] == "uv"]
    f = TARGET / rel
    shutil.copyfile(f, path / f.name)
    b = subprocess.check_output(
        [RUSTC, "-Zls=root", f], cwd=SRC, env=ENV | {"RUSTC_BOOTSTRAP": "1"}, timeout=90
    )
    (path / "uv-root.txt").write_bytes(b)
    r = o.s.decode(b, "uv")
    side = read(f.parent.parent / "fingerprint/lib-uv.public-api-hash")
    assert side["value"] == r["public_hash"]
    save(
        path / "uv-product.json",
        {
            "file": f.name,
            "ordinary_path": str(f),
            "raw_sha256": sha(f),
            "bytes": f.stat().st_size,
            "public": r["public_hash"],
            "private": r["private_hash"],
            "stable": r["stable_crate_id"],
            "full_root_dump_sha": sha(path / "uv-root.txt"),
            "dependencies": len(r["dependencies"]),
        },
    )


def complete_inputs(rows):
    def canonical(v):
        return json.dumps(v, sort_keys=True, separators=(",", ":")).encode()
    facts = {}
    for label, reason in (("compiler_artifact", "compiler-artifact"), ("build_script", "build-script-executed")):
        selected = sorted((r for r in rows if r["reason"] == reason), key=canonical)
        facts[label + "_count"] = len(selected)
        facts[label + "_sha256"] = hashlib.sha256(canonical(selected)).hexdigest()
    return facts


def journal(path, raw):
    rows, owners = native.events(raw)
    with gzip.open(path / "edited-cargo.jsonl.gz", "xb", compresslevel=2) as z:
        for r in rows:
            z.write((json.dumps(r, separators=(",", ":")) + "\n").encode())
    save(path / "build-output-owners.json", owners)
    save(path / "complete-inputs.json", complete_inputs(rows))
    return [r for r in rows if r["reason"] == "compiler-artifact"]


def role(role, signed, sub, src, reg, srcmod, core, o, ref, out):
    here = out / role
    here.mkdir()
    activate(signed, sub, out, role)
    delta = reset(src, reg, srcmod, core)
    assert (
        not TARGET.exists()
        and not list(HOME.iterdir())
        and {p.name for p in CARGO_HOME.iterdir()} == {"registry"}
    )
    capture = lambda: code_state(srcmod, core, C, delta)
    warm = here / "B-cold"
    stdout, stderr = command(warm, PLAIN)
    assert not stdout and len(native.package_lines(stderr)) > 400
    packlogs(warm)
    # Keep the native compiled B; both its unchanged reports describe the natural rustc/link background.
    bshape = here / "B-unchanged-typed"
    so, se = command(bshape, [*PLAIN, "--timings", "--message-format=json-render-diagnostics"])
    rows = journal(bshape, so)
    shape = o.s.inputs(rows)
    criteria = {
        "all_input_fields": read(bshape / "complete-inputs.json") == CFG["complete_cargo_inputs"],
        "unit_target_feature_roster": hashlib.sha256(o.s.canon(shape[0])).hexdigest() == ref["shape"],
        "recurring_artifacts": sorted(native.identity(r) for r in rows if not r["fresh"]) == sorted(CFG["background_keys"]),
        "typed_progress": native.package_lines(se) == ref["progress"],
    }
    packlogs(bshape)
    b2 = here / "B-unchanged-ordinary"
    so, se = command(b2, PLAIN)
    criteria["ordinary_progress"] = not so and native.package_lines(se) == ref["progress"]
    refused_parent = not all(criteria.values())
    if refused_parent:
        save(here / "parent-input-refusal.json", {"criteria": criteria, "score": False, "eligible": False})
    packlogs(b2)
    assert code_state(srcmod, core, B, b"")
    frozen = ROOT / "frozen-B"
    frozen.mkdir()
    preserved = [SRC, TARGET, HOME, CARGO_HOME]
    size = sum(used(p) for p in preserved)
    capacity(here, "cold-B-high-water", [ROOT], [size + 6 * GIB])
    save(
        here / "independently-built-B.json",
        {
            "initial_target": "absent",
            "commands": [PLAIN, [*PLAIN, "--timings", "--message-format=json-render-diagnostics"], PLAIN],
            "source": code_state(srcmod, core, B, b""),
            "input_rows": len(rows),
            "allocated_bytes_for_source_target_and_homes": size,
            "score": False,
        },
    )
    for p in preserved:
        p.rename(frozen / p.name)

    def restore():
        for p in preserved:
            rm(p)
            cp(frozen / p.name, p)
        assert code_state(srcmod, core, B, b"")
        return apply(srcmod, core, delta)

    if refused_parent:
        # Preserve the actual C observations from this ineligible B before stopping.
        # Each visit starts at the same independently-built B. Neither can clear its veto.
        for label, args in (("ordinary", PLAIN), ("diagnostic", DIAG)):
            dest = here / ("quarantined-C-" + label)
            try:
                state = restore()
                so, se = command(dest, args)
                obs = {"argv": args, "progress": native.package_lines(se), "eligible": False, "score": False}
                if label == "diagnostic":
                    journal(dest, so)
                    obs["actual_rustc_argv"] = native.commands(se.decode(), RUSTC)
                assert capture() == state
                save(dest / "observation.json", obs)
                packlogs(dest)
            except (AssertionError, ValueError, OSError, subprocess.SubprocessError):
                save(here / ("quarantined-C-" + label + "-error.json"), {"error": traceback.format_exc(), "score": False})
        raise ValueError(("ineligible independent B; C evidence is diagnostic only", criteria))

    def plain(path, starting, cold=False):
        so, se = command(path, PLAIN)
        assert not so
        progress = native.package_lines(se)
        assert (len(progress) > 400 and "uv" in progress) if cold else progress == ref["progress"]
        save(path / "ordinary.json", {"argv": PLAIN, "exit": 0, "progress": progress, "score": False})
        packlogs(path)
        product(path, shape, o)
        o.p.capture_plain(o.arm, path, shape, ENV)
        assert capture() == starting
        save(path / "source.json", starting)

    ordinary = here / "C-from-independent-B-ordinary"
    plain(ordinary, restore())
    p = here / "C-from-independent-B-diagnostic"
    state = restore()
    so, se = command(p, DIAG)
    rows = journal(p, so)
    if read(p / "complete-inputs.json") != CFG["complete_cargo_inputs"]:
        save(here / "C-input-refusal.json", {"actual": read(p / "complete-inputs.json"), "eligible": False, "score": False})
    assert o.s.inputs(rows) == shape
    calls = native.commands(se.decode(), RUSTC)
    save(p / "all-rustc-argv.json", calls)
    dirty = [
        {
            "name": r["target"]["name"],
            "kind": r["target"]["kind"],
            "package": r["package_id"],
            "features": r["features"],
            "filenames": r["filenames"],
        }
        for r in rows
        if not r["fresh"]
    ]
    save(
        p / "edited-background-products.json",
        native.digests(native.expected_products(rows, {"typed": CFG["background_keys"]})),
    )
    o.s.capture(p, "edited")
    product(p, shape, o)
    packlogs(p)
    save(
        p / "diagnostic.json",
        {
            "argv": DIAG,
            "progress": native.package_lines(se),
            "typed_nonfresh": dirty,
            "actual_rustc": len(calls),
            "surfaces_sha256": sha(p / "edited-rmeta-surface.zip"),
            "score": False,
        },
    )
    assert capture() == state
    save(p / "source.json", state)
    traced = here / "C-scoped-exec"
    state = restore()
    try:
        scoped.execute(traced, PLAIN, ENV, SRC)
        scoped.replay(traced)
        assert (traced / "stdout").stat().st_size == 0 and native.package_lines(
            (traced / "stderr").read_bytes()
        ) == ref["progress"]
        product(traced, shape, o)
        assert (
            read(traced / "workspace-products.json") == read(ordinary / "workspace-products.json")
            and capture() == state
        )
        save(traced / "source.json", state)
    except (AssertionError, ValueError, OSError, subprocess.SubprocessError) as e:
        save(
            here / "scoped-trace-refusal.json",
            {"failed": str(e), "other_native_controls_continue": True, "score": False},
        )
    rm(frozen)
    assert reset(src, reg, srcmod, core, delta) == delta and not TARGET.exists()
    plain(here / "C-independent-cold", apply(srcmod, core, delta), True)
    assert reset(src, reg, srcmod, core, delta) == delta
    witness = ROOT / "witness-target"
    assert not witness.exists()
    o.fx.run(core, o.arm.a, here / "witness-B", ENV, REG, "B", witness)
    code_state(srcmod, core, B, b"")
    apply(srcmod, core, delta)
    o.fx.run(core, o.arm.a, here / "witness-C", ENV, REG, "C", witness)
    capture()
    partial = o.p.compare(
        o.p.plain(o.arm, ordinary, shape), o.p.plain(o.arm, here / "C-independent-cold", shape)
    )
    save(here / "warm-cold-differences.json", partial)
    assert not (here / "C-input-refusal.json").exists(), "actual C Cargo input fields changed; independent checks retained"
    result = o.audit(here, ref, CASE)
    save(here / "native-audit.json", result)
    actor = CFG["sdk"][role]
    assert (
        sha(RUSTC) == actor["rustc"]
        and sha(SDK / "bin/cargo") == CFG["sdk"]["signed"]["cargo"]
        and sha(SDK / "lib/librustc_driver-b03bf00bec23bb9a.so") == actor["driver"]
    )
    assert not (
        here / "scoped-trace-refusal.json"
    ).exists(), "scoped exec gate failed; raw native root and fixture evidence retained"
    return result


def verify_archive(p):
    inv = read(p / "workspace-products.json")
    assert len(inv) == 70
    with ZipFile(p / "workspace-rmeta.zip") as z:
        assert len(z.infolist()) == len(inv) and set(z.namelist()) == set(inv)
        for f in z.infolist():
            n, d = inv[f.filename]
            assert 0 < n < 40 << 20 and f.file_size == n and not f.is_dir()
            with z.open(f) as v:
                assert hashlib.file_digest(v, "sha256").hexdigest() == d


def audit(out, o, ref):
    assert read(out / "host.json")["score"] is False and len(read(out / "host.json")["cpus"]) == 8
    assert read(out / "registry.json") == CFG["registry"]
    assert read(out / "source-git-history.json") == CFG["uv_git_history"] == read(out / "compiler-checkout-git-history.json")
    scoped.replay(out / "scoped-control")
    assert read(out / "trace-negative-controls.json") == scoped.mutations(out / "scoped-control")
    answers = {}
    for role in CFG["role_order"]:
        directory = out / role
        assert not (directory / "parent-input-refusal.json").exists() and not (directory / "C-input-refusal.json").exists()
        for visit in ("B-unchanged-typed", "C-from-independent-B-diagnostic"):
            pv = directory / visit
            with gzip.open(pv / "cargo.stdout.gz") as f:
                parsed, owners = native.events(f.read())
            with gzip.open(pv / "edited-cargo.jsonl.gz") as f:
                assert parsed == [json.loads(line) for line in f]
            assert owners == read(pv / "build-output-owners.json")
            assert complete_inputs(parsed) == read(pv / "complete-inputs.json") == CFG["complete_cargo_inputs"]
        assert sha(out / f"installed-{role}-components.json") == CFG["sdk"][role]["inventory_sha256"]
        receipt = read(out / f"active-{role}.json")
        assert (
            receipt["common_cargo"] == CFG["sdk"]["signed"]["cargo"]
            and receipt["loader"]["librustc_driver"][1] == CFG["sdk"][role]["driver"]
        )
        assert receipt["input_inventory"] == CFG["sdk"][role]["inventory_sha256"]
        real = read(directory / "independently-built-B.json")
        assert (
            real["initial_target"] == "absent"
            and real["source"]["working_revision"] == B
            and real["source"]["index_tree"] == CASE["B_tree"]
            and real["commands"] == [PLAIN, [*PLAIN, "--timings", "--message-format=json-render-diagnostics"], PLAIN]
            and not real["score"]
        )
        p = directory / "C-scoped-exec"
        assert not (directory / "scoped-trace-refusal.json").exists()
        assert read(p / "parsed.json")["command"] == PLAIN
        scoped.replay(p)
        ordinary = directory / "C-from-independent-B-ordinary"
        assert read(ordinary / "workspace-products.json") == read(p / "workspace-products.json") and read(
            p / "source.json"
        ) == read(ordinary / "source.json")
        for visit in (
            ordinary,
            p,
            directory / "C-from-independent-B-diagnostic",
            directory / "C-independent-cold",
        ):
            verify_archive(visit)
        for rp in [ordinary, directory / "C-independent-cold"]:
            rec = read(rp / "ordinary.json")
            assert rec["argv"] == PLAIN and rec["exit"] == 0 and rec["score"] is False
        ans = o.audit(directory, ref, CASE)
        assert ans == read(directory / "native-audit.json")
        answers[role] = ans
    assert answers["signed"]["real_separate_fixtures"] == answers["rebased"]["real_separate_fixtures"]
    return {
        "case": sha(H / "case.json"),
        "readers": sha(H / "readers.zip"),
        "complete_ordinary_trace_replays": 2,
        "actual_compilers_per_replay": 3,
        "complete_shape": 641,
        "native_checks_rederived": True,
        "raw_wire_identity_on_independent_cold": {k: v["raw_byte_identity"] for k, v in answers.items()},
        "all_compiler_surfaces_fixtures_and_full_argv_match": True,
        "eligible_for_performance_scoring": False,
        "score": False,
    }


def run():
    sdk.configure()
    w = sdk.workspace()
    tmp = Path(os.environ["RUNNER_TEMP"]).resolve()
    out = w / "trait-results"
    assert read(out / "host.json") == env_proof(out)
    scoped.replay(out / "scoped-control")
    assert not ROOT.exists() and ROOT.parent.resolve() == Path("/tmp")
    ROOT.mkdir(mode=0o700)
    readers = tmp / "uv-20991-pure-readers"
    _, o, source = initialize(readers)
    core = o.arm.core
    ref = read(H / "reference.json")
    installed = sdk.install(out, w / "sdk-media", tmp / "uv-20991-installed")
    src = w / "uv-source"
    assert subprocess.check_output(["git", "-C", src, "rev-parse", "HEAD"], text=True).strip() == C
    HOME.mkdir()
    CARGO_HOME.mkdir()
    activate(installed["signed"], installed["signed"], out, "signed")
    delta = checkout(src, source, core)
    save(out / "compiler-checkout-git-history.json", git_history(SRC))
    (out / "B-C.patch").write_bytes(delta)
    fetch = ["/tmp/uv-workflow-search/sdk/bin/cargo", "fetch", "--locked"]
    before = code_state(source, core, B, b"")
    with (out / "fetch.stdout").open("xb") as so, (out / "fetch.stderr").open("xb") as se:
        subprocess.run(
            fetch,
            cwd=SRC,
            env=ENV | {"CARGO_NET_OFFLINE": "false"},
            stdout=so,
            stderr=se,
            check=True,
            timeout=1000,
        )
    assert before == code_state(source, core, B, b"")
    save(out / "registry.json", registry(CARGO_HOME))
    # Never share mutable actor state. The sealed registry is copied anew for each cold build.
    bank = tmp / "uv-20991-verified-registry"
    assert not bank.exists()
    cp(CARGO_HOME / "registry", bank)
    for p in [SRC, TARGET, HOME, CARGO_HOME, SDK]:
        rm(p)
    capacity(out, "after-asset-and-registry-capacity", [ROOT, tmp, w], [CFG["minimum_ready_GiB"] * GIB] * 3)
    failures = {}
    for name in CFG["role_order"]:
        try:
            submitted = role(
                name, installed["signed"], installed[name], src, bank, source, core, o, ref, out
            )
            print(
                name,
                "completed actual roots, scoped argv and both upstream witnesses; independent raw differences",
                len(submitted["cold_raw_drift"]),
                flush=True,
            )
        except Exception:  # Always retain the other independent actor after a per-actor failure.
            failures[name] = traceback.format_exc()
            save(out / (name + "-refusal.json"), {"error": failures[name], "score": False})
        finally:
            for p in (
                SRC,
                TARGET,
                HOME,
                CARGO_HOME,
                SDK,
                ROOT / "frozen-B",
                ROOT / "witness-target",
                ROOT / "fixture-runtime",
            ):
                rm(p)
    if failures:
        raise ValueError(("unscored role checks failed; original raw retained", list(failures)))
    result = audit(out, o, ref)
    save(out / "unscored-opening.json", result)
    assert all(
        result["raw_wire_identity_on_independent_cold"].values()
    ), "unexplained independent raw rmeta drift: unscored semantic evidence retained, opening refused"


def verify_output(path):
    with tempfile.TemporaryDirectory() as td:
        _, o, _ = initialize(Path(td) / "kit")
        got = audit(path, o, read(H / "reference.json"))
    assert got == read(path / "unscored-opening.json")
    print(json.dumps(got, indent=2))
    assert all(got["raw_wire_identity_on_independent_cold"].values()), "independent cold output has unqualified wire drift"


if __name__ == "__main__":
    assert __debug__
    if len(sys.argv) == 3 and sys.argv[1] == "history":
        print(json.dumps(git_history(Path(sys.argv[2])), sort_keys=True, indent=2))
    elif sys.argv[1:] == ["early"]:
        early()
    elif sys.argv[1:] == ["intake"]:
        w = sdk.workspace()
        sdk.acquire(w / "trait-results", w / "sdk-media")
    elif sys.argv[1:] == ["run"]:
        run()
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify_output(Path(sys.argv[2]).resolve())
    else:
        raise SystemExit("opening.py early | intake | run | verify RAW-DIRECTORY")
