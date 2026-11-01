"""Exercise feature-sensitive Cargo installs with the two native release SDKs."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tarfile


SOURCES = {
    "published-22": ("008a21ac0d750dc9a1c18b7959d7e7984c03d887", "ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770"),
    "candidate": ("f12924d918dbc66898325531940a20aa8cf4f5fc", "159be68484a7f8cb05debf82bee89e594b7f19b6"),
}
HOSTS = {("Linux", "x86_64"): "x86_64-unknown-linux-gnu", ("Darwin", "arm64"): "aarch64-apple-darwin"}
SENTINEL = b"preexisting executable, owned outside Cargo\n"
GATED = """[package]
name = "featuregate"
version = "1.0.0"
edition = "2024"

[features]
extra = []

[[bin]]
name = "optional"
path = "optional.rs"
required-features = ["extra"]
"""
SIBLINGS = """[package]
name = "splitbins"
version = "1.0.0"
edition = "2024"

[features]
extra = []
"""
PROGRAM = 'fn main() { println!("{}", cfg!(feature = "extra")); }\n'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def local_registry(root):
    """Write Cargo's ordinary local-registry index and its checksum-matched crate."""
    root.mkdir()
    files = {"Cargo.toml": SIBLINGS, "src/bin/first.rs": PROGRAM, "src/bin/second.rs": PROGRAM}
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, text in files.items():
            data = text.encode()
            item = tarfile.TarInfo("splitbins-1.0.0/" + name)
            item.mode, item.size = 0o644, len(data)
            archive.addfile(item, io.BytesIO(data))
    crate = root / "splitbins-1.0.0.crate"
    crate.write_bytes(gzip.compress(tar.getvalue(), mtime=0))
    entry = root / "index/sp/li/splitbins"
    entry.parent.mkdir(parents=True)
    record = {"name": "splitbins", "vers": "1.0.0", "deps": [], "features": {"extra": []},
              "cksum": sha(crate), "yanked": False}
    entry.write_text(json.dumps(record) + "\n")
    return {"sources": files, "archive": sha(crate), "index": sha(entry)}


