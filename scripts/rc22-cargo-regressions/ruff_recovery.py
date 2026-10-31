"""Replay a repaired Ruff error through a same-installation-path -22 Cargo upgrade."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_mounts import ROLES, check_sdk, sha

RUFF = "93526150df078af7dd8fc4226cdcc469539d2001"
TREE = "62d3f106c5e41f6022847f26ff8c7dc00139f7b1"
LOCK = "c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf"
HISTORY = "32c5cd5daba51d9c3da691c5b43afa6a7a4bb731"
PATCH = "b583905f8f7bf43ff81aad1e29fae01eeba5b21fea091319041e20349af91008"
EDIT = "crates/ty_project/src/uv/metadata/dependencies.rs"
SOURCE = "crates/ty_project/src/lib.rs"
WARN = b'\n#[deprecated(note = "OHM_QA_PRESERVED_WARNING")]\nconst OHM_QA_OLD_CONST: u8 = 17;\n#[warn(deprecated)]\nconst _: u8 = OHM_QA_OLD_CONST;\n'
BAD = b'\nconst _: u8 = "OHM_RON_CHECK_BAD_TYPE";\n'


def save(path, value):
    with path.open("x") as file:
        json.dump(value, file, sort_keys=True, indent=2)
        file.write("\n")


def archive(path, data):
    with path.open("xb") as file:
        file.write(gzip.compress(data, compresslevel=2, mtime=0))


def retain_metadata(store, path, crate, env):
    """Keep exact compiler inputs and the producing compiler's own metadata listing."""
    data = path.read_bytes()
    assert 0 < len(data) <= 16 * 2**20
    digest = hashlib.sha256(data).hexdigest()
    body = store / (digest + ".rmeta.gz")
    listing = store / (digest + ".ls.gz")
    if body.exists():
        assert gzip.decompress(body.read_bytes()) == data and listing.is_file()
    else:
        kind = "all" if crate == "ron" else "root"
        decoded = read_output(["rustc", "+ohm", "-Zls=" + kind, str(path)], env)
        lines = decoded.splitlines()
        assert lines[0] == b"Crate info:" and lines[1].split(b"-", 1)[0] == b"name " + crate.encode()
        assert b"=External Dependencies=" in lines
        archive(body, data)
        archive(listing, decoded)
    assert len(data) == path.stat().st_size and digest == sha(path)
    return [len(data), digest]


def capture_ron(out, label, artifacts, env):
    store = out / "metadata"
    store.mkdir(exist_ok=True)
    roots = tuple(Path(env[k]).resolve() for k in ("CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"))
    selected = {"ron", "bitflags", "once_cell", "serde", "serde_core", "serde_derive", "typeid", "unicode_ident"}
    records = []
    for row in artifacts:
        name = row["target"]["name"]
        if name not in selected or row["target"]["kind"] not in (["lib"], ["proc-macro"]):
            continue
        outputs = {}
        for fname in row["filenames"]:
            path = Path(fname).resolve(strict=True)
            assert any(path.is_relative_to(root) for root in roots)
            outputs[fname] = (retain_metadata(store, path, name, env) if path.suffix == ".rmeta"
                              else [path.stat().st_size, sha(path)])
        records.append({"crate": name, "package": row["package_id"], "features": row["features"],
                        "fresh": row["fresh"], "profile": row["profile"], "outputs": outputs})
    assert {r["crate"] for r in records} == selected
    save(out / (label + ".metadata.json"), records)


def read_output(command, env=None, cwd=None):
    return subprocess.check_output(command, env=env, cwd=cwd, timeout=1500)


def diagnostic(rows):
    messages = [r for r in rows if r["reason"] == "compiler-message"]
    out = []
    for r in messages:
        m = r["message"]
        spans = [s for s in m["spans"] if s["is_primary"]]
        out.append({"package": r["package_id"], "crate": r["target"]["name"], "level": m["level"],
                    "code": (m.get("code") or {}).get("code"), "message": m["message"],
                    "spans": [(s["file_name"], s["line_start"], [t["text"] for t in s["text"]]) for s in spans]})
    return out


