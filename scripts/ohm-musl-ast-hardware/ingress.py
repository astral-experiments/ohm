"""Authenticate the paired physical SDK and both independent source-run structural outputs."""

import io
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from clocked import CMD, assignment, file_sha, require, save, sha
from products import product
import qualification

FROZEN = json.loads((HERE / "subjects.json").read_bytes())
SOURCE_RUN, SOURCE_HEAD = FROZEN["source_run"], FROZEN["source_head"]
PROVIDER_RUN, PROVIDER_HEAD = FROZEN["provider_run"], FROZEN["provider_head"]
REPO = "astral-experiments/ohm"
BRANCH = "charlie/qa-x86-musl-ast-hardware"
API = f"repos/{REPO}/actions/"


def admitted(here, phase):
    q = json.loads((here / "subjects.json").read_bytes())
    require(
        isinstance(SOURCE_RUN, int)
        and isinstance(SOURCE_HEAD, str)
        and len(SOURCE_HEAD) == 40
        and (q["source_run"], q["source_head"]) == (SOURCE_RUN, SOURCE_HEAD)
        and not any(row["run"] == SOURCE_RUN for row in q["rejected_source_runs"]),
        "source stage is not admitted",
    )
    require(
        isinstance(PROVIDER_RUN, int)
        and PROVIDER_RUN != SOURCE_RUN
        and isinstance(PROVIDER_HEAD, str)
        and len(PROVIDER_HEAD) == 40
        and (q["provider_run"], q["provider_head"]) == (PROVIDER_RUN, PROVIDER_HEAD),
        "both independently qualified provider layouts need a separate immutable run",
    )
    require(
        isinstance(q["source_transfer"], dict) and isinstance(q[phase], dict), "phase has not been enrolled"
    )
    item = q[phase]
    need = {"screen": "source", "primary": "screen", "independent": "primary"}[phase]
    require(item["after"] == need and len(item["accepted_sha256"]) == 64, "unfrozen preceding qualification")
    require(
        file_sha(here / "admitted" / f"{phase}.json") == item["accepted_sha256"],
        "prior independent acceptance record",
    )
    cert = json.loads((here / "admitted" / f"{phase}.json").read_bytes())
    require(
        cert["passed"] is True
        and cert["cohort"] == need
        and cert["source_head"] == SOURCE_HEAD
        and cert["source_run"] == SOURCE_RUN
        and cert["provider_run"] == PROVIDER_RUN
        and cert["provider_head"] == PROVIDER_HEAD,
        "incompatible preceding source/phase",
    )
    if phase == "screen":
        require(file_sha(here / "admitted" / "source-qualification.json") == cert["qualified_source_sha256"], "source proof changed")
    if phase != "screen":
        require(
            len(cert["positions"]) == (2 if phase == "primary" else 12)
            and len(set(cert["boot_ids"])) == len(cert["positions"]),
            "missing predecessor positions",
        )
    qualification.previous(here, q)
    return q, cert


def request(path):
    return subprocess.check_output(["gh", "api", API + path])


