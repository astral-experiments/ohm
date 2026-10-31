"""Use the reviewed F and E compiler archives and the frozen twelve-host order."""

from pathlib import Path
import json
import os
import sys

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "branch-first-session-e-screen"
sys.path[:0] = [str(HERE), str(COMMON)]
import decision
import checked_source
import confirm_binding as registration
import subjects

b = subjects.b
BASE_ROLE, TREATMENT = "F", "E"
BASE_COMMIT = "c6fe8ecda65452c105f85367a009af80cbb5efbc"
REF = registration.REF
RUNTIME = checked_source.RUNTIME
SOURCE_REPLAY = checked_source.CERTIFICATE
EXCLUDED = HERE / "inputs/excluded-boots.json"
ORDERS = decision.orders(json.loads((HERE / "inputs/orders.json").read_bytes()))
COLD_TABLE_ARM = "Eon"
PACKED_OBJECTS = frozenset(("Eon",))
EXTRA_INPUTS = tuple(
    HERE / "inputs" / name
    for name in (
        "orders.json",
        "previous-boots.json",
        "pilots.json",
        "integration-boots.json",
        "projections.json",
    )
) + (HERE / "SOURCE-ADDENDUM.md", checked_source.PROVIDER)


def enrollment():
    registration.local()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        b.need(
            os.environ.get("PREVIOUS_BINDING")
            == registration.sha(HERE / "inputs/integration-boots.json"),
            "prior job and boot receipt changed",
        )
    return checked_source.enrollment()


def activate(arm, rows, folder):
    b.need(arm in decision.ROLES, "unregistered role")
    enrolled = (
        b.spec()["manifest"]
        if arm.startswith("F")
        else checked_source.enrollment()["qualified"]["manifest"]
    )
    return b.activate(arm, rows, folder, permitted=decision.ROLES, source_manifest=enrolled)


def acquire(source):
    code = source / "scripts/branch-checked-packed-source"
    return subjects.acquire_from(
        source, BASE_ROLE, BASE_COMMIT, checked_source.enrollment(),
        code / "locate_checked.py", code / "restore_checked.py", checked_source.media,
    )


if __name__ == "__main__":
    print("source_head=" + enrollment()["head"])
