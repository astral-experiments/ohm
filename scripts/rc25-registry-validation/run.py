"""Exercise the exact merged Cargo using the released Linux compiler and two earlier fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import tarfile
import tomllib
import traceback
import urllib.request

here = Path(__file__).resolve().parent
prior = here.parent / "rc24-insta-input-proof"
reg = json.loads((here / "registration.json").read_bytes())


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n")


def out(args, cwd, env=None):
    return sp.check_output(args, cwd=cwd, env=env, text=True).strip()


def source_at(path):
    pack = here / "cargo-source.pack"
    assert sha(pack) == reg["source"]["pack"] and pack.stat().st_size == reg["source"]["bytes"]
    sp.run(["git", "init", "-q", path], check=True)
    (path / ".git/shallow").write_text(reg["head"] + "\n")
    with pack.open("rb") as inp:
        sp.run(["git", "index-pack", "--stdin", "--strict"], cwd=path, stdin=inp, check=True)
    sp.run(["git", "checkout", "--quiet", "--detach", reg["head"]], cwd=path, check=True)
    git = lambda *args: out(["git", *args], path)
    assert git("rev-parse", "HEAD") == reg["head"] and git("rev-parse", "HEAD^{tree}") == reg["tree"]
    assert [x[7:] for x in git("cat-file", "-p", "HEAD").splitlines() if x.startswith("parent ")] == reg["parents"]
    ids = sorted({l.split(" ", 1)[0] for l in git("rev-list", "--objects", "HEAD").splitlines()})
    assert len(ids) == reg["source"]["objects"]
    assert hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest() == reg["source"]["roster"]
    assert not git("status", "--porcelain") and sha(path / "Cargo.lock") == reg["rust_package"]
    sp.run(["git", "fsck", "--full", "--strict", "--no-reflogs", "HEAD"], cwd=path, check=True)


def signed_sdk(root, proof):
    record = json.loads((prior / "release-compiler.json").read_bytes())
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GH_TOKEN": os.environ.pop("OHM_SDK_READ_TOKEN")}
    endpoint = f"repos/astral-experiments/ohm/releases/assets/{reg['asset']}"
    meta = json.loads(sp.check_output(["gh", "api", endpoint], env=env))
    assert meta["digest"] == "sha256:" + reg["release"] and meta["size"] == 360088078
    archive = root / "signed.tar.gz"
    with archive.open("xb") as f:
        sp.run(["gh", "api", "-H", "Accept: application/octet-stream", endpoint], stdout=f, env=env, check=True)
    assert sha(archive) == record["tar_sha256"] == reg["release"] and archive.stat().st_size == meta["size"]
    entries = {v["source"]: (n, v) for n, v in record["members"].items()}
    sdk = root / "sdk"
    found = {}
    with tarfile.open(archive, "r|gz") as t:
        for m in t:
            if m.name not in entries:
                continue
            name, expected = entries[m.name]
            assert m.isfile() and m.size == expected["bytes"] and name not in found
            assert not Path(name).is_absolute() and ".." not in Path(name).parts
            p = sdk / name
            p.parent.mkdir(parents=True, exist_ok=True)
            with t.extractfile(m) as inp, p.open("xb") as dest:
                shutil.copyfileobj(inp, dest)
            p.chmod(0o755 if m.mode & 0o111 else 0o644)
            found[name] = sha(p)
            assert found[name] == expected["sha256"]
    assert len(found) == 79 and found.keys() == record["members"].keys()
    dump(proof / "sdk.json", {"asset": meta["id"], "tar": reg["release"], "physical": found})
    return sdk


def locked_inputs(source, env):
    sp.run(["cargo", "+ohm", "-Zohm-defaults=no", "fetch", "--locked"], cwd=source, env=env, check=True)
    required = {p["name"] + "-" + p["version"] + ".crate": p for p in tomllib.loads((source / "Cargo.lock").read_text())["package"] if "source" in p}
    cache, = (Path(env["CARGO_HOME"]) / "registry/cache").iterdir()
    for name, pkg in required.items():
        assert pkg["source"] == "registry+https://github.com/rust-lang/crates.io-index"
        f = cache / name
        if not f.exists():
            with urllib.request.urlopen("https://static.crates.io/crates/" + pkg["name"] + "/" + name, timeout=60) as inp, f.open("xb") as dest:
                shutil.copyfileobj(inp, dest)
        assert sha(f) == pkg["checksum"], name
    return {n: p["checksum"] for n, p in required.items()}


def deleted(case, proof):
    result = json.loads((case / "proof/complete.json").read_bytes())
    original = result["rows"][-1]
    assert original["label"] == "empty-repair" and original["display"] == "snapshots"
    source, = (case / "cargo-home/registry/src").glob("*/insta-1.48.0/src/settings.rs")
    assert sha(source) == result["source"]
    env = {k: os.environ[k] for k in ("HOME", "USER", "PATH", "LANG", "TMPDIR") if k in os.environ}
    env.update(RUSTUP_HOME=str(case / "rustup"), RUSTUP_TOOLCHAIN="ohm", CARGO_HOME=str(case / "cargo-home"),
               CARGO_TARGET_DIR=str(case / "target"), CARGO_BUILD_BUILD_DIR=str(case / "shared"), CARGO_NET_OFFLINE="true")
    assert sha(case / "active-sdk/bin/cargo") == result["roles"]["candidate"]
    held = case / "held-settings.rs"
    log = proof / "deletion"
    log.mkdir()
    rows = []

    def visit(label, error):
        args = ["cargo", "+ohm", "build", "--locked", "--offline", "-j1", "-vv", "--message-format=json"]
        p = sp.run(args, cwd=case / "project", env=env, capture_output=True)
        (log / (label + ".out")).write_bytes(p.stdout)
        (log / (label + ".err")).write_bytes(p.stderr)
        messages = [json.loads(l) for l in p.stdout.splitlines() if l.startswith(b"{")]
        assert p.returncode == (101 if error else 0) and messages[-1] == {"reason": "build-finished", "success": not error}
        errors = [m["message"] for m in messages if m["reason"] == "compiler-message" and m["message"]["level"] == "error"]
        if error:
            assert not source.exists() and any((m.get("code") or {}).get("code") == "E0583" and "settings" in m["message"]
                and any(s["is_primary"] and s["file_name"].endswith("/insta-1.48.0/src/lib.rs") for s in m["spans"]) for m in errors), errors
        else:
            assert not errors and sha(source) == result["source"]
        elf = case / "target/debug/ohm_insta_chain"
        assert sha(elf) == original["elf"] and out([elf], case / "project") == "snapshots"
        rows.append({"stage": label, "exit": p.returncode, "errors": [m.get("code") for m in errors],
                     "elf": sha(elf), "source_exists": source.exists()})

    source.rename(held)
    try:
        visit("missing", True)
        visit("still-missing", True)
    finally:
        held.rename(source)
    visit("repair", False)
    for name in ("target", "shared"):
        (case / name).rename(case / ("before-empty-" + name))
    visit("independent-empty", False)
    dump(log / "complete.json", rows)


def run():
    root = Path(os.environ["RUNNER_TEMP"]) / "cargo25-registry"
    root.mkdir()
    proof = root / "proof"
    proof.mkdir()
    for name, digest in reg["prior_files"].items():
        assert sha(prior / name) == digest
    src = root / "cargo-src"
    source_at(src)
    sdk = signed_sdk(root, proof)
    alias = root / "rustup/toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sdk)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LANG", "TMPDIR") if k in os.environ}
    env.update(CARGO_HOME=str(root / "compiler-home"), RUSTUP_HOME=str(root / "rustup"), RUSTUP_TOOLCHAIN="ohm",
               CARGO_TARGET_DIR=str(root / "compiler-target"), CARGO_BUILD_BUILD_DIR=str(root / "compiler-build"),
               CARGO_PROFILE_RELEASE_DEBUG="0", CARGO_INCREMENTAL="false")
    rustc = out(["rustc", "+ohm", "-vV"], src, env)
    old_cargo = out(["cargo", "+ohm", "-vV"], src, env)
    assert reg["signed_rust"] in rustc and reg["root"] in old_cargo
    print("Compiling exact Cargo on", rustc.splitlines()[0], flush=True)
    deps = locked_inputs(src, env)
    assert len(deps) == 524
    jobs = os.cpu_count()
    assert jobs and jobs > 0
    argv = ["cargo", "+ohm", "-Zohm-defaults=no", "build", "--release", "--locked", "--offline", "-p", "cargo", "--bin", "cargo", "--features", "all-static,ohm-defaults", f"-j{min(8, jobs)}"]
    sp.run(argv, cwd=src, env=env, check=True)
    assert not out(["git", "status", "--porcelain"], src)
    candidate = root / "compiler-target/release/cargo"
    vv = out([candidate, "-vV"], src, env)
    assert "commit-hash: " + reg["head"] in vv
    digest = sha(candidate)
    (proof / "physical").mkdir()
    shutil.copy2(candidate, proof / "physical/cargo")
    dump(proof / "compiler.json", {"source": reg["head"], "tree": reg["tree"], "cargo": vv, "sha256": digest, "build": argv, "rustc": rustc,
         "parent_cargo": old_cargo, "dependencies": deps, "qa": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"]})
    fixture = prior / "migration/fixture"
    seed = root / "fixture"
    (seed / "src").mkdir(parents=True)
    for filename in ("Cargo.toml", "Cargo.lock"):
        shutil.copyfile(fixture / filename, seed / filename)
    (seed / "src/main.rs").write_text("fn main() {}\n")
    fenv = dict(env, CARGO_HOME=str(root / "fixture-home"))
    sources = locked_inputs(seed, fenv)
    ruff = Path(os.environ["GITHUB_WORKSPACE"]) / "ruff"
    assert out(["git", "rev-parse", "HEAD"], ruff) == reg["ruff"]["new"] and out(["git", "rev-parse", "HEAD^"], ruff) == reg["ruff"]["old"]
    for revision in (reg["ruff"]["old"], reg["ruff"]["new"]):
        packages = tomllib.loads(out(["git", "show", revision + ":Cargo.lock"], ruff))["package"]
        available = {p["name"] + "-" + p["version"] + ".crate": p["checksum"] for p in packages if "source" in p}
        assert len(sources) == 88 and all(available.get(n) == v for n, v in sources.items())
    dump(proof / "fixture-inputs.json", sources)
    ctl = ["--signed", sdk, "--parent", sdk / "bin/cargo", "--candidate", candidate]
    case = root / "insta"
    refusals = {}
    try:
        sp.run(["strace", "-f", "-qq", "-s", "192", "-e", "trace=execve", "-o", proof / "insta.exec",
                sys.executable, "-IB", prior / "migration/run.py", "--work", case, "--sdk", sdk, *ctl[2:],
                "--fixture", fixture, "--registry", Path(fenv["CARGO_HOME"]) / "registry"], check=True)
        deleted(case, proof)
    except Exception:
        refusals["insta"] = traceback.format_exc()
        dump(proof / "refusals.json", refusals)
    finally:
        if (case / "proof").exists():
            (case / "proof").rename(proof / "insta")
    legacy = (prior / "evidence/nonempty-registry-history/replay.py").read_text()
    previous = "32df98560d4ac57c4c959c762095a3afe6a3bbe62b44d8fc6e6bf8071f53a53e"
    assert legacy.count(previous) == 1
    replay = root / "exact-replay.py"
    replay.write_text(legacy.replace(previous, digest))
    for label, control in [("first-v5", "--first-clean"), ("inherited", "--legacy-control")]:
        case = root / label
        try:
            sp.run([sys.executable, "-IB", replay, case, "--published-parent", control, *ctl], check=True)
        except Exception:
            refusals[label] = traceback.format_exc()
            dump(proof / "refusals.json", refusals)
        finally:
            if (case / "evidence").exists():
                (case / "evidence").rename(proof / label)
                for actual, preserved in (("objects/v5consumer/0.1.0/download", "v5consumer.crate"), ("application/Cargo.lock", "application/Cargo.lock"),
                                          ("index/v5/co/v5consumer", "registry/v5/co/v5consumer")):
                    if (case / actual).is_file():
                        dst = proof / label / preserved
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(case / actual, dst)
    assert not refusals, refusals
    dump(proof / "complete.json", {"root": reg["root"], "candidate": reg["head"], "cargo": digest, "rustc": reg["signed_rust"],
         "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "first_clean": True, "inherited": True, "deleted": True})


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check-source":
        source_at(Path(sys.argv[2]))
    else:
        assert len(sys.argv) == 1
        run()
