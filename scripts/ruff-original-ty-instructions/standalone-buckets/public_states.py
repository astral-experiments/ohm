"""Reopen the identities and public fingerprint transitions of the two real producer interfaces."""
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
from scope_rdr import decode

schema_path = here.parent / "source-pcs/verified-29697/metadata-schema.json.gz"
schema = schema_path.read_bytes()
assert hashlib.sha256(schema).hexdigest() == "236f4a0f399c405ddde4b5112d5b75983916b6ce5a3ee8056274c2dcc9047c5e"
schema = json.loads(gzip.decompress(schema))
version = "rustc 1.99.0-dev (Ohm metadata 3)"
tables = ("definition_identities", "public_definition_hashes", "expansions", "required_crates")


def changes(before, after):
    return (set(after) - set(before), set(before) - set(after),
            {key for key in before.keys() & after.keys() if before[key] != after[key]})


def digest_keys(group):
    data = json.dumps(sorted(group), separators=(",", ":")).encode()
    return {"count": len(group), "key_set_sha256": hashlib.sha256(data).hexdigest()}


def inspect(archive):
    observed = {}
    for role in "PC":
        for stage in ("old", "edit", "independent-clean"):
            info = json.loads(archive.read(f"{role}/{stage}/native.json"))
            for crate in ("ty_project", "ty_ide"):
                blob, = info["outputs"][crate]["metadata"]
                assert 0 < blob["bytes"] < 16 * 2**20
                raw = subprocess.run(["zstd", "-qdc"], input=archive.read("native/" + blob["sha256"] + ".zst"), capture_output=True, check=True).stdout
                assert len(raw) == blob["bytes"] and hashlib.sha256(raw).hexdigest() == blob["sha256"]
                observed[role, stage, crate] = decode(raw, schema["symbols"], schema["tables"], crate, version)
    absolute = {}
    transitions = {}
    equivalent = True
    for crate in ("ty_project", "ty_ide"):
        for stage in ("old", "edit", "independent-clean"):
            p, c = (observed[role, stage, crate] for role in "PC")
            deltas = {tag: [digest_keys(s) for s in changes(a,b)] for tag,a,b in zip(tables,p[1:],c[1:])}
            absolute[crate + "/" + stage] = {"headers": [p[0], c[0]], "differing_rows": deltas}
            equivalent &= p[1] == c[1]
        for start, end in (("old","edit"),("edit","independent-clean")):
            key = f"{crate}/{start}-to-{end}"
            result = {}
            for which, name in enumerate(tables, 1):
                p,c = (changes(observed[role,start,crate][which],observed[role,end,crate][which]) for role in "PC")
                result[name] = {"P": [digest_keys(g) for g in p], "C": [digest_keys(g) for g in c],
                                "different_keys": [sorted(x ^ y) for x,y in zip(p,c)]}
                if start == "old":
                    equivalent &= p == c
            transitions[key] = result
    return {"version": version, "tables": list(tables), "cross_role_absolute": absolute,
            "within_role_transitions": transitions, "equal_stable_identities_and_edit_key_sets": equivalent}