def guard(diags, verdict):
    errors = [r for r in diags if r["level"] == "error"]
    warnings = [r for r in diags if r["level"] == "warning" and r["code"] == "deprecated" and
                "OHM_QA_PRESERVED_WARNING" in r["message"]]
    has_error = verdict in ("invalid", "stale")
    assert len(errors) == int(has_error), (verdict, errors)
    if has_error:
        assert errors[0]["crate"] == "ty_project" and errors[0]["code"] == "E0308"
        assert any(path == SOURCE and any("OHM_RON_CHECK_BAD_TYPE" in line for line in lines) for path, _, lines in errors[0]["spans"])
    assert len(warnings) == int(verdict == "warning"), (verdict, warnings)
    if warnings:
        assert any(path == SOURCE for path, _, _ in warnings[0]["spans"])


def typed_reader(root, out, label, artifacts, env):
    ron, = [r for r in artifacts if r["target"]["name"] == "ron" and r["target"]["kind"] == ["lib"]]
    rmeta, = [Path(f) for f in ron["filenames"] if f.endswith(".rmeta")]
    assert rmeta.stat().st_size > 0
    deps = sorted({str(Path(f).parent) for r in artifacts for f in r["filenames"]})
    place = root / "typed-reader"
    place.mkdir(exist_ok=True)
    source = place / "input.rs"
    result = place / "consumer.rmeta"
    identity = {"ron": [rmeta.stat().st_size, sha(rmeta)]}
    common = ["rustc", "+ohm", "--edition=2021", "--crate-type=lib", "--crate-name", "rc22_ron_consumer",
              "--emit=metadata", "--error-format=json", "--extern", "ron=" + str(rmeta)]
    for directory in deps:
        common += ["-L", "dependency=" + directory]
    for ok, body in ((True, "ron::Value::Bool(true)"), (False, "true")):
        source.write_text("pub fn value() -> ron::Value { " + body + " }\n")
        if result.exists():
            result.unlink()
        p = subprocess.run(common + [str(source), "-o", str(result)], env=env, cwd=place, capture_output=True, timeout=120)
        archive(out / (label + (".good" if ok else ".bad") + ".stderr.gz"), p.stderr)
        assert p.returncode == int(not ok), (p.returncode, p.stderr[-1500:])
        if ok:
            assert result.stat().st_size > 0
            content = result.read_bytes()
            archive(out / (label + ".consumer.rmeta.gz"), content)
            identity["consumer"] = [len(content), hashlib.sha256(content).hexdigest()]
        else:
            errors = [m for line in p.stderr.splitlines() if (m := json.loads(line))["level"] == "error" and m.get("code")]
            assert len(errors) == 1 and errors[0]["code"]["code"] == "E0308"
            assert any(s["is_primary"] and Path(s["file_name"]) == source and s["line_start"] == 1 for s in errors[0]["spans"])
    return identity


