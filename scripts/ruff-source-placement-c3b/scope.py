"""Authenticate the two independent constructor families and the new QA caller."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "ruff-source-placement"
sys.path.insert(0, str(ORIGINAL))
import common as base
import receiver as c2_receiver

P = "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5"
C2 = "4e546b27c311f29d99f9528e64420887f57c7538"
C3 = "ed0262f9bdc384576925229764971f23a141c95f"
BRANCH = "charlie/qa-ruff-placement-c3b-20261102"
C3_FACTORY = 41492092582
C3_FACTORY_QA = "b49a9bb7ff0ce1e98f11b20014583b25113f5fd9"
OLD_FACTORY = c2_receiver.FACTORY
OLD_FACTORY_QA = c2_receiver.FACTORY_QA


def bind():
    need = base.need
    need(
        os.environ.get("GITHUB_REPOSITORY") == base.REPO
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH
        and base.git(HERE, "rev-parse", "HEAD")
        == os.environ["GITHUB_SHA"]
        == os.environ["REVIEWED_HEAD"]
        and os.environ["PLACEMENT_SOURCE"] == C3,
        "different independently enrolled QA caller",
    )
    factory = json.loads((HERE / "protocol.json").read_bytes())
    for path, tree in factory["inherited_trees"].items():
        need(
            base.git(HERE, "rev-parse", "HEAD:scripts/" + path) == tree,
            ("changed inherited source", path),
        )
    need(
        base.sha(HERE / "source-packet.json") == factory["source_packet_sha256"],
        "different product packet",
    )
    registration = json.loads((HERE / "three-arm-protocol.json").read_bytes())
    need(
        registration["source"] == {"P": P, "C2": C2, "C3b": C3}
        and registration["c2_factory"] == OLD_FACTORY
        and registration["c3b_factory"] == C3_FACTORY,
        "different previous or current source",
    )
    return registration


@contextmanager
def product(which):
    base.need(which in ("C2", "C3b"), "unknown compiler")
    directory = ORIGINAL if which == "C2" else HERE
    saved = (base.HERE, base.capsule.HERE, base.capsule.REG)
    try:
        base.HERE = directory
        reg = base.source_binding()
        base.need(
            (reg["roles"]["P"]["revision"], reg["roles"]["C"]["revision"])
            == (P, C2 if which == "C2" else C3),
            "different complete product sources",
        )
        base.capsule.HERE, base.capsule.REG = directory, reg
        yield reg
    finally:
        base.HERE, base.capsule.HERE, base.capsule.REG = saved
