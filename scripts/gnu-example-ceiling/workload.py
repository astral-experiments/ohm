"""Drive the ordinary Ruff examples through both observation orders and their clean controls."""

import gzip, hashlib, json, os, re, shutil, subprocess, sys, tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit, pmu, topology
from kit import H, sha, save, ROLES

REG = json.loads((HERE / "registration.json").read_bytes())
CLI = REG["cli"]
NAMES = set(ROLES["examples"])
RUSTDOC = "rustdoc"
GIT_TREE = "62d3f106c5e41f6022847f26ff8c7dc00139f7b1"
LOCK = "c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf"


def git(src, *args):
    return subprocess.check_output(["git", "-C", src, *args])


def sources(src, state):
    expect = ROLES["source_inputs"][state]
    assert {k: sha(src / k) for k in expect} == expect
    assert set(git(src, "diff", "--name-only").decode().splitlines()) == (
        set(expect) if state == "old" else set()
    ) and not git(src, "ls-files", "--others", "--exclude-standard")
    assert (
        git(src, "rev-parse", "HEAD").decode().strip() == REG["ruff"]
        and sha(src / "Cargo.lock") == LOCK
    )
    return expect


def source(root, local=None):
    src = root / "source"
    src.mkdir()
    git(src, "init", "-q")
    repo = str(local) if local else "https://github.com/astral-sh/ruff.git"
    for depth, rev in [(1, REG["ruff"]), (2, REG["edit"])]:
        git(src, "fetch", "--depth=" + str(depth), "--no-tags", repo, rev)
    git(src, "switch", "-q", "--detach", REG["ruff"])
    assert git(src, "rev-parse", "HEAD^{tree}").decode().strip() == GIT_TREE
    patch = HERE / "renderer.patch"
    assert (
        sha(patch)
        == REG["patch"]
        == H(
            git(
                src,
                "diff",
                "--binary",
                "--abbrev=10",
                REG["edit"] + "^",
                REG["edit"],
                "--",
                *sorted(ROLES["source_inputs"]["corrected"])
            )
        )
    )
    sources(src, "corrected")
    return src


def env_for(root):
    slot = root / "slot"
    slot.mkdir(exist_ok=True)
    home = slot / "home"
    home.mkdir(exist_ok=True)
    tmp = slot / "tmp"
    tmp.mkdir(exist_ok=True)
    proxies = Path(shutil.which("rustup")).absolute().parent
    tool = root / "rustup/toolchains"
    tool.mkdir(parents=True, exist_ok=True)
    alias = tool / "ohm"
    if not alias.is_symlink():
        alias.symlink_to(root / "sdk", target_is_directory=True)
    assert alias.samefile(root / "sdk")
    return {
        "HOME": str(home),
        "USER": os.environ.get("USER", "runner"),
        "PATH": os.pathsep.join([str(proxies), "/usr/local/bin", "/usr/bin", "/bin"]),
        "CARGO_TARGET_DIR": str(slot / "target"),
        "CARGO_BUILD_BUILD_DIR": str(slot / "shared"),
        "CARGO_HOME": str(slot / "cargo-home"),
        "RUSTUP_HOME": str(tool.parent),
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_NET_OFFLINE": "true",
        "CARGO_TERM_COLOR": "never",
        "CARGO_CACHE_AUTO_CLEAN_FREQUENCY": "never",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": str(tmp),
    }


def raw(folder, cmd, src, env, want=0):
    folder.mkdir(parents=True)
    p = pmu.spawn(cmd, src, env)
    pmu.gz(folder / "stdout.gz", p.stdout)
    pmu.gz(folder / "stderr.gz", p.stderr)
    save(folder / "invocation.json", {"argv": list(map(str, cmd)), "status": p.returncode})
    assert p.returncode == want, (folder, p.returncode, p.stderr[-500:])
    return p


def prepare_registry(root, src, env, out):
    seed = root / "fetched"
    seed.mkdir()
    en = dict(env, CARGO_HOME=str(seed))
    en.pop("CARGO_NET_OFFLINE")
    raw(out / "registry", ["cargo", "+ohm", "fetch", "--locked"], src, en)
    locked = {
        r["name"] + "-" + r["version"] + ".crate": r["checksum"]
        for r in tomllib.loads((src / "Cargo.lock").read_text())["package"]
        if "checksum" in r
    }
    actual = {p.name: sha(p) for p in (seed / "registry").glob("cache/*/*.crate")}
    assert len(locked) == 498 and actual == locked
    save(out / "registry-locks.json", actual)
    return seed


