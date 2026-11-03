"""Prove the published file list works with neither network nor access to the study tree."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="fresh-uv22958-evidence-") as tmp:
    checkout = Path(tmp)
    names = [line.split("  ", 1)[1] for line in (root/"SHA256SUMS").read_text().splitlines()] + ["SHA256SUMS"]
    for name in names:
        target = checkout/name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(root/name, target)
        except OSError:
            shutil.copyfile(root/name,target)
    env = {"PATH": "/usr/bin:/bin", "TMPDIR": str(checkout), "LC_ALL": "C"}
    subprocess.run(["sha256sum", "--strict", "--quiet", "-c", "SHA256SUMS"], cwd=checkout, env=env, check=True)
    # The actual interpreter sees only the portable test checkout and its standard library.
    # zstd is the single allowed subprocess and consumes local input and local output.
    audit = """import sys, runpy, pathlib
p=pathlib.Path.cwd()
stdlib=pathlib.Path(sys.base_prefix).resolve()
def restrict(event, args):
    if event.startswith('socket.'):
        raise PermissionError(event)
    if event=='subprocess.Popen' and args[0] != 'zstd':
        raise PermissionError(args[0])
    if event=='open' and isinstance(args[0], str):
        f=pathlib.Path(args[0]).resolve()
        if not (f.is_relative_to(p) or f.is_relative_to('/usr') or f.is_relative_to(stdlib) or f==pathlib.Path('/dev/null')):
            raise PermissionError(str(f))
sys.addaudithook(restrict)
sys.argv=sys.argv[1:]
runpy.run_path(str(p / sys.argv[0]),run_name='__main__')
"""
    command = [sys.executable, "-ISB", "-c", audit, "replay.py", "--controls", *sys.argv[1:]]
    result = subprocess.run(command, cwd=checkout, env=env, text=True, capture_output=True)
    print(result.stdout, end="")
    print(result.stderr, end="")
    result.check_returncode()
    mech = subprocess.run([sys.executable, "-ISB", "-c", audit, "mechanism/replay.py"],
                          env=env, cwd=checkout, text=True, capture_output=True, check=True)
    assert mech.stdout == (checkout/"mechanism/result.json").read_text()
    for role, r in json.loads(mech.stdout).items():
        print(f"{role} PID {r['pid']}: {r['provider_calls']} typeck_root calls and {r['guest_instructions']} total guest instructions")
