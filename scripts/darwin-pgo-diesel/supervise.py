"""Run the unaltered release entrypoint and stop only after its completed Rust PGO section."""

import os
from pathlib import Path
import re
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from identity import BENCHES, HERE, HOST, SECTION, need, trace, write

OK = re.compile(
    r"^\[[^\]\n]+ (?:INFO\s+)opt_dist::timer\] Section "
    + re.escape(chr(96) + SECTION + chr(96))
    + r" ended: OK \([0-9.]+s\)"
    + re.escape(chr(96))
    + r"$"
)


def finished(log):
    parsed = trace(log)
    rows = re.findall(r"^Finished benchmark ([^ ]+) \(([1-9])/9\)$", log, re.MULTILINE)
    need(
        len(rows) == 9
        and {v[0] for v in rows} == set(BENCHES.split(","))
        and {int(v[1]) for v in rows} == set(range(1, 10)),
        "incomplete original cross-benchmark roster",
    )
    need(
        "collector error:" not in log and len([l for l in log.splitlines() if OK.fullmatch(l)]) == 1,
        "positive cutpoint missing or contradictory",
    )
    return parsed


def run_child(cmd, w, report):
    report.mkdir()
    log = report / "original-opt-dist.log"
    write(
        report / "entry.json",
        {
            "argv": cmd,
            "cwd": str(w),
            "scope": "one unchanged original release entrypoint through the complete rustc profile group",
        },
    )
    p = subprocess.Popen(cmd, cwd=w, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    cut = False
    try:
        with log.open("xb") as out:
            for line in iter(p.stdout.readline, b""):
                sys.stdout.buffer.write(line)
                sys.stdout.flush()
                out.write(line)
                if not cut and OK.fullmatch(line.decode(errors="replace").rstrip("\r\n")):
                    out.flush()
                    try:
                        finished(log.read_text(errors="replace"))
                    except ValueError as error:
                        (report / "unaccepted-checkpoint.txt").write_text(str(error) + "\n")
                        continue
                    cut = True
                    os.killpg(p.pid, signal.SIGTERM)
            code = p.wait(timeout=120)
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
    write(report / "primary.json", {"code": code, "stopped_after_completed_rustc_profiles": cut})
    need(cut or code != 0, "optimized distribution ended with no recognized rustc stop")
    return 0 if cut else code or 1


def main():
    w = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    report = w / "source/reports/diesel-pgo"
    cmd = [
        str(w / "scripts/build-optimized-dist.sh"),
        HOST,
        "ohm-1.99.0-22",
        str(w / "source/rust"),
        str(w / "release/bootstrap.toml"),
    ]
    return run_child(cmd, w, report)


if __name__ == "__main__":
    raise SystemExit(main())