def registry(env, seed):
    home = Path(env["CARGO_HOME"])
    home.mkdir(exist_ok=False)
    # Cargo's two installations have independent writable state. The already
    # authenticated fetched registry is their common, immutable input corpus.
    for sub in ("registry", "git"):
        donor = seed / sub
        if donor.exists():
            dest = home / sub
            if sub == "registry":
                dest.mkdir()
                for item in ("cache", "index", "src"):
                    if (donor / item).exists():
                        (dest / item).symlink_to(donor / item, target_is_directory=True)
            else:
                dest.symlink_to(donor, target_is_directory=True)


def plain_artifacts(data):
    msgs = [json.loads(line) for line in data.splitlines()]
    assert msgs[-1] == {"reason": "build-finished", "success": True}
    assert not any(
        m["reason"] == "compiler-message" and m["message"]["level"] == "error" for m in msgs
    )
    arts = [m for m in msgs if m["reason"] == "compiler-artifact"]
    assert len(arts) == 55
    outputs = {
        m["target"]["name"]: m["executable"]
        for m in arts
        if m.get("executable") and m["target"]["kind"] == ["example"]
    }
    assert set(outputs) == NAMES
    typed = sorted([m["target"]["name"], m["target"]["kind"], m["fresh"]] for m in arts)
    return {"units": typed, "outputs": outputs}


def examples(dest, src, en, paths):
    dest.mkdir()
    states = {}
    for k, name in sorted(paths.items()):
        p = Path(name)
        v = pmu.spawn([p], src, en, 35)
        assert v.returncode == 0
        b = p.read_bytes()
        assert b[:7] == b"\x7fELF\x02\x01\x01"
        states[k] = [H(b), len(b), H(v.stdout), H(v.stderr)]
        pmu.gz(dest / (k + "-out.gz"), v.stdout)
        pmu.gz(dest / (k + "-err.gz"), v.stderr)
    save(dest / "12-images.json", states)
    return states


def oracle(dest, src, en, state):
    test = [
        "cargo",
        "+ohm",
        "test",
        "-p",
        "ruff_annotate_snippets",
        "--test",
        "ruff",
        "--no-run",
        "--locked",
        "--offline",
        "-j4",
        "--message-format=json",
    ]
    slot = Path(en["CARGO_TARGET_DIR"]).parent
    private = dict(
        en,
        CARGO_TARGET_DIR=str(slot / "oracle-target"),
        CARGO_BUILD_BUILD_DIR=str(slot / "oracle-shared"),
    )
    assert not any(Path(private[k]).exists() for k in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"))
    r = raw(dest / "no-run", test, src, private)
    msgs = [json.loads(x) for x in r.stdout.splitlines()]
    assert msgs[-1] == {"reason": "build-finished", "success": True}
    (exe,) = [
        m["executable"]
        for m in msgs
        if m["reason"] == "compiler-artifact"
        and m["target"]["kind"] == ["test"]
        and m.get("executable")
    ]
    x = raw(
        dest / "case",
        [exe, "--exact", "multiple_insertions", "--nocapture", "--test-threads=1"],
        src,
        private,
    )
    assert b"running 1 test" in x.stdout and b"1 passed; 0 failed" in x.stdout
    assert (b"panicked" in x.stderr) == (state == "old") and (
        state != "old" or b"index out of bounds" in x.stderr
    ), x.stderr[-500:]
    return {"source": state, "program": sha(exe), "stdout": H(x.stdout), "stderr": H(x.stderr)}


def park(root, where, names, require=True):
    where.mkdir()
    slot = root / "slot"
    for n in names:
        src = slot / n
        if require:
            assert src.exists(), src
        if src.exists():
            src.rename(where / n)
        assert not src.exists()


def markers(slot):
    tag = "/dev/null/ohm-recheck-dependent-links"
    assert not os.path.lexists(tag)
    found = []
    own = []
    for p in sorted(list((slot / "target").rglob("*.d")) + list((slot / "shared").rglob("*.d"))):
        b = p.read_bytes()
        body = b.decode(errors="surrogateescape").splitlines()
        marks = [k[:-1] for k in body if k.endswith(":") and k.startswith("/dev/null/ohm-")]
        if marks:
            found.append([p.name, marks, H(b)])
        if p.stem in NAMES and p.parent.name == "out":
            own.append(p.stem)
            assert not marks
    assert set(own) == NAMES and any(n.startswith("zmij-") and tag in m for n, m, _ in found), (
        own,
        found,
    )
    return {
        "missing": tag,
        "emitted_real_flags": sorted(found),
        "examples_own_none": sorted(set(own)),
    }


def paths(root, out, env):
    sdk = root / "sdk"
    c = Path(shutil.which("cc", path=env["PATH"]))
    gcc = subprocess.check_output([c, "-print-prog-name=collect2"], env=env, text=True).strip()
    paths = {
        "rustc": sdk / "bin/rustc",
        "cc": c,
        "collect2": Path(gcc),
        "wild": sdk / kit.WILD_PATH,
    }
    subjects = {k: topology.location(p) for k, p in paths.items()}
    save(out / "selected.json", subjects)
    assert paths["collect2"].is_file()
    versions = {}
    for n, flag, expected in [
        ("cargo", "-Vv", kit.TOOLCARGO),
        ("rustc", "-vV", kit.RUST),
        ("rustdoc", "-vV", kit.RUST),
    ]:
        b = subprocess.check_output([n, "+ohm", flag], env=env)
        assert expected.encode() in b
        versions[n] = b.decode()
        active = Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "ohm", n], env=env, text=True
            ).strip()
        )
        assert active.samefile(sdk / "bin" / n)
    assert Path(
        subprocess.check_output(["rustc", "+ohm", "--print", "sysroot"], env=env, text=True).strip()
    ).samefile(sdk)
    save(
        out / "identities.json",
        {
            "selectors": {k: [str(v), sha(v)] for k, v in paths.items()},
            "versions": versions,
            "cargo": kit.stable(sdk / "bin/cargo"),
            "driver": kit.stable(next((sdk / "lib").glob("librustc_driver-*.so"))),
            "environment": env,
        },
    )
    return paths, subjects


