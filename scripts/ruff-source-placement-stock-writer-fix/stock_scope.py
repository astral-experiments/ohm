"""Verify each real source and factory on its original branch before selecting a toolchain."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
GUARDED = HERE.parent / "ruff-source-placement-c3b"
ORIGINAL = HERE.parent / "ruff-source-placement"
sys.path.insert(0, str(GUARDED))
import scope as guarded

sys.path.insert(0, str(HERE))
import fix_source as stock_source

base, receiver = guarded.base, guarded.c2_receiver
P, C3, STOCK = guarded.P, guarded.C3, "fba2663650927209e3589fdc807194f66271bd5a"
BRANCH = stock_source.BRANCH
# Only a separately verified successful physical construction can enroll a native invocation.
factory_file = HERE / "physical-factory.json"
constructor = json.loads(factory_file.read_bytes()) if factory_file.is_file() else {}
STOCK_FACTORY, STOCK_QA = constructor.get("factory"), constructor.get("qa")
GUARDED_FACTORY, GUARDED_QA = guarded.C3_FACTORY, guarded.C3_FACTORY_QA
INTERNAL = {"P": "P", "C3b": "G", "Stock4": "C"}


def read(path):
    return json.loads(path.read_bytes())


def bind():
    base.need(
        os.environ.get("GITHUB_REPOSITORY") == base.REPO
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH
        and base.git(HERE, "rev-parse", "HEAD")
        == os.environ["REVIEWED_HEAD"]
        == os.environ["GITHUB_SHA"]
        and os.environ["PLACEMENT_SOURCE"] == STOCK,
        "wrong independently registered selected QA event",
    )
    packet, reg = stock_source.binding(HERE)
    spec = read(HERE / "protocol.json")
    for name, tree in spec["inherited_trees"].items():
        base.need(
            base.git(HERE, "rev-parse", "HEAD:scripts/" + name) == tree,
            ("different previously verified QA source", name),
        )
    study = read(HERE / "selected-study.json")
    base.need(
        study["source"] == {"P": P, "C3b": C3, "Stock4": STOCK}
        and packet["subject"] == reg["roles"]["C"]["revision"] == STOCK
        and study["source_factory_protocol"] == base.sha(HERE / "protocol.json")
        and spec["source_packet_sha256"]
        == reg["source_packet_sha256"]
        == base.sha(HERE / "source-packet.json")
        and bool(STOCK_FACTORY and STOCK_QA)
        and constructor["source"] == STOCK
        and STOCK_FACTORY != stock_source.OLD_FACTORY
        and study["excluded"]["failed_factory"] == stock_source.OLD_FACTORY
        and study["c3b_factory"] == GUARDED_FACTORY,
        "incomplete native source lineage",
    )
    schedule(study)
    return study


def schedule(study):
    blocks = study["blocks"]
    base.need(
        blocks
        == [
            {"slot": 1, "roles": ["P", "C3b", "Stock4"], "suites": ["option", "e2e"]},
            {"slot": 2, "roles": ["Stock4", "C3b", "P"], "suites": ["e2e", "option"]},
        ],
        "not the two prospective reversed ordinary visits",
    )
    return [r["roles"] for r in blocks]


@contextmanager
def product(which):
    if which == "C3b":
        with guarded.product("C3b") as reg:
            yield reg
        return
    base.need(which == "Stock4", "unregistered physical kit family")
    previous = (base.HERE, base.capsule.HERE, base.capsule.REG)
    try:
        _, verified = stock_source.binding(HERE)
        base.HERE = HERE
        reg = base.source_binding()
        base.need(
            reg == verified
            and reg["roles"]["P"]["revision"] == P
            and reg["roles"]["C"]["revision"] == STOCK,
            "different source-built matched compiler",
        )
        base.capsule.HERE, base.capsule.REG = HERE, reg
        yield reg
    finally:
        base.HERE, base.capsule.HERE, base.capsule.REG = previous