def reopen(artifacts, role, expected):
    name = f"musl-285-ordinary-{role}"
    (item,) = [a for a in artifacts if a["name"] == name]
    require(
        (item["workflow_run"]["id"], item["workflow_run"]["head_sha"], item["expired"])
        == (SOURCE_RUN, SOURCE_HEAD, False),
        name,
    )
    raw = request(f"artifacts/{item['id']}/zip")
    require(
        item["size_in_bytes"] == len(raw) and item["digest"] == "sha256:" + sha(raw) and sha(raw) == expected,
        name,
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        require(z.testzip() is None, name)

        def physical(suffix):
            matches = [p for p in z.namelist() if p == suffix or p.endswith("/" + suffix)]
            require(len(matches) == 1, (name, suffix, matches))
            return z.read(matches[0])

        def read(suffix):
            return json.loads(physical(suffix))

        structural = read("qualified-ordinary.json")
        result = read("build/terminal.json")
        markers = read("build-markers.json")
        plain = read("ordinary/terminal.json")
        require(plain["role"] == role and result["cmd"] == CMD, "wrong role or ordinary command")
        typed = {}
        stream_sha = {}
        kernels = {}
        linker_only = {}
        native = {}
        for phase, flank in [("edit", "edited"), ("repeat", "unchanged")]:
            content = gzip.decompress(physical("ordinary/" + phase + "/stdout.jsonl.gz"))
            messages = [json.loads(x) for x in content.splitlines()]
            typed[phase], _ = product(messages)
            raw_rows = [
                [m["package_id"], m["target"]["name"], m["fresh"]]
                for m in messages
                if m.get("reason") == "compiler-artifact"
            ]
            rec = plain["all"][phase]
            require(
                rec["fresh"] == raw_rows and rec["cmd"] == CMD and rec["exit"] == 0,
                "untraced typed Cargo output",
            )
            stream_sha[phase] = sha(content)
            kbytes = physical("build/" + flank + "/kernel.json")
            k = json.loads(kbytes)
            require(
                k["cargo"][0]["terminal"] == [0]
                and not k["link_tools"]
                and all(x["terminal"] == [0] for x in k["rustcs"]),
                "native structural flank",
            )
            native[phase] = sorted(x["crate"] for x in k["rustcs"] if not x["link_only"])
            linker_only[phase] = sorted(x["crate"] for x in k["rustcs"] if x["link_only"])
            kernels[phase] = sha(kbytes)
    require(
        structural["role"] == role
        and all(structural["structural"].values())
        and result["full_byte_gate_passed"],
        name,
    )
    records = result["visits"]
    leaves = ("zmij", "compact_str", "ruff_python_ast")
    expect = {}
    for flank, phase in [("edited", "edit"), ("unchanged", "repeat")]:
        require(
            not records[flank]["link_tools"], "ordinary musl AST archive unexpectedly invoked a native linker"
        )
        expect[phase] = sorted(n for n, _, _, only in records[flank]["emitted"] if not only)
    require(native == expect, "source kernel and emitted dep-file owner rosters differ")
    observed = {n: t[0] for n, t in markers["empty"].items()}
    require(
        set(observed) == set(leaves)
        and all(records[p]["typed"] == 39 for p in ("old", "empty", "edited", "unchanged")),
        name,
    )
    if role == "P":
        require(expect["repeat"] == sorted(leaves), "lost pinned parent")
    return {
        "artifact_id": item["id"],
        "artifact_sha256": sha(raw),
        "native": native,
        "link_only_native": linker_only,
        "typed": typed,
        "typed_source_stdout_sha256": stream_sha,
        "native_source_kernel_sha256": kernels,
        "markers": observed,
        "freshness": {p: records[n]["typed_fresh"] for p, n in [("edit", "edited"), ("repeat", "unchanged")]},
        "behavior": {
            k: {"reader": result["outputs"][k]["client"]["sha256"], "stdout": result["outputs"][k]["stdout"]}
            for k in ("old", "empty")
        },
    }


def main(phase, pos):
    orders = assignment(HERE, phase)
    require(1 <= pos <= len(orders), pos)
    require(
        os.environ["GITHUB_REPOSITORY"] == REPO
        and os.environ["GITHUB_REF_NAME"] == BRANCH
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "wrong QA ref/attempt",
    )
    config, cert = admitted(HERE, phase)
    opaque_preflight = qualification.recheck_api(HERE, config, request)
    sys.path.insert(0, str(HERE.parent / "ohm-musl-ast-pair"))
    import lookup, restore

    located = lookup.locate(PROVIDER_RUN, PROVIDER_HEAD)
    require(
        (located["SOURCE_RUN"], located["SOURCE_HEAD"], located["PROVIDER_RUN"], located["PROVIDER_HEAD"])
        == (str(SOURCE_RUN), SOURCE_HEAD, str(PROVIDER_RUN), PROVIDER_HEAD),
        "provider qualification selected different source or donor kit",
    )
    require(located == config["source_transfer"], ("declarative transfer differs", located))
    artifacts = json.loads(request(f"runs/{SOURCE_RUN}/artifacts?per_page=100"))["artifacts"]
    guards = {role: reopen(artifacts, role, cert["ordinary_sha256"][role]) for role in "PC"}
    require(
        len(guards["C"]["native"]["repeat"]) < len(guards["P"]["native"]["repeat"]),
        "source candidate did not avoid a full compilation",
    )
    require(
        all(guards["P"]["behavior"][k] == guards["C"]["behavior"][k] for k in ("old", "empty")),
        "cross-role historical native verdict",
    )
    for key in ("PROVIDER_RUN", "PROVIDER_HEAD"):
        require(key not in os.environ or os.environ[key] == located[key], ("conflicting provider identity", key))
        os.environ[key] = located[key]
    guard = restore.restore(
        orders[pos - 1][0],
        SOURCE_RUN,
        SOURCE_HEAD,
        int(located["TRANSFER_ID"]),
        located["TRANSFER_DIGEST"],
        located["TRANSFER_SEAL"],
    )
    dest = Path(os.environ["RUNNER_TEMP"]) / "musl-hardware-handoff.json"
    save(
        dest,
        {
            "phase": phase,
            "position": pos,
            "order": orders[pos - 1],
            "transfer": located,
            "qualification": guards,
            "admitted": cert,
            "opaque_preflight": opaque_preflight,
            "sdk": str(restore.SDK),
            "sdk_receipt": file_sha(restore.s.LOG / "sdk.json"),
            "guard_subjects": file_sha(restore.s.LOG / "guard-subjects.json"),
            "drivers": guard["drivers"],
            "aware_cargo": guard["cargos"]["aware"],
            "workflow_sha": os.environ["GITHUB_SHA"],
        },
    )


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
