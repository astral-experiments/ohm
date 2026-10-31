"""Remove only the run-owned Ruff subtree of a newly claimed native scratch directory."""
import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import uuid


def check(value, why):
    if not value:
        raise ValueError(why)


def handle(operation, path, expected, nonce, parent, run, attempt):
    name = path.name
    check(parent.is_absolute() and parent.resolve(strict=True) == parent and path.parent == parent and
          re.fullmatch(rf"ohm-rc22-recovery-{int(run)}-{int(attempt)}-[a-zA-Z0-9]{{8}}", name),
          "unregistered scratch directory")
    check(str(uuid.UUID(nonce)) == nonce, "invalid scratch nonce")
    outer_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=outer_fd)
        try:
            st = os.fstat(fd)
            check(st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700, "wrong scratch owner or mode")
            ident = f"{st.st_dev}:{st.st_ino}"
            marker = ".rc22-regression-owned"
            if operation == "claim":
                check(not expected and not os.listdir(fd), "scratch is not initially empty")
                f = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                with os.fdopen(f, "w") as file:
                    file.write(nonce)
                return ident
            check(expected == ident and set(os.listdir(fd)) <= {marker, "rc22-regression"}, "scratch identity or entries changed")
            f = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(f) as file:
                check(file.read() == nonce, "scratch nonce changed")
            # This host is exclusive and no user compiler remains. Refuse even
            # a same-device bind before removing any task-owned build products.
            entries = Path("/proc/self/mountinfo").read_text().splitlines()
            check(not any(row.split()[4] == str(path) or row.split()[4].startswith(str(path) + "/") for row in entries),
                  "unexpected mount under native scratch")
            if "rc22-regression" in os.listdir(fd):
                check(shutil.rmtree.avoids_symlink_attacks and stat.S_ISDIR(os.stat(
                    "rc22-regression", dir_fd=fd, follow_symlinks=False).st_mode), "worker root is not its ordinary directory")
                shutil.rmtree("rc22-regression", dir_fd=fd)
            os.unlink(marker, dir_fd=fd)
            check(not os.listdir(fd), "scratch still has entries")
            return ident
        finally:
            os.close(fd)
    finally:
        os.close(outer_fd)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("claim", "drop"))
    p.add_argument("path", type=Path)
    p.add_argument("identity")
    p.add_argument("nonce")
    args = p.parse_args()
    print(handle(args.operation, args.path, args.identity, args.nonce, Path("/cache"),
                 os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]))
