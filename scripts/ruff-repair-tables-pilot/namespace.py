"""Run only the two unscored observed Cargo commands and the known-allocation fixture as isolated PID 1."""

import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
from protocol import need


def outer():
    return os.readlink("/proc/self/ns/pid")


def launch(command, cwd, env, writable, privileged):
    bwrap = shutil.which("bwrap")
    need(bwrap and os.getuid() != 0, "expected a nonroot native worker with bubblewrap")
    args = (["sudo", "-n"] if privileged else []) + [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--as-pid-1",
    ]
    if privileged:
        args += ["--uid", str(os.getuid()), "--gid", str(os.getgid())]
    args += ["--cap-drop", "ALL", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    for path in writable:
        path = Path(path)
        need(
            path.is_dir() and path.resolve() == path and path not in (Path("/"), Path.home()),
            "unsafe namespace writable root",
        )
        args += ["--bind", str(path), str(path)]
    args += ["--chdir", str(cwd), "--clearenv"]
    for key, val in env.items():
        args += ["--setenv", key, val]
    # The kernel no-new-privileges bit is inherited by every child, including the measured-family binaries.
    return args + ["--", "/usr/bin/setpriv", "--no-new-privs", "--", *map(str, command)]


def qualify(where, env):
    here = Path(__file__).resolve().parent
    outside = outer()
    for privileged in (False, True):
        probe = sp.run(
            launch(
                [
                    "/usr/bin/python3",
                    "-ISB",
                    "-c",
                    "import os,pathlib,sys; s=pathlib.Path('/proc/self/status').read_text();"
                    "assert os.getpid()==1 and os.getuid()==int(sys.argv[1])!=0 and os.readlink('/proc/self/ns/pid')!=sys.argv[2];"
                    "assert int([l.split()[1] for l in s.splitlines() if l.startswith('CapEff:')][0],16)==0 and 'NoNewPrivs:\\t1' in s",
                    str(os.getuid()),
                    outside,
                ],
                where,
                env,
                [where],
                privileged,
            ),
            capture_output=True,
        )
        (where / ("entry-root-drop" if privileged else "entry-unprivileged")).write_text(
            json.dumps(
                {"rc": probe.returncode, "stdout": probe.stdout.decode(), "stderr": probe.stderr.decode()}
            )
            + "\n"
        )
        if probe.returncode == 0:
            break
    else:
        (where / "refused.json").write_text(
            json.dumps(
                {
                    "status": "inconclusive",
                    "reason": "neither nonroot nor privilege-dropping PID namespace was admitted",
                }
            )
            + "\n"
        )
        return None
    fixture = where / "calibration"
    fixture.mkdir()
    small = env | {"SCOPED_WORK": str(fixture), "OBSERVATION_OUTER_PIDNS": outside}
    p = sp.run(
        launch(["/usr/bin/python3", "-ISB", here / "peak_fixture.py"], fixture, small, [fixture], privileged),
        capture_output=True,
    )
    (where / "fixture.stdout").write_bytes(p.stdout)
    (where / "fixture.stderr").write_bytes(p.stderr)
    need(
        p.returncode == 0 and (fixture / "report.json").is_file(),
        "physical observed-memory/storage calibration failed",
    )
    # Remove only the two calibrated file trees. Keep complete original raw snapshots and their report.
    for key in ("target", "build"):
        shutil.rmtree(fixture / key)
    return privileged


def command(cargo, worker, env, where, privileged):
    b = worker.b
    tmp = Path(env["TMPDIR"])
    need(
        tmp.parent == b.ROOT and b.WORK.parent == b.ROOT and where.is_relative_to(b.OUT),
        "wrong owned native scratch",
    )
    args = [
        "/usr/bin/python3",
        "-ISB",
        Path(__file__).resolve().parent / "peak.py",
        "--root",
        b.WORK / "target",
        "--root",
        b.WORK / "build",
        "--outside",
        outer(),
        "--result",
        where / "peak.json.gz",
        "--",
        *cargo,
    ]
    # Cargo retains its private locks and last-use bookkeeping. Acquisition and final readback hash every archive.
    return launch(args, worker.kit.TREE, env, [b.WORK, where, tmp, b.HOME / ".cargo"], privileged)[:]
