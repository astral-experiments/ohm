"""Exercise the checked-in native test through the installed Cargo and a real terminal."""

import gzip
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from qualify import BIND, CHILD, checksum, guard, need, save, verify_live
from release_smoke import identities
from worktree_paths import run

FIXTURE = "aed63f3c04ca7fb3eb4826bc53125d9dc741d23d1a6f75ec66cf4017ad3b50b8"


def interactive(src, env, argv, control, out, test, enabled):
    """Give interactive Bash sole ownership of a fresh PTY before it launches Cargo."""
    transcript = bytearray()
    shell, fd = pty.fork()
    if not shell:
        for sig in (
            signal.SIGINT,
            signal.SIGTERM,
            signal.SIGHUP,
            signal.SIGQUIT,
            signal.SIGTSTP,
            signal.SIGTTIN,
            signal.SIGTTOU,
            signal.SIGCONT,
        ):
            signal.signal(sig, signal.SIG_DFL)
        os.chdir(src)
        os.execve("/bin/bash", ["bash", "--noprofile", "--norc", "-i"], env)
    owned = {shell}
    result = {}
    os.set_blocking(fd, False)

    def until(check):
        deadline = time.monotonic() + 30
        while not check():
            need(time.monotonic() < deadline, "terminal did not reach its expected boundary")
            if select.select([fd], [], [], 0.05)[0]:
                data = os.read(fd, 65536)
                need(data, "shell ended before its verdict")
                transcript.extend(data)

    def ps(pid):
        return subprocess.check_output(
            ["ps", "-ww", "-p", str(pid), "-o", "command="], text=True
        ).strip()

    try:
        until(lambda: b"OHM-READY> " in transcript)
        os.write(fd, (shlex.join(argv) + '; printf "\\nOHM-CARGO=%s\\n" "$?"\n').encode())
        until(lambda: (control / "active").is_file())
        pid, group, child = [
            int((control / n).read_text()) for n in ("active", "test-group", "descendant")
        ]
        need(
            all(os.getsid(p) == shell for p in (pid, group, child))
            and os.getpgid(pid) == group
            and os.getpgid(child) == group,
            "test or descendant outside its terminal job",
        )
        owned.update((pid, group, child))
        actual_test = ps(pid)
        leader = ps(group)
        result.update(
            shell=shell,
            pid=pid,
            group=group,
            child=child,
            test_command=actual_test,
            group_command=leader,
        )
        save(out / "terminal-start.json", result)
        need(
            str(test) in actual_test and ("--ohm-ready-test-relay" in leader.split()) == enabled,
            "different native test or terminal relay mode",
        )
        os.write(fd, b"hello\n")
        status = rb"\nOHM-CARGO=([0-9]+)\r?\n"
        until(lambda: re.search(status, transcript))
        result["status"] = int(re.search(status, transcript)[1])
        need(
            result["status"] == 0
            and b"1 passed; 0 failed" in transcript
            and (control / "input").read_bytes() == b"hello\n"
            and (control / "runs").read_bytes() == b"a\n",
            "wrong shell or actual test verdict",
        )
    finally:
        (out / "terminal.gz").write_bytes(gzip.compress(bytes(transcript), mtime=0))
        for name in ("active", "test-group", "descendant"):
            if (control / name).is_file():
                owned.add(int((control / name).read_text()))
        for pid in sorted(owned, key=lambda pid: pid == shell):
            try:
                if os.getsid(pid) == shell:
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.close(fd)
        os.waitpid(shell, 0)
    return result


