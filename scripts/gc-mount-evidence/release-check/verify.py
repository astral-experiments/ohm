"""Replay the Ruff and two collector regressions against one release-style Cargo."""
import errno
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
joint = runpy.run_path(str(HERE.parent / "joint-result/verify.py"))
SOURCE = "b76dc8006155d48a8cd7d6c5543acb9c18e2ce4b"
TREE = "c8d0e89c4226add0ae40b6604025f5e7b04489f5"
INVENTORY = "a4577f82988cc0de84fd0faa94e9b03318624eed7af0bb4314a2e4915c650510"
BINARY = "f1a88bf5fb2bf431eeea068455d9d4e98dcfbfee3dc381ee47cc7c96df3e128f"
WORKFLOW = "0db917cab8e5cfb2cbd51ee794d9f6ce958bc495"


def private_mount(packet, build, lane, expected_error, source=SOURCE, binary=BINARY):
    """Verify the directory identity, mount replacement and external file using native observations."""
    root = f"{lane}/fixed/"
    identity = json.loads(packet[root + "identity.json"])
    observation = json.loads(packet[root + "reattached-result.json"])
    binding = observation["binding"]
    assert identity["expected"] == source and identity["version"] == build["version"]
    assert binding["sha256"] == identity["cargo"]["sha256"] == binary
    assert identity["uid"] > 0 and identity["namespace"] != identity["parent_namespace"]
    assert identity["cargo"]["filesystem"] == "ext4"
    for component, installed_path in (
        ("rustc", "bin/rustc"),
        ("driver", "lib/librustc_driver-b03bf00bec23bb9a.so"),
        ("wild", "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"),
    ):
        assert identity[component]["sha256"] == build["signed_runtime"][installed_path]
    assert packet[root + "cargo.stdout"].decode() == observation["stdout"]
    assert packet[root + "cargo.stderr"].decode() == observation["err"]

    for before_key, outside_key, bound_key in (
        ("before_dir", "outside_dir", "bound_dir"),
        ("before_leaf", "outside_leaf", "bound_leaf"),
    ):
        before, bound = binding[before_key], binding[bound_key]
        assert binding[outside_key] == before and before["mount"] != bound["mount"]
        assert {k: v for k, v in bound.items() if k != "mount"} == {
            k: v for k, v in before.items() if k != "mount"
        }
    original = binding["outside_leaf"]
    assert observation["exit"] == 0 and observation["outside_after"] == original
    assert observation["visible_after"] == binding["bound_leaf"] and original["nlink"] == 1
    assert observation["physical_held_after"] == {"nlink": 1, "sha256": original["sha256"]}

    events = observation["events"]
    assert all(event["pid"] == binding["pid"] for event in events)
    scans = [e["mountinfo"] for e in events if "mountinfo" in e]
    assert scans == list(range(1, len(scans) + 1))
    first_open = next(i for i, e in enumerate(events) if e.get("kind") in ("openat", "openat2"))
    assert sum("mountinfo" in e for e in events[:first_open]) == binding["mountinfo_reads"] >= 2
    assert any(e.get("kind") == "openat2" and e["resolve"] & 1 and e["return"] == -expected_error for e in events)
    successful_unlinks = [e for e in events if e.get("kind") == "unlinkat-payload" and e["return"] == 0]
    assert not successful_unlinks
    fdinfo = sum(e.get("kind") == "mount-id-open" and e["return"] >= 0 for e in events)
    assert (fdinfo > 0) == (expected_error == errno.ENOSYS)
    return {"cargo_pid": binding["pid"], "exit": observation["exit"], "openat2_errno": expected_error,
            "successful_fdinfo_opens": fdinfo, "held_links": original["nlink"], "external_unlinks": 0}


def verify(directory, source, tree, binary, inventory, workflow, run, native_rechecks=None):
    roster = json.loads((directory / "artifacts.json").read_bytes())
    assert set(roster) == {"build", "gc", "late", "private", "ruff"}
    packets = {}
    for role, archive in roster.items():
        path = directory / f"combined-{role}.zip"
        assert path.stat().st_size == archive["bytes"]
        packets[role] = joint["read"](path, archive["sha256"])
    summary = joint["verify"](packets, source, tree, binary, inventory, workflow, workflow, native_rechecks)
    private = packets["private"]
    assert private["build.json"] == packets["build"]["build.json"]
    build = json.loads(private["build.json"])
    assert json.loads(private["terminal.json"]) == {"stack": 0, "stack-enosys": 0}
    assert json.loads(private["registration.json"]) == {
        "build_sha256": joint["sha"](private["build.json"]), "cargo_sha256": binary,
        "inventory": inventory, "source": source, "tree": tree,
        "workflow_run": run, "workflow_sha": workflow,
    }
    summary["private_gc"] = {
        lane: private_mount(private, build, lane, error, source, binary)
        for lane, error in (("stack", errno.EXDEV), ("stack-enosys", errno.ENOSYS))
    }
    return summary


def main():
    return verify(HERE, SOURCE, TREE, BINARY, INVENTORY, WORKFLOW, 41149649623)


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
