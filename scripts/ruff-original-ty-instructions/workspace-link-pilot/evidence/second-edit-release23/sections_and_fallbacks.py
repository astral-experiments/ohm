"""Reopen whole SHA, section contents, and Wild's actual fallback at every refused native role."""

import gzip, hashlib, json, re, sys
from pathlib import Path
from zipfile import ZipFile


def reopen(p, expected):
    with p.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected
    with ZipFile(p) as z:
        names = set(z.namelist())

        def raw(n):
            v = z.read(n)
            return gzip.decompress(v) if n.endswith(".gz") else v

        def j(n):
            return json.loads(raw(n))

        verified = j("complete.json")
        seen = j("all-signed-native-differences.json.gz")
        assert not verified["qualified"] and verified["failures"]
        patches = {}
        prior = {}
        for role in sorted({s for v in verified["failures"].values() for s in v}):
            rows = {}
            for cur in sorted(
                x.split("/")[0]
                for x in names
                if x.endswith("/inventory.json.gz")
                and (
                    x.startswith("P-")
                    or any(x.startswith(tag + "/") for tag in verified["failures"])
                )
            ):
                inv = j(cur + "/inventory.json.gz")
                assert len(inv["executables"]) == 102
                [(path, which)] = [
                    (k, v) for k, v in inv["executables"].items() if k.endswith(role)
                ]
                part = which["elf"]
                h = part["sha256"]
                assert (
                    re.fullmatch("[a-f0-9]{64}", h)
                    and j(cur + "-receipt.json.gz")["published"][role] == h
                )
                rows[cur] = (part, inv["state"], which["unit"])
            reference = rows["P-empty-new"][0]
            for cur, failed in verified["failures"].items():
                if role not in failed:
                    continue
                body, rev, unit = rows[cur]
                k = role
                assert rows["P-empty-new"][1:] == (rev, unit) and seen[cur][role] == [
                    body["sha256"],
                    reference["sha256"],
                ]
                old = reference["sections"]
                new = body["sections"]
                assert [s[0] for s in old] == [s[0] for s in new]
                differences = [
                    {"section": b[0], "signed": a, "actual": b}
                    for a, b in zip(old, new, strict=True)
                    if a != b
                ]
                r = j(cur + "/physical-decisions.json")["actors"][role]
                log = raw(cur + "/actor-" + r["pid"] + ".tsv.gz").decode().splitlines()

                def records(key):
                    return [a.split("\t")[1:] for a in log if a.startswith(key + "\t")]

                [declared] = records("TYPED")
                actual = records("ACTUAL-GROUP")
                projected = records("PROJECTED-GROUP")
                assert (
                    actual == projected
                    and actual
                    and r["action"] == "full-typed-refusal"
                    and not r["allowed"]
                )
                assert r["response"] == "full" and len(records("EMITTED")) == 1
                assert not records("FRESH-PUBLISH") and not records("ACCEPT")
                equal = [
                    t
                    for t, (v, state, other) in rows.items()
                    if t.startswith("P-")
                    and state == rev
                    and v["sha256"] == body["sha256"]
                    and other == unit
                ]
                patches.setdefault(cur, {})[role] = {
                    "state": rev,
                    "unit": unit,
                    "strict_reference": "P-empty-new",
                    "current_size": body["bytes"],
                    "reference_size": reference["bytes"],
                    "current_sha256": body["sha256"],
                    "reference_sha256": reference["sha256"],
                    "matching_signed_full_sha_same_state": equal,
                    "native_role": role,
                    "fallback": r["action"],
                    "response": r["response"],
                    "reasons": r["reasons"],
                    "observed_threads": int(declared[4]),
                    "projected_actual_group": actual,
                    "differing_recorded_sections": differences,
                    "equal_section_count": len(new) - len(differences),
                    "raw_stream_sha256": hashlib.sha256(
                        raw(cur + "/actor-" + r["pid"] + ".tsv.gz")
                    ).hexdigest(),
                }
        return {
            "original_sha256": expected,
            "qa_head": j("admission.json")["head"],
            "run": j("admission.json")["run"],
            "qualified": False,
            "scope": "The complete original ELF SHA and each native section tuple are bound. Native ELF bodies, padding, and every section-header field were not archived. No masking or changed reference is used.",
            "refusals": patches,
        }


if __name__ == "__main__":
    print(json.dumps(reopen(Path(sys.argv[1]), sys.argv[2]), indent=2, sort_keys=True))
