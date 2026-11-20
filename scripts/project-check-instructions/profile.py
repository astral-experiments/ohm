"""Sample user-space instructions for the programs executed at each edit."""
import gzip
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run

def find_perf():
    for path in [shutil.which("perf"), *Path("/usr/lib/linux-tools").glob("*/perf")]:
        if path and subprocess.run([path, "--version"], capture_output=True).returncode == 0:
            return path
    raise RuntimeError("install linux-tools-generic")

PERF = find_perf()
command = run.command

def record(argv, cwd, env, log):
    if log.name != "check.log":
        return command(argv, cwd, env, log)
    data = cwd.parent / "check.data"
    period = "170003"
    command([PERF, "record", "-e", "instructions:u", "-c", period, "-m", "128",
             "-o", data, "--", *argv], cwd, env, log)
    if run.read_counts(log.parent / "units.tsv"):
        samples = subprocess.check_output([PERF, "script", "-i", data, "-F", "pid,comm,sym,dso"], env=env)
        with gzip.open(log.parent / "samples.txt.gz", "wb") as output:
            output.write(samples)
        (log.parent/"period").write_text(period)
    data.unlink()

run.command = record
sys.argv.append("--probe")
run.main()