def main(a):
    root = a.root
    assert root.is_absolute() and not root.exists() and root.parent == Path(os.environ["RUNNER_TEMP"]).resolve()
    root.mkdir(mode=0o700)
    out = root / "packet"
    out.mkdir()
    assert shutil.disk_usage(root).free >= 42 * 2**30
    cfg = json.loads(a.registration.read_bytes())
    identities = check_sdk(a.sdk, cfg)
    sdk = root / "sdk"
    (sdk / "bin").mkdir(parents=True)
    for item in a.sdk.iterdir():
        if item.name != "bin":
            (sdk / item.name).symlink_to(item, target_is_directory=item.is_dir())
    for item in (a.sdk / "bin").iterdir():
        if item.name != "cargo":
            (sdk / "bin" / item.name).symlink_to(item)
    install = sdk / "bin/cargo"
    path = root / "rustup/toolchains/ohm"
    path.parent.mkdir(parents=True)
    path.symlink_to(sdk, target_is_directory=True)
    shims = root / "shims"
    shims.mkdir()
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    for name in ("cargo", "rustc", "rustdoc"):
        (shims / name).symlink_to(rustup)
    target, build = root / "targets" / "ruff", root / "build" / "shared"
    env = {"HOME": str(root / "home"), "CARGO_HOME": str(root / "registry"), "RUSTUP_HOME": str(path.parent.parent),
           "RUSTUP_AUTO_INSTALL": "0", "CARGO_BUILD_BUILD_DIR": str(build), "CARGO_TARGET_DIR": str(target),
           "USER": os.environ.get("USER", "runner"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(root / "tmp"),
           "PATH": str(shims) + ":/usr/local/bin:/usr/bin:/bin", "CARGO_NET_OFFLINE": "true", "CARGO_TERM_COLOR": "never"}
    for key in ("HOME", "CARGO_HOME", "TMPDIR"):
        Path(env[key]).mkdir()
    for p in (build, target):
        p.parent.mkdir()
    src = root / "source"
    subprocess.run(["git", "init", "-q", src], check=True)
    def git(*args):
        return read_output(["git", "-C", src, *args])
    for depth, rev in ((1, RUFF), (2, HISTORY)):
        git("fetch", "--quiet", "--no-tags", "--depth=" + str(depth), "https://github.com/astral-sh/ruff.git", rev)
    git("switch", "--quiet", "--detach", RUFF)
    patch = git("diff", "--binary", "--abbrev=10", HISTORY + "^", HISTORY)
    assert git("rev-parse", "HEAD^{tree}").decode().strip() == TREE and sha(src / "Cargo.lock") == LOCK
    assert hashlib.sha256(patch).hexdigest() == PATCH and (src / EDIT).read_bytes() == git("show", HISTORY + ":" + EDIT)
    archive(out / "historical.patch.gz", patch)
    original = (src / SOURCE).read_bytes()
    assert original == git("show", RUFF + ":" + SOURCE)
    alias = (path.lstat().st_dev, path.lstat().st_ino)
    def switch(role, binary):
        r = cfg[role]
        assert (r["source"], r["tree"]) == ROLES[role] and sha(binary) == r["sha256"]
        staged = install.with_name("candidate.tmp")
        assert not staged.exists()
        shutil.copyfile(binary, staged)
        staged.chmod(0o755)
        staged.replace(install)
        assert sha(install) == r["sha256"] and check_sdk(sdk, cfg) == identities
        assert (path.lstat().st_dev, path.lstat().st_ino) == alias
        version = read_output(["cargo", "+ohm", "-Vv"], env)
        assert ("commit-hash: " + r["source"] + "\n").encode() in version and b"release: 1.99.0-dev\n" in version
        save(out / (role + ".json"), {"path": str(install), "sha256": sha(install), "alias": alias,
                                     "version": version.decode(), "sdk": identities, "source": r})
    switch("pinned", a.pinned)
    subprocess.run(["cargo", "+ohm", "fetch", "--locked"], cwd=src, env={k: v for k, v in env.items() if k != "CARGO_NET_OFFLINE"},
                   check=True, timeout=1200)
    locked = {p["name"] + "-" + p["version"] + ".crate": p["checksum"] for p in tomllib.loads((src / "Cargo.lock").read_text())["package"] if "checksum" in p}
    crates = {p.name: sha(p) for p in (root / "registry/registry").glob("cache/*/*.crate")}
    assert len(locked) == 498 and locked == crates
    save(out / "source.json", {"head": RUFF, "tree": TREE, "lock": LOCK, "patch": PATCH, "archives": crates})
    rows_by_phase = {}
    def visit(label, verdict, *, off=False):
        working = dict(env)
        if off:
            working["CARGO_TARGET_DIR"], working["CARGO_BUILD_BUILD_DIR"] = str(root / "off-target"), str(root / "off-build")
        argv = ["cargo", "+ohm"] + (["-Zohm-defaults=no"] if off else []) + ["check", "-p", "ty_project", "--tests", "--locked", "--offline", "-j8", "--message-format=json"]
        before = (sha(src / SOURCE), sha(src / EDIT), sha(src / "Cargo.lock"), sha(install))
        p = subprocess.run(argv, cwd=src, env=working, capture_output=True, timeout=1800)
        archive(out / (label + ".stdout.gz"), p.stdout)
        archive(out / (label + ".stderr.gz"), p.stderr)
        assert p.returncode == (101 if verdict == "invalid" else 0), (label, p.returncode, p.stderr[-800:])
        rows = [json.loads(line) for line in p.stdout.splitlines()]
        assert rows[-1] == {"reason": "build-finished", "success": p.returncode == 0}
        diags = diagnostic(rows)
        guard(diags, verdict)
        artifacts = [r for r in rows if r["reason"] == "compiler-artifact"]
        assert len(artifacts) == (302 if verdict == "invalid" else 303)
        assert any(r["target"]["name"] == "ron" for r in artifacts)
        capture_ron(out, label, artifacts, working)
        names = [r for r in artifacts if r["target"]["name"] == "ty_project"]
        assert bool(names) == (verdict != "invalid")
        outputs = {}
        for r in names:
            for name in r["filenames"]:
                file = Path(name)
                assert file.resolve(strict=True).is_relative_to(Path(working["CARGO_TARGET_DIR"])) or file.resolve().is_relative_to(Path(working["CARGO_BUILD_BUILD_DIR"]))
                outputs[str(file)] = [file.stat().st_size, sha(file)]
        assert before == (sha(src / SOURCE), sha(src / EDIT), sha(src / "Cargo.lock"), sha(install))
        result = {"label": label, "verdict": verdict, "exit": p.returncode, "source_and_cargo": before,
                  "diag": diags, "cargo_units": len(artifacts), "ty_outputs": outputs,
                  "dirty": sorted(r["target"]["name"] for r in artifacts if not r["fresh"])}
        if label in {"warning", "pinned-warning-repeat", "pinned-empty-at-same-paths",
                     "upgraded", "upgraded-repeat", "fresh-repair", "fixed-empty-at-same-paths"}:
            result["typed_reader"] = typed_reader(root, out, label, artifacts, working)
        save(out / (label + ".json"), result)
        rows_by_phase[label] = result
        return result
    visit("original", "clean")
    subprocess.run(["git", "apply", "--reverse", "-"], cwd=src, input=patch, check=True)
    assert (src / EDIT).read_bytes() == git("show", HISTORY + "^:" + EDIT)
    visit("historical-edit", "clean")
    (src / SOURCE).write_bytes(original + WARN)
    pinned_first = visit("warning", "warning")
    pinned_repeat = visit("pinned-warning-repeat", "warning")
    retained = {}
    for directory in (target, build):
        saved = directory.with_name(directory.name + "-pinned-before-control")
        assert not saved.exists()
        retained[directory] = [saved, directory.stat().st_dev, directory.stat().st_ino]
        directory.rename(saved)
    pinned_empty = visit("pinned-empty-at-same-paths", "warning")
    for directory, (saved, dev, ino) in retained.items():
        independent = directory.with_name(directory.name + "-pinned-empty")
        assert not independent.exists()
        directory.rename(independent)
        saved.rename(directory)
        assert (directory.stat().st_dev, directory.stat().st_ino) == (dev, ino)
    (src / SOURCE).write_bytes(original + BAD)
    visit("invalid", "invalid")
    (src / SOURCE).write_bytes(original + WARN)
    visit("pinned-repair", "stale")
    visit("pinned-repeat", "stale")
    visit("opt-out-clean", "warning", off=True)
    visit("opt-out-repeat", "warning", off=True)
    old_dirs = [(p.stat().st_dev, p.stat().st_ino) for p in (target, build)]
    switch("fixed", a.fixed)
    assert [(p.stat().st_dev, p.stat().st_ino) for p in (target, build)] == old_dirs
    first, repeat = visit("upgraded", "warning"), visit("upgraded-repeat", "warning")
    visit("opt-out-upgraded", "warning", off=True)
    (src / SOURCE).write_bytes(original + BAD)
    visit("fresh-invalid", "invalid")
    (src / SOURCE).write_bytes(original + WARN)
    repair = visit("fresh-repair", "warning")
    for p in (target, build):
        retained = p.with_name(p.name + "-retained")
        assert not retained.exists()
        p.rename(retained)
    assert not target.exists() and not build.exists()
    clean = visit("fixed-empty-at-same-paths", "warning")
    def comparison(warm, empty):
        return {item["label"]: {"diagnostics": item["diag"] == empty["diag"], "root_outputs": item["ty_outputs"] == empty["ty_outputs"],
                               "ron": item["typed_reader"]["ron"] == empty["typed_reader"]["ron"],
                               "external_consumer": item["typed_reader"]["consumer"] == empty["typed_reader"]["consumer"]}
                for item in warm}
    baseline = comparison((pinned_first, pinned_repeat), pinned_empty)
    candidate = comparison((first, repeat, repair), clean)
    save(out / "warm-versus-empty.json", {"pinned": baseline, "fourfix": candidate})
    assert all(all(values.values()) for values in candidate.values()), ("warm/empty mismatch", baseline, candidate)
    save(out / "complete.json", {"run": int(os.environ["GITHUB_RUN_ID"]), "qa": os.environ["GITHUB_SHA"], "source": RUFF,
                                 "accepted": list(rows_by_phase), "sdk": identities, "roles": ROLES})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "sdk", "pinned", "fixed", "registration"):
        p.add_argument(name, type=Path)
    main(p.parse_args())
