"""Ordinary two-crate Cargo transitions. The native verifier reopens the retained streams and ELFs."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
PARENT = "556a8364f1485a03be31b1a50c250d63198a943d"
CARGO = "4591cf45cc10abb19d2456c40b99606e08167f29"
CARGO_SHA = "b45c94851ffc8d00753a8155aa29cb177321361fc91a5a1b3e7fab2c46bb251f"
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
HOST = "x86_64-unknown-linux-gnu"
CASES = ("build", "test", "name", "body", "abi", "nested")
PHASES = ("cold-A", "unchanged-A", "edit-B", "unchanged-B", "restore-A", "return-B",
          "invalid-A", "repair-A", "empty-B", "empty-A", "empty-invalid-A")


def need(ok, detail):
    if not ok:
        raise ValueError(detail)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def blob(path, data):
    path.write_bytes(gzip.compress(data, compresslevel=1, mtime=0))


def environment(root, sdk):
    root.mkdir(parents=True)
    proxies = root / "proxies"
    proxies.mkdir()
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    for name in ("rustup", "cargo", "rustc", "rustdoc"):
        (proxies / name).symlink_to(rustup)
    alias = root / "rustup/toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sdk.resolve(strict=True))
    env = {"PATH": str(proxies) + ":/usr/local/bin:/usr/bin:/bin", "RUSTUP_HOME": str(root / "rustup"),
           "RUSTUP_AUTO_INSTALL": "0", "CARGO_NET_OFFLINE": "true", "CARGO_TERM_COLOR": "never",
           "LC_ALL": "C.UTF-8", "CARGO_TARGET_DIR": str(root / "target"),
           "CARGO_BUILD_BUILD_DIR": str(root / "build")}
    for k, name in (("HOME", "home"), ("TMPDIR", "temp"), ("CARGO_HOME", "registry")):
        (root / name).mkdir()
        env[k] = str(root / name)
    return env


def call(args, env, cwd, timeout=120):
    return subprocess.run(list(map(str, args)), env=env, cwd=cwd, capture_output=True, timeout=timeout)


def subjects(sdk, env, revision):
    versions = {}
    for tool, commit in (("cargo", CARGO), ("rustc", revision)):
        path = sdk / "bin" / tool
        v = call([tool, "+ohm", "-vV"], env, sdk)
        which = call(["rustup", "which", "--toolchain", "ohm", tool], env, sdk)
        need(v.returncode == which.returncode == 0 and ("commit-hash: " + commit + "\n").encode() in v.stdout
             and ("host: " + HOST + "\n").encode() in v.stdout
             and Path(which.stdout.decode().strip()).samefile(path), ("wrong physical role", tool, v.stderr))
        versions[tool] = {"sha256": sha(path), "version": v.stdout.decode()}
    driver, = list((sdk / "lib").glob("librustc_driver-*.so"))
    versions.update(driver=sha(driver), wild=sha(sdk / "lib/rustlib" / HOST / "bin/wild-ld/ld.bfd"))
    need(versions["cargo"]["sha256"] == CARGO_SHA and versions["wild"] == WILD, versions)
    if revision == PARENT:
        need(versions["driver"] == "07a3122d625927e970985f6e74d377cbed179476790e8ff3c0401dcd2b165701", versions)
    return versions


def parameters(case):
    abi = case in ("abi", "nested")
    binary = case == "build"
    fixture = HERE / "fixtures" / (case if abi else "registration")
    subcommand = (["build", "-p", "test_owner", "--bin", "test_owner"] if binary else
                  ["test", "-p", "abi_probe_owner" if abi else "test_owner", "--test",
                   "native" if abi else "control", "--no-run"])
    return fixture, binary, abi, ["cargo", "+ohm", *subcommand, "--offline", "--locked", "-j4", "--message-format=json"]


def hidden(fixture, case, state):
    data = (fixture / state / "hidden.rs").read_bytes()
    if state == "B" and case == "name":
        data = data.replace(b".store(83,", b".store(17,")
    if state == "B" and case == "body":
        data = data.replace(b"_bbbb", b"_aaaa")
    return data


def phases(migration):
    return PHASES[:2] + ("upgrade-A",) + PHASES[2:] if migration else PHASES


def run(out, work, case, sdk, revision, second=None):
    fixture, binary, abi, args = parameters(case)
    out.mkdir(parents=True)
    env = environment(work, sdk)
    versions = subjects(sdk, env, revision)
    source = work / "project"
    source.mkdir()
    for name in ("Cargo.toml", "Cargo.lock", "dep", "owner"):
        original = fixture / name
        if original.is_file():
            shutil.copy2(original, source / name)
        else:
            shutil.copytree(original, source / name)
    if binary:
        old = source / "owner/tests/control.rs"
        replacement = source / "owner/src/main.rs"
        replacement.parent.mkdir()
        replacement.write_bytes(old.read_bytes().replace(b"#[test] fn root_value()", b"fn main()"))
        old.unlink()
    (out / "bodies").mkdir()
    save(out / "subject.json", {"role": revision, "versions": versions, "case": case, "argv": args,
         "inputs": {str(f.relative_to(source)): sha(f) for f in source.rglob("*") if f.is_file()}})
    last = None
    for phase in phases(bool(second)):
        if second and phase == "upgrade-A":
            new, new_rev = second
            alias = work / "rustup/toolchains/ohm"
            swap = alias.with_name("new")
            swap.symlink_to(new.resolve(strict=True))
            swap.replace(alias)
            save(out / "migrated.json", subjects(new, env, new_rev))
        loc = out / phase
        loc.mkdir()
        if phase.startswith("empty-"):
            for n in ("target", "build"):
                (work / n).rename(work / (n + "-before-" + phase))
        state = phase[-1]
        data = hidden(fixture, case, state)
        if "invalid" in phase:
            data += b'const _: u8 = "wrong";\n'
        if data != last:
            (source / "dep/src/hidden.rs").write_bytes(data)
        last = data
        p = call(args, env, source)
        blob(loc / "stdout.gz", p.stdout)
        blob(loc / "stderr.gz", p.stderr)
        for ice in source.glob("rustc-ice-*.txt"):
            shutil.move(ice, loc / ice.name)
        events = [json.loads(line) for line in p.stdout.splitlines()]
        need(events[-1] == {"reason": "build-finished", "success": p.returncode == 0}, (phase, p.stderr))
        typed = [e for e in events if e["reason"] == "compiler-artifact"]
        record = {"code": p.returncode, "source": sha(source / "dep/src/hidden.rs"),
                  "artifacts": [[e["target"]["name"], e["fresh"]] for e in typed],
                  "shared_dirs": sorted(d.name for d in (work / "build").rglob("v2-*") if d.is_dir())}
        if p.returncode == 0:
            exe, = [Path(e["executable"]) for e in typed if e.get("executable")]
            dig = sha(exe)
            dest = out / "bodies" / (dig + ".gz")
            if not dest.exists():
                blob(dest, exe.read_bytes())
            record["elf"] = dig
            env_name = "EXPECTED_VALUE" if abi else "WANT"
            test = "library_answer" if abi else "root_value"
            if not binary:
                listing = call([exe, "--list"], env, source)
                need(listing.returncode == 0, listing.stderr)
                (loc / "inventory.txt").write_bytes(listing.stdout)
            outcomes = {}
            for expected in (17, 0x100000011 if abi else 83):
                cmd = [exe] if binary else [exe, "--exact", test, "--nocapture"]
                r = call(cmd, env | {env_name: str(expected)}, source)
                (loc / f"native-{expected}.txt").write_bytes(r.stdout + r.stderr)
                outcomes[str(expected)] = r.returncode
            record["executions"] = outcomes
        save(loc / "visit.json", record)
        print(case, phase, p.returncode, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for n in ("output", "work", "sdk"):
        p.add_argument(n, type=Path)
    p.add_argument("revision")
    p.add_argument("--case", choices=CASES, action="append")
    p.add_argument("--migration-sdk", type=Path)
    p.add_argument("--migration-revision")
    opt = p.parse_args()
    need(bool(opt.migration_sdk) == bool(opt.migration_revision), "incomplete migration")
    for case in opt.case or CASES:
        run(opt.output.resolve() / case, opt.work.resolve() / case, case, opt.sdk.resolve(), opt.revision,
            (opt.migration_sdk, opt.migration_revision) if opt.migration_sdk else None)
