"""Execute only the complete, checksum-bound Ruff ELF in a sealed anonymous file on GNU x86-64."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

import cases as s


def replay(archive, native, revision, edited):
    desc = native["cli"]
    s.need(
        platform.system() == "Linux" and platform.machine() == "x86_64" and 8192 < desc["size"] < 256 * 2**20,
        "native GNU x86-64 intake required",
    )
    with os.fdopen(os.memfd_create("qa-historical-ruff", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING), "r+b") as f:
        h = desc["whole"]
        with archive.open("native-bodies/" + h + ".zst") as compressed:
            proc = subprocess.Popen(["zstd", "-dq", "--stdout"], stdin=subprocess.PIPE, stdout=f)
            with proc.stdin as pipe:
                shutil.copyfileobj(compressed, pipe, 1 << 20)
            s.need(proc.wait() == 0 and f.tell() == desc["size"], "incomplete retained CLI")
        os.fchmod(f.fileno(), 0o500)
        # UAPI linux/fcntl.h; some otherwise compatible Python distributions omit these names.
        mask = 0x0008 | 0x0004 | 0x0002 | 0x0001
        fcntl.fcntl(f, getattr(fcntl, "F_ADD_SEALS", 1033), mask)
        f.seek(0)
        s.need(
            fcntl.fcntl(f, getattr(fcntl, "F_GET_SEALS", 1034)) == mask
            and hashlib.file_digest(f, "sha256").hexdigest() == h,
            "wrong retained whole CLI",
        )
        exe = f"/proc/self/fd/{f.fileno()}"
        with tempfile.TemporaryDirectory(prefix="ctfe-stub-native-") as directory:
            cwd = Path(directory).resolve()
            env = {"HOME": str(cwd), "PATH": "/usr/bin:/bin", "LC_ALL": "C", "RAYON_NUM_THREADS": "2"}

            def run(args, stdin=b""):
                return subprocess.run(
                    [exe, *args],
                    input=stdin,
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    pass_fds=(f.fileno(),),
                    timeout=30,
                )

            v = run(["version", "--output-format", "json"])
            s.need(
                v.returncode == 0
                and not v.stderr
                and json.loads(v.stdout)["commit_info"]["commit_hash"] == revision,
                "retained native program has different revision",
            )
            outcomes = {}
            for case in s.CASES:
                cmd = run(s.argv(case), s.SOURCE)
                s.verdict(case, edited, cmd.returncode, cmd.stdout, cmd.stderr, cwd)
                outcomes[case] = cmd.returncode
            return outcomes
