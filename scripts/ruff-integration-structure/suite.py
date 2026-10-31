"""Validate the native Linux libtest and the Cargo-selected development-feature CLI."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
LIST_SHA = "1cbc0fb0d7cc1767f905f1a34d953e98af8a3e6edc887a410bf26f25658be039"
TEST_SHA = "f68c78f3031ac48bb4558ac8bda894490ba3c79ddcd9e88c33ae1b34b0ab0edb"
EXACT = ("check_input_from_argfile", "missing_argfile_reports_error")


def require(value, reason):
    if not value:
        raise ValueError(str(reason))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data):
    with path.open("x") as out:
        json.dump(data, out, sort_keys=True, separators=(",", ":"))
        out.write("\n")


def inventory(body):
    require(sha(body) == LIST_SHA and body == (HERE / "expected-tests.txt").read_bytes(), "Linux libtest inventory")
    names = [s.removesuffix(": test") for s in body.decode().splitlines() if s.endswith(": test")]
    require(len(set(names)) == len(names) == 96, "missing or duplicate test")
    return names


def verdict(body, names, filtered=0):
    text = body.decode()
    rows = re.findall(r"^test ([^ ]+) \.\.\. ([^\n]+)$", text, re.M)
    require(sorted(rows) == sorted((name, "ok") for name in names), ("reported libtest cases", rows))
    summaries = re.findall(r"^test result: (.+)$", text, re.M)
    need = rf"ok\. {len(names)} passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in [0-9.]+s"
    require(len(summaries) == 1 and re.fullmatch(need, summaries[0]), ("libtest terminal", summaries))


def command(argv, cwd, env, where, label):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=360)
    for name, data in (("stdout", result.stdout), ("stderr", result.stderr)):
        (where / f"{label}.{name}.gz").write_bytes(gzip.compress(data, mtime=0))
    write(where / f"{label}.json", dict(argv=list(map(str, argv)), cwd=str(cwd), exit=result.returncode,
          stdout=sha(result.stdout), stderr=sha(result.stderr), cargo_bin=env.get("CARGO_BIN_EXE_ruff"), insta_root=env.get("INSTA_WORKSPACE_ROOT")))
    require(result.returncode == 0, (label, result.returncode, result.stdout[-3500:], result.stderr[-1000:]))
    return result


def permission_prefix(where):
    prefix = (["setpriv", "--bounding-set=-dac_override,-dac_read_search", "--inh-caps=-all",
               "--ambient-caps=-all", "--no-new-privs", "--"] if os.getuid() == 0 else [])
    with tempfile.TemporaryDirectory(dir=where) as tmp:
        root = Path(tmp)
        file, directory = root / "file", root / "dir"
        file.write_text("private")
        file.chmod(0)
        directory.mkdir(mode=0)
        try:
            probe = """import errno, os, sys
for path, op in [(sys.argv[1], lambda p: open(p, 'rb').close()), (sys.argv[2], os.listdir)]:
    try: op(path)
    except OSError as e:
        if e.errno != errno.EACCES: raise
    else: raise RuntimeError('permission-negative test cannot exercise EACCES')
print(os.getuid(), 'file EACCES', 'directory EACCES')
"""
            command([*prefix, sys.executable, "-IB", "-c", probe, file, directory], root, os.environ,
                    where, "eacces")
        finally:
            directory.chmod(0o700)
            file.chmod(0o600)
    return prefix


def check_children(events, harness, cli, case):
    require(len(events) == 2, ("unexpected external tool, fallback Cargo or extra child", events))
    (hp, he, ha), (cp, ce, ca) = events
    require(hp != cp and Path(he) == harness and Path(he).samefile(harness) and
            ha[1:] == ["--exact", case, "--test-threads=1", "--color", "never"], "wrong real libtest")
    arg = "@!.txt" if case == EXACT[1] else None
    require(Path(ce) == cli and Path(ce).samefile(cli) and ca[1] == "check" and
            "--isolated" in ca and "--no-cache" in ca and
            any(v == arg if arg else v.startswith("@/") and v.endswith("/file_paths.txt") for v in ca),
            ("wrong real Ruff BIN or argfile operand", ce, ca))
    return {"harness_pid": hp, "ruff_pid": cp, "ruff_path": ce, "argv": ca}


def exercise(harness, cli, root, env, where, prefix, processes):
    package = root / "crates/ruff"
    require(sha((package / "tests/integration_test.rs").read_bytes()) == TEST_SHA, "wrong test source")
    env = env | {"CARGO_BIN_EXE_ruff": str(cli), "INSTA_UPDATE": "no", "INSTA_WORKSPACE_ROOT": str(root)}
    def run(args, name):
        return command([*prefix, *args], package, env, where, name)
    listed = run([harness, "--list", "--format", "pretty"], "libtest-list")
    names = inventory(listed.stdout)
    full = run([harness, "--test-threads=1", "--color", "never"], "libtest-full")
    verdict(full.stdout, names)
    rule = run([cli, "rule", "RUF950"], "dev-rule")
    require(b"ruf950" in rule.stdout.lower(), "Ruff development rules absent")
    observed = {}
    for case in EXACT:
        raw = where / (case + ".exec")
        args = ["strace","-f","-qq","--seccomp-bpf","-s","262144","-e","trace=execve,execveat",
                "-o",raw,harness,"--exact",case,"--test-threads=1","--color","never"]
        try:
            sample = run(args, case)
            verdict(sample.stdout, [case], 95)
            with raw.open() as events:
                observed[case] = check_children(processes.execs(events), harness, cli, case)
        finally:
            if raw.exists():
                processes.compact(raw, where / (case + ".exec.gz"))
    write(where / "libtest.json", dict(inventory=sha(listed.stdout), total=96, passed=96,
          children=observed, rule=sha(rule.stdout), package=str(package)))
    return {"inventory": sha(listed.stdout), "names": sorted(names), "dev_rule": sha(rule.stdout)}