def file_identity(path):
    st = path.lstat()
    need(stat.S_ISREG(st.st_mode), f"unexpected nonregular file {path}")
    return {"sha256": sha(path), "inode": st.st_ino, "device": st.st_dev,
            "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "mode": stat.S_IMODE(st.st_mode)}


class NativeRole:
    def __init__(self, role, sdk, work, out, launchers, bodies):
        self.role, self.sdk, self.work, self.out, self.bodies = role, sdk, work, out, bodies
        self.host = HOSTS[platform.system(), platform.machine()]
        work.mkdir()
        out.mkdir()
        for name in ("home", "rustup/toolchains", "cargo", "tmp"):
            (work / name).mkdir(parents=True)
        (work / "rustup/toolchains/ohm").symlink_to(sdk, target_is_directory=True)
        (work / "rustup/settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
        self.env = {k: os.environ[k] for k in ("SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET")
                    if k in os.environ}
        self.env.update(PATH=str(launchers) + os.pathsep + os.environ["PATH"], HOME=str(work / "home"),
                        RUSTUP_HOME=str(work / "rustup"), RUSTUP_AUTO_INSTALL="0",
                        CARGO_HOME=str(work / "cargo"), TMPDIR=str(work / "tmp"), LC_ALL="C",
                        CARGO_BUILD_JOBS="2", CARGO_TERM_COLOR="never", GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_ALLOW_PROTOCOL="file", GIT_TERMINAL_PROMPT="0")
        self.cargo = [str(launchers / "cargo"), "+ohm"]
        self.launchers = launchers

    def command(self, name, argv, cwd=None):
        p = subprocess.run(argv, cwd=cwd or self.work, env=self.env, capture_output=True, timeout=120)
        (self.out / (name + ".stdout")).write_bytes(p.stdout)
        (self.out / (name + ".stderr")).write_bytes(p.stderr)
        save(self.out / (name + ".json"), {"argv": list(map(str, argv)), "cwd": str(cwd or self.work),
             "status": p.returncode, "stdout_sha256": hashlib.sha256(p.stdout).hexdigest(),
             "stderr_sha256": hashlib.sha256(p.stderr).hexdigest()})
        return p

    def tools(self):
        rows = {}
        for name, revision in zip(("rustc", "cargo"), SOURCES[self.role], strict=True):
            which = self.command(name + "-which", [self.launchers / "rustup", "which", "--toolchain", "ohm", name])
            which.check_returncode()
            selected = Path(os.fsdecode(which.stdout).strip())
            expected = self.sdk / "bin" / name
            need(selected.samefile(expected), f"wrong actual {name} selection")
            v = self.command(name + "-version", [self.launchers / name, "+ohm", "-vV"])
            v.check_returncode()
            lines = v.stdout.decode().splitlines()
            need(lines[0].startswith(name + " ") and f"commit-hash: {revision}" in lines
                 and f"host: {self.host}" in lines, f"unexpected {name} version {lines}")
            rows[name] = {"path": str(selected), "resolved": str(selected.resolve()), "sha256": sha(expected),
                          "commit": revision, "host": self.host}
        sysroot = self.command("sysroot", [self.launchers / "rustc", "+ohm", "--print", "sysroot"])
        sysroot.check_returncode()
        need(Path(os.fsdecode(sysroot.stdout).strip()).samefile(self.sdk), "foreign rustc sysroot")
        save(self.out / "tools.json", rows)
        return rows

    def install(self, label, root, *opts):
        return self.command(label, [*self.cargo, "install", "-vv", "--root", root, *opts])

    def binary(self, label, path, values):
        identity = file_identity(path)
        need(identity["mode"] & 0o111, f"installed output is not executable: {path}")
        raw = path.read_bytes()
        if self.host.startswith("x86_64"):
            need(raw[:6] == b"\x7fELF\x02\x01" and int.from_bytes(raw[18:20], "little") == 62,
                 f"expected x86-64 ELF: {path}")
        else:
            need(raw[:4] == bytes.fromhex("cffaedfe") and int.from_bytes(raw[4:8], "little") == 0x0100000c,
                 f"expected arm64 Mach-O: {path}")
        body = self.bodies / (identity["sha256"] + ".gz")
        if not body.exists():
            body.write_bytes(gzip.compress(raw, mtime=0))
        need(gzip.decompress(body.read_bytes()) == raw, f"captured wrong executable: {path}")
        p = self.command(label, [path])
        p.check_returncode()
        need(p.stdout in {v.encode() + b"\n" for v in values} and not p.stderr, f"unexpected {path} output {p.stdout!r}")
        return dict(identity, output=p.stdout.decode().strip(), path=str(path), body=body.name)

    def gated(self, fixture):
        results = {}
        for tracking, options in (("tracked", []), ("untracked", ["--no-track"])):
            for enabled in (False, True):
                label = "collision-" + tracking + ("-enabled" if enabled else "-disabled")
                root = self.work / label
                dest = root / "bin"
                dest.mkdir(parents=True)
                optional = dest / "optional"
                optional.write_bytes(SENTINEL)
                optional.chmod(0o755)
                before = file_identity(optional)
                p = self.install(label, root, "--path", fixture, *options, *(["--features", "extra"] if enabled else []))
                need(file_identity(optional) == before and optional.read_bytes() == SENTINEL,
                     f"{label}: touched the existing executable")
                main = dest / "featuregate"
                row = {"foreign": before, "status": p.returncode}
                if p.returncode == 0:
                    need(not enabled, f"{label}: missed the enabled collision")
                    row.update(result="installed", native=self.binary(label + "-run", main, ["mandatory"]))
                else:
                    err = p.stderr.decode()
                    messages = {"error: binary `optional` already exists in destination",
                                f"error: binary `optional` already exists in destination `{optional}`"}
                    need(p.returncode == 101 and any(l in messages for l in err.splitlines())
                         and "Add --force to overwrite" in err and not main.exists(),
                         f"{label}: unrecognized collision, see original stderr")
                    need(enabled or self.role == "published-22", f"{label}: refused an inactive executable")
                    row["result"] = "active collision" if enabled else "old inactive collision"
                results[label] = row
        # Prove the optional target is selectable and its installed program really works.
        root = self.work / "enabled-free"
        self.install("enabled-free", root, "--path", fixture, "--features", "extra").check_returncode()
        results["enabled-free"] = [self.binary("enabled-free-" + name, root / "bin" / name, [value])
                                   for name, value in (("featuregate", "mandatory"), ("optional", "optional"))]
        return results

    def git_repeat(self, fixture):
        root = self.work / "git-install"
        opts = ["--git", fixture.as_uri()]
        cold = self.install("git-first", root, *opts)
        cold.check_returncode()
        main = root / "bin/featuregate"
        first = self.binary("git-run-first", main, ["mandatory"])
        second = self.install("git-repeat", root, *opts)
        second.check_returncode()
        final = self.binary("git-run-repeat", main, ["mandatory"])
        need(not (root / "bin/optional").exists(), "installed feature-disabled Git executable")
        err = second.stderr.decode().splitlines()
        ignored = any(re.match(r"\s*Ignored package `featuregate v1\.0\.0 ", l) and
                      "is already installed" in l for l in err)
        # -vv exposes every dispatched target command. Match the actual crate, not version queries or prose.
        def compiles(stderr):
            return sum("Running `" in line and re.search(r" --crate-name featuregate(?: |$)", line) is not None
                       for line in stderr.splitlines())
        need(compiles(cold.stderr.decode()) == 1, "missing real initial Git target compilation")
        count = compiles(second.stderr.decode())
        if ignored:
            need(count == 0 and first == final and not any(re.match(r"\s*(Compiling|Installing|Replacing) ", l) for l in err),
                 "ignored install changed the executable or dispatched compiler work")
            result = "skipped"
        else:
            need(self.role == "published-22" and count == 1 and
                 any(re.match(r"\s*Compiling featuregate v1\.0\.0 ", l) for l in err) and
                 any(re.match(r"\s*Replac(?:ing|ed) ", l) for l in err),
                 "unrecognized repeated install or candidate recompiled")
            result = "old repeated compilation"
        return {"result": result, "repeat_target_compilations": count, "first": first, "repeat": final}

    def siblings(self):
        root = self.work / "registry-install"
        snapshots = []
        for name, opts, values in (("both-extra", ["--features", "extra"], (["true"], ["true"])),
                                   ("only-first", ["--bin", "first"], (["false"], ["true"])),
                                   ("both-default", [], (["false"], ["false", "true"]))):
            p = self.install("registry-" + name, root, "--config", 'source.crates-io.replace-with="fixture"',
                             "--offline", "splitbins", *opts)
            p.check_returncode()
            pair = [self.binary("registry-" + name + "-" + k, root / "bin" / k, v)
                    for k, v in zip(("first", "second"), values, strict=True)]
            snapshots.append(pair)
        need(snapshots[1][1] == snapshots[0][1], "one-bin selection changed its sibling")
        if snapshots[2][1]["output"] == "true":
            need(self.role == "published-22" and snapshots[1][1] == snapshots[2][1] and
                 re.search(rb"(?m)^\s*Ignored package `splitbins v1\.0\.0` is already installed", p.stderr),
                 "stale candidate or unrecognized stale sibling")
            result = "old stale sibling"
        else:
            result = "corrected sibling"
        return {"result": result, "executions": snapshots}


def fixtures(worker):
    gated = worker.work / "featuregate"
    (gated / "src").mkdir(parents=True)
    (gated / "Cargo.toml").write_text(GATED)
    (gated / "src/main.rs").write_text('fn main() { println!("mandatory"); }\n')
    (gated / "optional.rs").write_text('fn main() { println!("optional"); }\n')
    sources = {str(p.relative_to(gated)): sha(p) for p in gated.rglob("*") if p.is_file()}
    for label, args in (("init", ["init", "-q", "-b", "main"]), ("add", ["add", "."]),
                        ("commit", ["-c", "user.name=Installer QA", "-c", "user.email=qa@example.invalid",
                                    "-c", "commit.gpgsign=false", "commit", "-qm", "Feature-gated binary"]),
                        ("head", ["rev-parse", "HEAD"])):
        worker.env.update(GIT_AUTHOR_DATE="2025-01-01T00:00:00Z", GIT_COMMITTER_DATE="2025-01-01T00:00:00Z")
        p = worker.command("fixture-git-" + label, ["git", *args], cwd=gated)
        p.check_returncode()
    registry = worker.work / "registry-source"
    registered = local_registry(registry)
    (worker.work / "cargo/config.toml").write_text('[source.crates-io]\nreplace-with = "fixture"\n'
                '[source.fixture]\nlocal-registry = ' + json.dumps(str(registry)) + '\n')
    save(worker.out / "fixtures.json", {"git_commit": p.stdout.decode().strip(), "git_sources": sources,
                                       "local_registry": registered})
    return gated


def role(name, sdk, work, out, proxies, bodies):
    worker = NativeRole(name, sdk, work, out, proxies, bodies)
    tools = worker.tools()
    gated = fixtures(worker)
    results = {"tools": tools, "collisions": worker.gated(gated), "repeat": worker.git_repeat(gated),
               "siblings": worker.siblings()}
    need(all(sha(sdk / "bin" / k) == row["sha256"] for k, row in tools.items()), "changed SDK during qualification")
    save(out / "complete.json", results)
    return results


def run(candidate, published, work, out):
    sdks = {k:p.resolve(strict=True) for k,p in (("candidate", candidate), ("published-22", published))}
    need(not sdks["published-22"].samefile(sdks["candidate"]), "requires two distinct SDKs")
    work, out = work.absolute(), out.absolute()
    roots = [work.resolve(), out.resolve(), *sdks.values()]
    need(len(set(roots)) == 4 and not any(a in b.parents for a in roots for b in roots),
         "overlapping source, proof or work roots")
    work.mkdir(); out.mkdir()
    bodies = out / "native-bodies"
    bodies.mkdir()
    proxy = work / "proxies"
    proxy.mkdir()
    installed = Path(shutil.which("rustup")).absolute().parent
    for name in ("rustup", "rustc", "cargo"):
        p = installed / name
        need(p.is_file() and os.access(p, os.X_OK), f"missing real {name} proxy")
        (proxy / name).symlink_to(p)
    outcomes = {k:role(k, sdk, work / k, out / k, proxy, bodies) for k,sdk in sdks.items()}
    first, second = [json.loads((out / k / "fixtures.json").read_bytes()) for k in outcomes]
    need(first == second, "different package inputs between SDKs")
    save(out / "complete.json", {"source": SOURCES, "verified": list(outcomes), "fixtures": first,
                                 "role_receipts": {k:sha(out / k / "complete.json") for k in outcomes}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("candidate", "published", "work", "out"):
        parser.add_argument("--" + argument, required=True, type=Path)
    run(**vars(parser.parse_args()))
