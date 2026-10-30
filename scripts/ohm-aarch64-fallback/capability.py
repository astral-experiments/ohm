"""Compare emitted Rust compiler arguments and the source-level Cargo/rustc handshake on GNU."""
import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

SIGNED = "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c"
FIXED = "735e1528ed741015c57676dccf05dbdc0ff7bed1"
COMMON = "7277e6cdaba44c43294a07c0661fc8e69fd8e3e7"
TREE = "9cb7035b7adc52ecac48495666b95ba857ed3cdd"
GHREPO = "repos/astral-experiments/"
FULL = {"signed": "","fixed":"9d1323d66e21edb7e695b90aa4bf3a7e2e5cdd362b7c4701fd174dadccc77e3b"}
ROLES = {"N":"P","M":"C"}


def h(b):
    return hashlib.sha256(b).hexdigest()


def call(gh, repo, endpoint):
    return subprocess.check_output([gh, "api", GHREPO + repo + "/" + endpoint])


def blob(gh, rev, file):
    j = json.loads(call(gh, "ohm-cargo", "contents/" + file + "?ref=" + rev))
    raw = base64.b64decode(j["content"])
    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == j["sha"]
    return raw, j["sha"]


def native_args(z, prefix, phase, crate):
    records = json.loads(z.read(prefix + "/" + phase + "/native.json"))["rustcs"]
    matches = [r for r in records if r["crate"] == crate]
    assert len(matches) == 1 and matches[0]["terminal"] == [0]
    return matches[0]["argv"]


def normalize_argv(args):
    cooked = []
    replaced = []
    for i, literal in enumerate(args):
        if "/v2-" in literal:
            v, n = re.subn(r"/v2-[a-f0-9]{16}/", "/<toolchain-namespace>/", literal)
            assert n == 1 and args[i - 1] in {"--out-dir", "--extern", "-L"}, literal
            replaced.append(i)
        else:
            v = literal
        cooked.append(v)
    return cooked, replaced


def main(a):
    receipt = json.loads(a.signed_meta.read_bytes())
    sd = next(j for j in receipt["artifacts"] if j["name"] == "gnu-compact-input-ruff-complete")
    assert sd["digest"] == "sha256:" + h(a.signed.read_bytes())
    fixed = json.loads(call(a.gh, "ohm", "actions/runs/41078144732/artifacts"))
    fr, = [j for j in fixed["artifacts"] if j["name"] == "gnu-ruff-735e1528-native-only"]
    assert fr["workflow_run"]["head_sha"] == "86c6d127b33dd3ef1a3b8e18b23e5a1a59f47779"
    assert fr["digest"] == "sha256:" + FULL["fixed"] and fr["size_in_bytes"] < 96 * 2**20
    wire = call(a.gh, "ohm", f"actions/artifacts/{fr['id']}/zip")
    assert h(wire) == FULL["fixed"] and len(wire) == fr["size_in_bytes"]
    comparisons = {}
    with zipfile.ZipFile(a.signed) as sz, zipfile.ZipFile(io.BytesIO(wire)) as fz:
        for role, alias in ROLES.items():
            for phase, crates in (("old-empty", ("zmij", "compact_str", "ruff_python_ast")),
                                  ("edit", ("ruff_python_ast",))):
                for crate in crates:
                    left = native_args(sz, "mirror1-" + alias, phase, crate)
                    right = native_args(fz, "ruff-native-" + role, phase, crate)
                    l, li = normalize_argv(left)
                    r, ri = normalize_argv(right)
                    diffs = [[i, old, new] for i, (old, new) in enumerate(zip(l, r)) if old != new]
                    comparisons[f"{role}/{phase}/{crate}"] = {
                        "lengths": [len(left), len(right)], "raw_sha256": [h(json.dumps(x,separators=(",",":")).encode()) for x in (left,right)],
                        "namespace_positions": [li, ri], "remaining_diff": diffs,
                        "signed_options": [x for x in left if x.startswith("-Z")],
                        "fixed_options": [x for x in right if x.startswith("-Z")]}
        assert len(comparisons) == 8
        env = json.loads(fz.read("ruff-native-eligibility.json"))["roles"]
        env_keys = {role: env[role]["actual_env"]["ast"]["environment_keys"] for role in ROLES}
    paths = ("src/compiler/mod.rs", "src/compiler/fingerprint/dep_info.rs", "src/compiler/fingerprint/mod.rs")
    sources = {}
    for rev in (SIGNED, FIXED):
        entries = {}
        for path in paths:
            raw, oid = blob(a.gh, rev, path)
            lines = raw.decode().splitlines()
            entries[path] = {"git_blob": oid, "sha256": h(raw),
                             "relevant": [[i, ln.strip()] for i, ln in enumerate(lines,1) if
                                          ('rustc.arg("-Zohm-check-relink-inputs")' in ln or
                                           "fn unit_checks_relink_inputs(" in ln or
                                           "recheck_native_link =" in ln or
                                           "fn native_relinks_use" in ln or
                                           "native_link_driver::" in ln or
                                           "record_native_link_inputs(marked)" in ln or
                                           "fn parse_rustc_dep_info" in ln or
                                           "fn recheck_marker" in ln)]}
        sources[rev] = entries
    ahead = json.loads(call(a.gh, "ohm-cargo", f"compare/{FIXED}...{SIGNED}"))
    assert (ahead["status"],ahead["merge_base_commit"]["sha"],ahead["ahead_by"],ahead["behind_by"]) == ("diverged",COMMON,1,3)
    source = json.loads(call(a.gh, "ohm-cargo", "git/commits/" + FIXED))
    assert source["tree"]["sha"] == TREE
    table = {"compared_argv": comparisons, "fixed_AST_environment_keys": env_keys, "fixed_raw": FULL["fixed"],
             "signed_raw": sd["digest"][7:], "sources": sources, "Cargo_common_base": COMMON}
    wire = (json.dumps(table, indent=2,sort_keys=True)+"\n").encode()
    if a.output.exists():
        assert a.output.read_bytes() == wire
    else:
        a.output.open("xb").write(wire)
    for name, record in comparisons.items():
        print(name, record["lengths"], record["remaining_diff"], "duplicated_only_namespace", record["namespace_positions"][0]==record["namespace_positions"][1])
    print(h(wire), len(wire))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("gh")
    p.add_argument("signed", type=Path)
    p.add_argument("signed_meta", type=Path)
    p.add_argument("output", type=Path)
    main(p.parse_args())
