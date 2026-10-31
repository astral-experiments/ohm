"""Recompute CLI and consumer outcomes from captured byte streams, independent of producer helpers."""
import gzip
import json

from replay_metrics import REVS, need, sha


def raw(z, prefix, name):
    name = prefix.rstrip("/") + "/" + name
    data = z.read(name)
    return gzip.decompress(data) if name.endswith(".gz") else data


def read(z, prefix, name):
    return json.loads(raw(z, prefix, name))


def syntax_failure(records):
    return any(str(e.get("code")).lower() == "invalid-syntax" or
               "syntax" in str(e.get("message")).lower() for e in records)


def native_verdict(z, prefix, branch):
    revision = REVS[branch]
    observed = read(z, prefix, "native.json.gz")
    want = 64 if branch == "A" else 56
    need(observed["branch"] == branch and observed["source"] == revision, "source identity")
    consumer = raw(z, prefix, "reader-run.stdout.gz").decode().strip()
    need(consumer == observed["typed"] == f"Expr={want} valid=1 rejected", "typed parser client")
    for width in (64, 56):
        label = f"layout-{width}"
        cmd = read(z, prefix, label + ".json.gz")
        inp = raw(z, prefix, label + ".stderr.gz")
        need(cmd["argv"][:2] == ["rustc", "+ohm"] and cmd["stderr_sha256"] == sha(inp) and
             cmd["exit"] == int(width != want), "contradictory compiler client")
        if width != want:
            need(any((json.loads(line).get("code") or {}).get("code") == "E0308"
                     for line in inp.splitlines()), "failed layout produced different diagnostic")
    tags = {"version": "ruff-version", "source": "ruff-version-json", "clean": "ruff-clean",
            "warning": "ruff-warning", "fixed": "ruff-fix", "recheck": "ruff-recheck",
            "invalid": "ruff-invalid"}
    expected_codes = {"warning": 1, "fixed": 1, "invalid": 1}
    expected_text = b"def enabled(value):\n    if value is None:\n        return 1\n    return 0\n"
    cli = {}
    need(set(observed["cli_cases"]) == set(tags), "incomplete CLI cases")
    for case, tag in tags.items():
        desc = observed["cli_cases"][case]
        stdout = raw(z, prefix, tag + ".stdout")
        stderr = raw(z, prefix, tag + ".stderr")
        need(desc["status"] == expected_codes.get(case, 0) and
             desc["stdout_sha256"] == sha(stdout) and desc["stderr_sha256"] == sha(stderr),
             ("native CLI process", case))
        cli[case] = stdout
    need(b"0.16.7" in cli["version"], "unexpected Ruff version")
    version = json.loads(cli["source"])
    need(version["version"] == "0.16.7" and version["commit_info"]["commit_hash"] == revision and
         version["commit_info"]["short_commit_hash"] == revision[:9], "wrong executable revision")
    warning = json.loads(cli["warning"])
    need(len(warning) == 1 and warning[0]["code"] == "E711" and warning[0]["location"]["row"] == 2
         and warning[0]["fix"] and cli["fixed"] == expected_text and json.loads(cli["clean"]) == []
         and json.loads(cli["recheck"]) == [] and syntax_failure(json.loads(cli["invalid"])),
         "lint/unsafe fix/repair/verdict")
    fstrings = {}
    cases = {"valid": 0, "warning": 1, "fix": 1, "recheck": 0, "invalid": 1, "format": 0}
    need(set(observed["fstring_cases"]) == {"fstring-" + case for case in cases},
         "incomplete formatted-string cases")
    for case, expected in cases.items():
        name = "fstring-" + case
        cmd = read(z, prefix, name + ".json.gz")
        stdout = raw(z, prefix, name + ".stdout.gz")
        stderr = raw(z, prefix, name + ".stderr.gz")
        need(observed["fstring_cases"][name] == [expected, sha(stdout), sha(stderr)] and
             cmd["exit"] == expected and cmd["stdout_sha256"] == sha(stdout) and
             cmd["stderr_sha256"] == sha(stderr), ("formatted-string process", case))
        fstrings[case] = stdout
    warning = json.loads(fstrings["warning"])
    need(json.loads(fstrings["valid"]) == [] and len(warning) == 1 and
         warning[0]["code"] == "F541" and warning[0]["fix"] and
         fstrings["fix"] == b'def label():\n    return "literal"\n' and
         json.loads(fstrings["recheck"]) == [] and syntax_failure(json.loads(fstrings["invalid"])) and
         fstrings["format"] == b'def labels(items):\n    return [f"{n}:{item!r:>4}" for n, item in enumerate(items)]\n',
         "formatted-string runtime verdict")
    for kind in ("cli", "reader"):
        e = observed[kind]
        need(len(e["whole"]) == 64 and e["size"] > 8192 and ".text" in e["executable"]
             and e["loads"] and all(n["filesz"] > 0 and n["flags"] & 1 for n in e["loads"]),
             ("missing native executable segments", kind))
    return observed
