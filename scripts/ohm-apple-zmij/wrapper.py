#!/usr/bin/env python3
"""Diagnostic only. Verify the selected compiler, forward literal arguments/FDs, and record the real child exit."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study import need, sha


def compiler_selector(argument, physical):
    given = Path(shutil.which(argument) or argument)
    if given.samefile(physical):
        return {"kind": "direct"}
    # Cargo may hand its wrapper the bare rustc rustup proxy. Resolve the actual
    # active toolchain in this Cargo child (including its cwd and environment).
    rustup = shutil.which("rustup")
    need(
        given.name == "rustc" and rustup
        and (given.samefile(rustup) or sha(given) == sha(rustup)),
        "Cargo passed a different rustc to the diagnostic wrapper",
    )
    selected = subprocess.check_output([rustup, "which", "rustc"], timeout=15).decode().strip()
    need(Path(selected).samefile(physical), "rustup selected a different compiler")
    return {"kind": "rustup", "proxy": str(given), "selected": selected}


def forward():
    physical = Path(os.environ["QA_APPLE_REAL_RUSTC"])
    argv = sys.argv[1:]
    selector = compiler_selector(argv[0], physical)
    before = physical.stat()
    # close_fds=False preserves the actual inherited Cargo jobserver. Popen's CLOEXEC
    # handshake raises rather than reporting a successful child if execv fails.
    p = subprocess.Popen(argv, executable=str(physical), close_fds=False)
    code = p.wait()
    after = physical.stat()
    need(
        (before.st_dev, before.st_ino, before.st_size) == (after.st_dev, after.st_ino, after.st_size),
        "compiler replaced",
    )
    evidence = Path(os.environ["QA_APPLE_CALLS"]) / (str(os.getpid()) + ".json")
    evidence.write_text(
        json.dumps(
            {
                "path": str(physical),
                "argv": argv,
                "pid": p.pid,
                "ppid": os.getpid(),
                "physical": [before.st_dev, before.st_ino, before.st_size],
                "selector": selector,
                "exit": code,
            }
        )
    )
    if code < 0:
        os.kill(os.getpid(), -code)
    sys.exit(code)


class WrapperTrace:
    kind = "compiler-wrapper-unscored"

    def ready(self):
        pass

    def close(self):
        pass

    def command(self, argv, *, env, cwd, out, err, timeout=600):
        with tempfile.TemporaryDirectory() as directory:
            # Version/host checks from sdk_id already established this exact SDK.
            source = Path(env["RUSTUP_HOME"]) / "toolchains/ohm/bin/rustc"
            env = dict(env, QA_APPLE_CALLS=directory, QA_APPLE_REAL_RUSTC=str(source.resolve()))
            if argv[:2] == ["cargo", "+ohm"]:
                # A hosted PATH can contain another rustc shim. Only this diagnostic
                # invocation names the SDK binary explicitly; ordinary Cargo runs keep their environment.
                env["RUSTC"] = str(source.resolve(strict=True))
                env["RUSTC_WRAPPER"] = str(Path(__file__).resolve())
                cmd = argv
            else:
                need(argv[:2] == ["rustc", "+ohm"], "unexpected diagnostic command")
                cmd = [str(Path(__file__).resolve()), str(source.resolve()), *argv[2:]]
            code = subprocess.run(cmd, env=env, cwd=cwd, stdout=out, stderr=err, timeout=timeout).returncode
            rows = [json.loads(p.read_bytes()) for p in sorted(Path(directory).glob("*.json"))]
            return code, [{"scope": self.kind, "selected_rustc": str(source.resolve(strict=True))}, *rows]


if __name__ == "__main__":
    forward()
