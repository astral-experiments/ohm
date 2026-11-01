"""Bind real mapped drivers and the selected AST tables outside the hardware acquisition."""

import gzip
import json
from pathlib import Path
from unittest.mock import patch

import contract as q

AST = ("ruff_python_ast",)


def data(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def mapped_build(h, observer, w, env, arm):
    record = data(h.OUT / "sdk" / (arm[0] + ".json"))
    sdk = Path(env["LD_LIBRARY_PATH"]).parent
    driver = record["driver"]

    def invoke(folder, code):
        events, count, actual = observer.invocation(folder, env, code, arm)
        return events, count, h.dw.rows(actual), actual

    events, count, _, actual = h.dw.live_driver.watch(
        invoke, w, 0, sdk, sdk / driver, h.dw.write, record["files"][driver]
    )
    return events, count, actual


def registered(dw, first, old, clean, dirty, full, role):
    # Only AST necessarily recompiles after this private body edit.
    with patch.object(dw, "OWN", AST):
        chosen = dw.register([first, old, dirty], full, role)
    selected = chosen[AST[0]]
    y = selected["Y_path"]
    before = {k: v for k, v in clean["sessions"].items() if v["owner"] == AST[0]}
    (unmodified,) = set(before) - {y}
    q.need(
        len(before) == 2
        and y in before
        and before[y] == selected["Y"]
        and selected["X_path"] != unmodified
        and clean["source"]["revision"] == dirty["source"]["revision"] == dw.B
        and clean["source"]["ref"] == dirty["source"]["ref"] == dw.X
        and not clean["source"]["modified"]
        and dirty["source"]["modified"] == ["crates/ruff_python_ast/src/lib.rs"]
        and dirty["source"]["lib"] != clean["source"]["lib"],
        "not a newly published, genuinely dirty X at the same commit",
    )
    return chosen


def dirty_return(h, observer, w, env, arm):
    states = [
        data(w.parent / p / "donor-state.json")
        for p in ("Y-B", "X-A", "X-B", "dirty-X-B")
    ]
    last = data(w.parent / "dirty-X-B/native-execs.json.gz")
    selected = registered(h.dw, *states, h.dw.rows(last), arm[0])
    q.need(
        h.dw.donors.snapshot(h.WORK / "target", arm[0]) == states[-1]["sessions"],
        "donors changed before return",
    )
    h.save(w / "both-ref-tips.json", h.dw.refs(h.kit.TREE, h.dw.B))
    h.save(w / "donor-register.json", selected)
    record = data(h.OUT / "sdk" / (arm[0] + ".json"))
    with patch.object(h.dw.donors, "OWN", AST):
        return h.dw.capture(observer.invocation, w, env, arm, record, selected)


def reopen_mappings(dw, proof, cert, phys):
    (key,) = [
        name for name in cert["files"] if Path(name).name.startswith("librustc_driver-")
    ]
    driver = Path(cert["sdk"]) / key
    reference = proof["reference"]
    dw.driver_map.check_reference(reference, driver, cert["files"][key])
    q.need(not proof["refused"] and proof["worker_pid"] > 0, "mapping reader refused")
    selected = [
        r for r in dw.rows(phys) if r["name"] in dw.OWN and r["mode"] == "compile"
    ]
    q.need(any(r["name"] == AST[0] for r in selected), "no installed AST emitter")
    for r in selected:
        actual = proof["actual"][str(r["pid"])]
        q.need(
            actual["pid"] == r["pid"]
            and actual["argv"][1:] == r["argv"][1:]
            and actual["ancestry"][0] == proof["worker_pid"],
            "different running driver",
        )
        dw.driver_map.check_process(
            reference,
            driver,
            cert["files"][key],
            actual["mount_namespace"],
            actual["visible"],
            actual["maps"],
        )
