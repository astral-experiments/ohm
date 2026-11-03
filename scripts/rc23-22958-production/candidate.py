"""The one additional source layer on the qualified full -23 compiler."""
import hashlib
import re
import subprocess
from pathlib import Path

import gate

H = Path(__file__).resolve().parent / "handwritten"
F = "60bd529e1a0d59e5904912bd38e6a13702d10263"
F_TREE = "2b6ae56e2269366bed9e28438451690ff64abc54"
SIGNED_CARGO = "f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee"
AUTHORIZATION_SHA256 = "d53715b5c9248cc6bb4e8b4959bf7dbb1e9ff8f28cd0927dee7934c4e0b3d305"
UNIT = "handwritten_slot_collision_uses_the_reserved_ordinal"


def selected(inherited):
    if not re.fullmatch("[a-f0-9]{64}", AUTHORIZATION_SHA256):
        raise ValueError("G has no reviewed positive profile, epochs and build authorization")
    parent = inherited["roles"]["full_with_ctfe"]
    assert (parent["commit"], parent["tree"], parent["epoch"], parent["metadata_epoch"]) == (F, F_TREE, 43422, 43422)
    assert gate.h(H / "build-authorization.json") == AUTHORIZATION_SHA256
    auth = gate.read(H / "build-authorization.json")
    assert auth["build_role"] == "G" and auth["parent"] == F and auth["build_authorized"] is True
    for name in ("G.json", "owner-profile.json", "assigned-epochs.json"):
        assert gate.h(H / name) == auth["inputs"][name]
    role = gate.read(H / "G.json")
    epochs = gate.read(H / "assigned-epochs.json")
    assert role["parent"] == F and role["parent_tree"] == F_TREE
    assert role["role"] == "G" and role["commit"] != F and role["tree"] != F_TREE
    assert epochs["role"] == "G" and epochs["source_parent"] == F
    for key in ("epoch", "metadata_epoch"):
        assert type(role[key]) is int and role[key] == epochs[key] and 43422 < role[key] <= 65535
    assert inherited["signed_cargo_sha256"] == SIGNED_CARGO
    assert gate.h(H / "G.pack") == role["packet"]["sha256"]
    assert role["run_make"] == "handwritten-impl-identity"
    assert "tests/run-make/" + role["run_make"] + "/rmake.rs" in role["files"]
    assert {gate.INC, gate.META, "compiler/rustc_hir_id/src/definitions/tests.rs"} <= role["files"].keys()
    assert role["linked_outputs"] == {"reader": "19 11 13"}
    return {"role_order": ["G"], "roles": {"G": role}, "signed_cargo_sha256": SIGNED_CARGO}


def image(repo, commit, path):
    raw = gate.text(repo, "ls-tree", commit, "--", path)
    if not raw:
        return None
    mode, kind, blob, name = raw.split()
    assert kind == "blob" and name == path and mode in ("100644", "100755")
    return {"mode": mode, "oid": blob}


def install(repo, role):
    """Admit exactly the new positive Git objects and their complete tree delta."""
    assert gate.text(repo, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [F, F_TREE]
    raw = (H / "G.pack").read_bytes()
    assert len(raw) == role["packet"]["bytes"] and 0 < len(raw) <= 1 << 20 and raw[:4] == b"PACK"
    assert hashlib.sha256(raw).hexdigest() == role["packet"]["sha256"] and hashlib.sha1(raw[:-20]).digest() == raw[-20:]
    indexed = subprocess.check_output(["git", "-C", repo, "index-pack", "--strict", "--stdin"], input=raw).decode().split()
    assert indexed == ["pack", raw[-20:].hex()]
    idx = gate.text(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects/pack/pack-" + indexed[1] + ".idx")
    rows = [s.split() for s in gate.text(repo, "verify-pack", "-v", idx).splitlines()]
    objects = {r[0]: r[1] for r in rows if len(r) >= 5 and len(r[0]) == 40}
    commit = role["commit"]
    assert set(objects) == set(gate.text(repo, "rev-list", "--objects", "--no-object-names", "--missing=error", F + ".." + commit).splitlines())
    assert sorted(objects) == role["packet"]["objects"] and len(objects) == int.from_bytes(raw[8:12], "big")
    assert [k for k, v in objects.items() if v == "commit"] == [commit]
    assert gate.text(repo, "show", "-s", "--format=%P %T", commit).split() == [F, role["tree"]]
    paths = gate.text(repo, "diff-tree", "-r", "--no-renames", "--no-commit-id", "--name-only", F, commit).splitlines()
    assert paths == sorted(role["files"]) and all(p.startswith(("compiler/", "tests/")) for p in paths)
    for path in paths:
        assert image(repo, F, path) == role["files"][path]["before"]
        assert image(repo, commit, path) == role["files"][path]["after"] and role["files"][path]["after"]
    for path, value in ((gate.INC, role["epoch"]), (gate.META, role["metadata_epoch"])):
        assert gate.g(repo, "show", commit + ":" + path) == gate.version(gate.g(repo, "show", F + ":" + path), path, 43422, value)
    gate.g(repo, "checkout", "--quiet", "--detach", "--no-recurse-submodules", commit)
    for path in paths:
        f = repo / path
        assert f.is_file() and not f.is_symlink() and gate.oid(f.read_bytes()) == role["files"][path]["after"]["oid"]
        assert bool(f.stat().st_mode & 0o111) == (role["files"][path]["after"]["mode"] == "100755")
    return {"direct_parent": F, "new_objects": sorted(objects), "changes": role["files"],
            "authorization_sha256": AUTHORIZATION_SHA256}