def cases(root, out, env, sdk, source, expected, host):
    root.mkdir()
    out.mkdir()
    revision = expected.get("cargo_revision", BIND["trees"]["src/tools/cargo"])
    versions = identities(
        sdk, sdk, sdk / "bin/cargo", expected["rust"], revision, host, env, out / "identity"
    )
    need(
        all(versions[k]["sha256"] == expected[k] for k in ("rustc", "cargo", "driver")),
        "different actual toolchain",
    )
    need(checksum(source) == FIXTURE, "different in-tree ready-test source")
    (body,) = re.findall(r'\.file\(\s*"a/src/lib.rs",\s*r#"(.*?)"#,\s*\)', source.read_text(), re.S)
    src = root / "project"
    (src / "src").mkdir(parents=True)
    (src / "src/lib.rs").write_text(body)
    (src / "Cargo.toml").write_text('[package]\nname="ready_probe"\nversion="0.0.0"\nedition="2021"\n')
    need(
        run(out, "lock", ["cargo", "+ohm", "generate-lockfile", "--offline"], src, env).returncode == 0,
        "lockfile generation failed",
    )
    outcomes = {}
    for name in ("default", "enabled"):
        active = name == "enabled"
        ctl = root / name
        ctl.mkdir()
        folder = out / name
        folder.mkdir()
        e = dict(
            env,
            CARGO_TARGET_DIR=str(root / (name + "-target")),
            CARGO_BUILD_BUILD_DIR=str(root / (name + "-build")),
            READY_CONTROL=str(ctl),
            READY_MODE="terminal",
            PS1="OHM-READY> ",
            TERM="dumb",
            HISTFILE=os.devnull,
            LC_ALL="C",
            CARGO_TERM_COLOR="never",
            CARGO_NET_OFFLINE="true",
        )
        command = (
            ["cargo", "+ohm"]
            + (["-Zohm-defaults=no"] if active else [])
            + ["test"]
            + (["-Zohm-ready-tests"] if active else [])
            + ["--lib", "--locked", "--offline", "-j2"]
        )
        result = run(folder, "prepare", command + ["--no-run", "--message-format=json"], src, e)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        need(
            result.returncode == 0 and rows[-1] == {"reason": "build-finished", "success": True},
            "failed to build the native test",
        )
        (unit,) = [u for u in rows if u.get("executable")]
        exe = Path(unit["executable"])
        need(unit["profile"]["test"] and exe.is_file(), "different test artifact")
        digest = checksum(exe)
        (folder / "native.gz").write_bytes(gzip.compress(exe.read_bytes(), mtime=0))
        inventory = run(folder, "list", [exe, "--list"], src, e)
        need(
            inventory.returncode == 0
            and inventory.stdout.splitlines()[:2] == [b"excluded: test", b"selected: test"],
            "different test inventory",
        )
        ordinary = run(folder, "no-run", command + ["--no-run"], src, e)
        need(
            ordinary.returncode == 0
            and b"Executable unittests" in ordinary.stderr
            and not list(ctl.iterdir()),
            "--no-run ran tests or omitted the executable",
        )
        argv = command + ["--", "--exact", "selected"]
        save(folder / "terminal-argv.json", argv)
        terminal = interactive(src, e, argv, ctl, folder, exe, active)
        rejected = run(folder, "rejected", [exe, "--exact", "excluded"], src, e)
        need(
            rejected.returncode == 101
            and b"the test filter was lost" in rejected.stdout
            and checksum(exe) == digest,
            "alternate test was not discriminating",
        )
        outcomes[name] = dict(native=digest, bytes=exe.stat().st_size, terminal=terminal)
    save(
        out / "complete.json",
        dict(
            host=host,
            source=FIXTURE,
            lib=checksum(src / "src/lib.rs"),
            versions=versions,
            cases=outcomes,
        ),
    )


def main():
    _, repo, reports, tmp, host = guard()
    verify_live(repo)
    link = tmp / "release-link-smoke"
    prior = json.loads((reports / "slot-link-smoke/complete.json").read_bytes())
    need(
        prior["host"] == host and prior["qualified"] and shutil.disk_usage(tmp).free > 4 << 30,
        "missing native source gate",
    )
    out = reports / "slot-ready-terminal"
    out.mkdir()
    completed = {}
    with tempfile.TemporaryDirectory(dir=tmp, prefix="ohm-ready-terminal-") as td:
        base = Path(td).resolve()
        env = dict(
            HOME=str(base),
            TMPDIR=str(base),
            PATH=str(link / "proxies") + os.pathsep + os.environ["PATH"],
            CARGO_HOME=str(base / "registry"),
            RUSTUP_AUTO_INSTALL="0",
        )
        if host.startswith("aarch64-"):
            env["LLVM_PROFILE_FILE"] = str(base / "ready-%m.profraw")
            for key in ("SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET"):
                if key in os.environ:
                    env[key] = os.environ[key]
        for role, sdk, rust, cargo in [
            ("published-22", link / "published-22/sdk", BIND["parent"], BIND["shipped_cargo"]),
            ("rebased", link / "sdk", CHILD, BIND["trees"]["src/tools/cargo"]),
        ]:
            native = prior["results"][role]["versions"]
            expected = {"rust": rust, "cargo_revision": cargo, **{k:native[k]["sha256"] for k in ("rustc", "cargo", "driver")}}
            home = base / ("rustup-" + role)
            (home / "toolchains").mkdir(parents=True)
            (home / "toolchains/ohm").symlink_to(sdk, target_is_directory=True)
            (home / "settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
            cases(base / role, out / role, dict(env, RUSTUP_HOME=str(home)), sdk,
                  repo / "src/tools/cargo/tests/testsuite/ohm_ready_tests.rs", expected, host)
            completed[role] = checksum(out / role / "complete.json")
    save(out / "complete.json", {"host":host,"roles":completed})


if __name__ == "__main__":
    main()
