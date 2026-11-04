"""Join the complete, independently executed single-target ELF to the refused workspace oracle."""

import gzip
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

PRIOR = (7294914, "6dcff8bf78023a304b67be31f2156b8c853e3a332f0d66434bcd9daf8ee8d3a0")
WORKSPACE = (
    41514240,
    "b793f66dcaa3d935abca0fc2d5d9fd6de9737da7c3e3c1b05836581ffe481c7f",
)
ROLE = "/ty_server/f5c6198f896cf7b0/out/e2e-f5c6198f896cf7b0"


def authenticate(path, expected):
    with path.open("rb") as f:
        assert (
            path.stat().st_size,
            hashlib.file_digest(f, "sha256").hexdigest(),
        ) == expected
    return ZipFile(path)


def read(z, name):
    data = z.read(name)
    return gzip.decompress(data) if name.endswith(".gz") else data


def json_member(z, name):
    return json.loads(read(z, name))


def physical(z, prefix, actor):
    inv = json_member(z, prefix + "/inventory.json.gz")
    elf = inv["executables"][inv["binary"]]["elf"]
    assert inv["binary"].endswith(ROLE)
    raw = read(z, actor)
    records = [line.split("\t") for line in raw.decode().splitlines()]
    (emitted,) = [r for r in records if r[0] == "EMITTED"]
    assert emitted[-1].endswith("/" + inv["binary"]) and int(emitted[3]) == elf["bytes"]
    assert ["VERIFIED"] in records and not any(
        r[0] in ("FRESH-PUBLISH", "ACCEPT") for r in records
    )
    inputs = {}
    for suffix in ("symbols.o", "raw-dylibs/libutil.a"):
        (frozen,) = [
            r for r in records if r[0] == "FROZEN" and r[-1].endswith("/" + suffix)
        ]
        (consumed,) = [r for r in records if r[0] == "USED" and r[-1] == frozen[-1]]
        assert [frozen[3], frozen[4]] == consumed[2:4]
        inputs[suffix] = [int(frozen[3]), frozen[4]]
    return {
        "bytes": elf["bytes"],
        "sha256": elf["sha256"],
        "blake3": emitted[4],
        "native_buffers": inputs,
    }


if __name__ == "__main__":
    prior_path, workspace_path = map(Path, sys.argv[1:])
    with authenticate(prior_path, PRIOR) as prior, authenticate(
        workspace_path, WORKSPACE
    ) as workspace:
        row = json_member(prior, "four-complete.json")
        complete = json_member(prior, "complete.json")
        assert complete["four"] == row
        runner = json_member(prior, "registration.json")
        assert (
            runner["run"] == "41723091119"
            and runner["head"] == "575582bd4f55f4410720e31ef04261b8238b8042"
        )
        assert row["exit"] == 83 and row["successful"]
        new_name = "C-native-four"
        new_mutation = json_member(workspace, new_name + "-actual-change.json")
        assert (
            new_mutation == row["mutation"]
            and len(new_mutation["changed_offsets"]) == 4
        )
        assert json_member(workspace, "admission.json")["run"] == "41737649726"
        new_decision = json_member(workspace, new_name + "/physical-decisions.json")[
            "actors"
        ][ROLE]
        assert (
            new_decision["action"] == "full-typed-refusal"
            and new_decision["response"] == "full"
        )
        old = physical(prior, "four", "four/link-actor.tsv.gz")
        new = physical(
            workspace, new_name, new_name + "/actor-" + new_decision["pid"] + ".tsv.gz"
        )
        assert (
            old == new
            and row["sha256"] == old["sha256"]
            and row["emitted"][3] == old["blake3"]
        )
        assert old["bytes"] == 227979400
        assert new_name + "-verdict.json" not in workspace.namelist()
        print(
            json.dumps(
                {
                    "scope": "Independent actual signed -23 single-target execution of the same complete ELF",
                    "prior": {
                        "run": 41723091119,
                        "artifact": 13275840782,
                        "zip": PRIOR,
                        "head": runner["head"],
                        "observed_exit": row["exit"],
                        "actual_argv_suffix": "--list",
                    },
                    "workspace": {
                        "run": 41737649726,
                        "artifact": 13279449314,
                        "zip": WORKSPACE,
                        "own_runtime_completed": False,
                    },
                    "same_physical_inputs_and_native_output": old,
                    "mutation": new_mutation,
                },
                indent=2,
                sort_keys=True,
            )
        )