def run_arm(root, dest, binpath, mode, src, en):
    dest.mkdir()
    selected, sel = paths(root, dest, en)
    active = root / "slot"
    assert not (active / "target").exists() and not (active / "shared").exists()
    git(src, "apply", "--reverse", str(HERE / "renderer.patch"))
    sources(src, "old")
    old = plain_artifacts(raw(dest / "old", CLI, src, en).stdout)
    orig = examples(dest / "old-programs", src, en, old["outputs"])
    a = oracle(dest / "old-case", src, en, "old")
    park(root, root / (dest.name + "-retired-old-oracle"), ("oracle-target", "oracle-shared"))
    git(src, "apply", str(HERE / "renderer.patch"))
    sources(src, "corrected")
    # Leave both role targets and the pair's source untouched across these calls.
    data = [
        pmu.record(dest / phase, binpath, mode, selected, CLI, src, en)
        for phase in ("edit", "repeat")
    ]
    p, q = map(plain_artifacts, data)
    assert p["outputs"] == q["outputs"]
    rendered = examples(dest / "returned", src, en, q["outputs"])
    assert all(orig[k][0] != v[0] for k, v in rendered.items())
    marker = markers(active)
    results = {}
    for phase, art in [("edit", p), ("repeat", q)]:
        dirty = [v[0] for v in art["units"] if not v[2]]
        assert set(dirty) == NAMES | ({"annotate_snippets"} if phase == "edit" else set()), (
            phase,
            dirty,
        )
        native = topology.read(
            dest / phase / "trace", sel, mode, names=NAMES, registry_target=active / "target"
        )
        if mode != "plain":
            assert len(native["library"]) == (1 if phase == "edit" else 0)
        results[phase] = {"typed": art["units"], "native": native}
    # A no-PMU topology flank checks the execution roster without instrumenting
    # the ordinary-only pair. Its outputs anchor the observed depfiles and issued programs.
    f = plain_artifacts(pmu.record(dest / "settled", binpath, "topology", selected, CLI, src, en))
    settled = topology.read(
        dest / "settled/trace", sel, "topology", names=NAMES, registry_target=active / "target"
    )
    assert not settled["library"] and f["units"] == q["units"]
    assert rendered == examples(dest / "settled-programs", src, en, f["outputs"])
    assert marker["examples_own_none"] == markers(active)["examples_own_none"]
    # Keep every original target at a sibling location. Both reference roots
    # are verified absent; Cargo gets the identical absolute target/shared paths.
    park(root, root / (dest.name + "-retired-history"), ("target", "shared"))
    correct = plain_artifacts(raw(dest / "empty", CLI, src, en).stdout)
    ref = examples(dest / "empty-programs", src, en, correct["outputs"])
    assert rendered == ref
    z = oracle(dest / "fixed-case", src, en, "corrected")
    sources(src, "corrected")
    park(
        root,
        root / (dest.name + "-retired-reference"),
        ("target", "shared", "oracle-target", "oracle-shared"),
    )
    output = {
        "mode": mode,
        "edit": results["edit"],
        "repeat": results["repeat"],
        "programs": rendered,
        "old_programs": orig,
        "settled": settled,
        "marker": marker,
        "cases": [a, z],
        "source": ROLES["source_inputs"],
        "original_executables_compared": 12,
    }
    save(dest / "accepted.json", output)
    return output
