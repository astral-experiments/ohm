"""Install the newly assembled archive and exercise both forms of private native export."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sources import CARGO, REVIEWED, RUST, TOOLS, git, need, sha


def save(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")


def run(out, name, args, env, cwd):
    proc = subprocess.run(args, env=env, cwd=cwd, capture_output=True, timeout=240)
    (out / (name + ".stdout")).write_bytes(proc.stdout)
    (out / (name + ".stderr")).write_bytes(proc.stderr)
    save(out / (name + ".json"), {"argv": list(map(str, args)), "exit": proc.returncode})
    need(proc.returncode == 0, (name, proc.stderr[-2000:]))
    return proc.stdout


def rust_dylib(work, out, env, sdk, host):
    work.mkdir()
    out.mkdir()
    case = HERE / "rust-dylib"
    contracts = {"leaf": "", "owner": '[lib]\ncrate-type=["dylib"]\n[dependencies]\nleaf={path="../leaf"}\n',
                 "client": '[dependencies]\nowner={path="../owner"}\n'}
    (work / "Cargo.toml").write_text('[workspace]\nmembers=["leaf","owner","client"]\nresolver="3"\n[profile.dev.package.leaf]\nopt-level=1\n')
    for crate, extra in contracts.items():
        part = work / crate
        (part / "src").mkdir(parents=True)
        (part / "Cargo.toml").write_text(f'[package]\nname="{crate}"\nversion="0.0.0"\nedition="2024"\n' + extra)
        shutil.copyfile(case / (crate + ".rs"), part / "src" / ("main.rs" if crate == "client" else "lib.rs"))
    hidden = work / "leaf/src/hidden.rs"
    old = (case / "hidden.rs").read_bytes()
    need(old.count(b"value: u32") == 1, "different private field")
    new = old.replace(b"value: u32", b"value: u64")
    hidden.write_bytes(old)
    env = dict(env, CARGO_TARGET_DIR=str(work / "target"), CARGO_BUILD_BUILD_DIR=str(work / "build"), CARGO_NET_OFFLINE="true")
    run(out, "lock", ["cargo", "+ohm", "generate-lockfile", "--offline"], env, work)
    states = {}
    for phase, body, value in [("old", old, 17), ("edited", new, 4294967313), ("unchanged", new, 4294967313),
                              ("empty", new, 4294967313), ("return", old, 17)]:
        if phase == "empty":
            for key in ("target", "build"):
                (work / key).rename(work / (key + "-parked"))
        if hidden.read_bytes() != body:
            hidden.write_bytes(body)
        dst = out / phase
        dst.mkdir()
        raw = run(dst, "cargo", ["cargo", "+ohm", "build", "-p", "client", "--offline", "--locked", "--message-format=json"], env, work)
        messages = [json.loads(line) for line in raw.splitlines()]
        need([r["success"] for r in messages if r["reason"] == "build-finished"] == [True], phase)
        artifacts = {r["target"]["name"]: r for r in messages if r["reason"] == "compiler-artifact"}
        need(set(artifacts) == contracts.keys(), ("wrong ordinary dynamic consumer", artifacts.keys()))
        client = Path(artifacts["client"]["executable"])
        native, = [Path(path) for path in artifacts["owner"]["filenames"] if path.endswith((".so", ".dylib"))]
        apple = host == "aarch64-apple-darwin"
        deps = run(dst, "dynamic", (["otool", "-L"] if apple else ["readelf", "-d"]) + [client], env, work)
        need(native.name.encode() in deps, (phase, "no actual dependency", native.name))
        dirs = [native.parent, client.parent / "deps", sdk / "lib/rustlib" / host / "lib", sdk / "lib"]
        runtime = dict(env, **{("DYLD_LIBRARY_PATH" if apple else "LD_LIBRARY_PATH"): os.pathsep.join(map(str, dirs))})
        actual = run(dst, "execute", [client], runtime, work)
        need(actual == f"{value}\n".encode(), (phase, actual))
        states[phase] = {"value": value, "client_sha256": sha(client), "library_sha256": sha(native), "source_sha256": sha(hidden)}
        save(dst / "observed.json", states[phase])
    need(states["old"]["library_sha256"] != states["edited"]["library_sha256"], "changed private field gave the same dylib")
    need(states["edited"] == states["unchanged"], "unchanged native reader changed")
    return states


def cargo_repair(work, out, env):
    work.mkdir()
    out.mkdir()
    for sub in ("src", "dep/src"):
        (work / sub).mkdir(parents=True)
    (work / "Cargo.toml").write_text('[package]\nname="app"\nversion="0.0.0"\nedition="2024"\n[dependencies]\ndep={path="dep"}\n')
    (work / "dep/Cargo.toml").write_text('[package]\nname="dep"\nversion="0.0.0"\nedition="2024"\n')
    env = dict(env, CARGO_TARGET_DIR=str(work / "target"), CARGO_BUILD_BUILD_DIR=str(work / "build"), CARGO_NET_OFFLINE="true")
    app = work / "src/lib.rs"
    dep = work / "dep/src/lib.rs"
    healthy = b"pub fn value() -> u32 { dep::value() }\nfn unused_after_repair() {}\n"
    invalid = {"E0308": b'const BAD: u32 = "invalid";\n', "E0425": b'const BAD: u32 = missing_value;\n'}
    app.write_bytes(healthy)
    dep.write_text("pub fn value() -> u32 { 1 }\n")
    run(out, "lock", ["cargo", "+ohm", "generate-lockfile", "--offline"], env, work)
    phases = [("warning", 1, ""), ("unchanged", 1, ""), ("malformed-type", 1, "E0308"),
              ("repaired", 2, ""), ("dependency-body-change", 3, ""), ("malformed-name", 3, "E0425"),
              ("repaired-again", 4, ""), ("settled", 4, ""), ("empty", 4, "")]
    states = {}
    for phase, value, error in phases:
        if phase == "empty":
            for key in ("target", "build"):
                (work / key).rename(work / (key + "-parked"))
        for path, data in [(app, healthy + invalid.get(error, b"")), (dep, f"pub fn value() -> u32 {{ {value} }}\n".encode())]:
            if path.read_bytes() != data:
                path.write_bytes(data)
        dst = out / phase
        dst.mkdir()
        cmd = ["cargo", "+ohm", "check", "--tests", "--locked", "--offline", "--message-format=json"]
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, timeout=120)
        (dst / "cargo.stdout").write_bytes(proc.stdout)
        (dst / "cargo.stderr").write_bytes(proc.stderr)
        messages = [json.loads(line) for line in proc.stdout.splitlines()]
        diagnostics = [m["message"] for m in messages if m["reason"] == "compiler-message"]
        errors = [m for m in diagnostics if m["level"] == "error"]
        warnings = [m for m in diagnostics if m["level"] == "warning" and (m.get("code") or {}).get("code") == "dead_code"
                    and "unused_after_repair" in m["message"]]
        need(proc.returncode == (101 if error else 0) and [m["success"] for m in messages if m["reason"] == "build-finished"] == [not error], phase)
        need([m["code"]["code"] for m in errors] == ([error] if error else []), (phase, "unexpected diagnostic", errors))
        if not error:
            need(len(warnings) == 1 and any(s["file_name"] == "src/lib.rs" and s["line_start"] == 2 for s in warnings[0]["spans"]), (phase, "missing original warning"))
        states[phase] = {"argv": cmd, "exit": proc.returncode, "error": error, "warnings": len(warnings), "app": sha(app), "dep": sha(dep),
                         "typed_artifacts": [[m["target"]["name"], m["fresh"]] for m in messages if m["reason"] == "compiler-artifact"]}
        save(dst / "observed.json", states[phase])
    return states


def main(workspace, root):
    release = workspace / "release"
    root.mkdir(exist_ok=True)
    report = root / "reports"
    report.mkdir(exist_ok=True)
    host = os.environ["OHM_TARGET"]
    need((platform.system(), platform.machine()) == {"aarch64-apple-darwin": ("Darwin", "arm64"), "x86_64-unknown-linux-gnu": ("Linux", "x86_64")}[host], "foreign host")
    name = "ohm-1.99.0-22"
    manifest = json.loads((release / (name + ".json")).read_bytes())
    expected = {"rust": RUST, "cargo": CARGO, **{k: v[0] for k, v in TOOLS.items()}}
    need({k: v["revision"] for k, v in manifest["sources"].items()} == expected, "different actual release manifest")
    prefix = name + "-" + host
    origin = json.loads((release / (prefix + "-provenance.json")).read_bytes())
    need(origin["coordinator"] == {"repository": "astral-experiments/ohm", "revision": os.environ["GITHUB_SHA"]} and origin["target"] == host
         and origin["toolchain"] == name and {k: v["revision"] for k,v in origin["sources"].items()} == expected, "wrong assembled provenance")
    need(origin["manifest"]["sha256"] == sha(release / (name + ".json")), "wrong built manifest")
    archive = release / (prefix + ".tar.gz")
    digest = sha(archive)
    need((release / (archive.name + ".sha256")).read_text().split() == [digest, archive.name], "different archive")
    sdk = root / "installed"
    rup = root / "rustup"
    chome = root / "cargo"
    chome.mkdir()
    proxies = root / "proxies"
    proxies.mkdir()
    installed_rustup = Path(shutil.which("rustup")).resolve(strict=True)
    for alias in ("cargo", "rustc", "rustdoc", "rustup"):
        (proxies / alias).symlink_to(installed_rustup)
    env = dict(os.environ, OHM_DOWNLOAD_URL=release.as_uri(), OHM_INSTALL_DIR=str(sdk), RUSTUP_HOME=str(rup),
               CARGO_HOME=str(chome), PATH=str(proxies) + os.pathsep + os.environ["PATH"], RUSTUP_AUTO_INSTALL="0")
    run(report, "install", ["sh", release / "ohm-installer.sh"], env, workspace)
    need((rup / "toolchains/ohm").samefile(sdk), "installed alias points elsewhere")
    driver, = list((sdk / "lib").glob("librustc_driver-*"))
    paths = [sdk / "bin" / t for t in ("rustc", "rustdoc", "cargo", "cargo-clippy", "clippy-driver", "rustfmt", "cargo-fmt")]
    paths.extend([driver, sdk / "lib/rustlib/src/rust/library/core/src/lib.rs", sdk / "lib/rustlib" / host / "bin/rust-lld"])
    wasm, = list((sdk / "lib/rustlib/wasm32-unknown-unknown/lib").glob("libstd-*.rlib"))
    paths.append(wasm)
    if host.startswith("x86_64"):
        linker = sdk / "lib/rustlib" / host / "bin/wild-ld/ld.bfd"
        need(sha(linker) == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5", "changed stock Wild")
        paths.append(linker)
    members = {str(p.relative_to(sdk)): [p.stat().st_size, sha(p)] for p in paths}
    for tool, commit in [("rustc", RUST), ("rustdoc", RUST), ("cargo", CARGO)]:
        raw = run(report, tool, [tool, "+ohm", "-vV"], env, workspace).decode()
        need(f"commit-hash: {commit}\n" in raw and f"host: {host}\n" in raw, (tool, raw))
    if host.startswith("aarch64"):
        ld = Path(run(report, "xcrun-ld", ["xcrun", "-f", "ld"], env, workspace).decode().strip()).resolve(strict=True)
        members["external-xcode-ld"] = [ld.stat().st_size, sha(ld)]
    current = {"archive_sha256": digest, "archive_bytes": archive.stat().st_size, "members": members, "coordinator": REVIEWED,
               "qa": os.environ["GITHUB_SHA"], "run": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "target": host}
    save(report / "installed.json", current)
    probe = workspace / "export-probe/scripts/darwin-native-export/probe.py"
    need(git(workspace / "export-probe", "rev-parse", "HEAD") == "c0748d6bc1bac8e85828ea0c5c9f297eb10f88aa", "different constructor fixture")
    for mode in ("build", "test"):
        subprocess.run([sys.executable, "-IB", probe, root / mode, report / mode, rup, proxies, mode, "candidate", RUST, members["bin/cargo"][1]], check=True, env=env)
    current["rust_dylib"] = rust_dylib(root / "rust-only-work", report / "rust-only", env, sdk, host)
    current["cargo_diagnostic_repair"] = cargo_repair(root / "cargo-repair-work", report / "cargo-repair", env)
    current["constructor"] = {m:json.loads((report / m / "results.json").read_bytes()) for m in ("build", "test")}
    current["qualified"] = True
    save(report / "complete.json", current)


if __name__ == "__main__":
    main(Path(os.environ["GITHUB_WORKSPACE"]), Path(os.environ["RUNNER_TEMP"]) / "integrated-smoke")
