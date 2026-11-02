"""Apply the trait-defining-crate proof to the sealed ac671 production source."""
from pathlib import Path
import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PARENT = "ac67101cb973e35ce8ff044cc8014c2c76bab69e"
TREE = "1c07367341a9cc53272e9eefdae1ac8823d44839"
PREVIOUS_ROLE = "callables_ctfe318_incoherent_domain_proc_derive"
ROLE = PREVIOUS_ROLE + "_trait_origin"
EPOCH = "compiler/rustc_incremental/src/persist/file_format.rs"
WIRE = "compiler/rustc_metadata/src/rmeta/mod.rs"
PROTOCOL = "d6f293599dceb1079fbf3ba6b534b2a263824210278c009773c3367b79fc7aa8"
STABLE = ("role", "source", "component_git", "recipe", "training_objects", "signed_manifest_sha256",
          "released_coordinator", "source_pack_sha256", "overlay_description_sha256")


def git(repo, *args, data=None):
    return subprocess.check_output(["git", "-C", repo, *args], input=data)


def value(repo, *args):
    return git(repo, *args).decode().strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply(repo, before, manifest, payload):
    source, files = manifest["source"], manifest["files"]
    assert manifest["role"] == ROLE and before["role"] == PREVIOUS_ROLE
    assert before["source"] == manifest["parent"] == json.loads((HERE / "derive-source.json").read_bytes())["source"]
    assert source["parent"] == PARENT and source["parent_tree"] == TREE
    assert before["source"]["commit"] == PARENT and before["source"]["tree"] == TREE
    assert value(repo, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [PARENT, TREE]
    assert manifest["format_versions"] == {"incremental": [43319, 43323], "metadata": [43319, 43319]}
    assert source["epoch"] == 43323 and source["metadata_epoch"] == before["source"]["metadata_epoch"] == 43319
    assert digest((HERE / "origin-protocol.json").read_bytes()) == manifest["prospective_protocol_sha256"] == PROTOCOL
    # These are the same stable source fields checked by the previous production arm.
    canonical = runpy.run_path(str(HERE / "materialize-domain.py"))["canon"]
    assert digest(canonical({key: before[key] for key in STABLE})) == manifest["published_parent_projection_sha256"]
    assert len(payload) == manifest["pack_bytes"] and digest(payload) == manifest["pack_sha256"]
    pack = git(repo, "index-pack", "--strict", "--stdin", data=payload).decode().split()[-1]
    assert pack == manifest["pack_id"] and re.fullmatch("[0-9a-f]{40}", pack)
    index = Path(value(repo, "rev-parse", "--absolute-git-dir")) / "objects/pack" / ("pack-" + pack + ".idx")
    objects = sorted(line.split()[0] for line in value(repo, "verify-pack", "-v", index).splitlines()
                     if re.fullmatch("[0-9a-f]{40}", line.split()[0]))
    tip = source["commit"]
    assert value(repo, "rev-list", "--parents", "-1", tip) == tip + " " + PARENT
    assert value(repo, "rev-parse", tip + "^{tree}") == source["tree"]
    assert objects == sorted(value(repo, "rev-list", "--objects", "--no-object-names", tip, "^" + PARENT).splitlines())
    assert len(objects) == len(set(objects)) == manifest["pack_objects"]
    assert digest(("\n".join(objects) + "\n").encode()) == manifest["objects_sha256"]
    rows = value(repo, "diff-tree", "--no-commit-id", "--no-renames", "--raw", "--no-abbrev", "-r", PARENT, tip)
    actual = dict((name, record[1:].split()) for record, name in (line.split("\t") for line in rows.splitlines()))
    assert set(actual) == set(files) == set(source["files_from_control"])
    assert EPOCH in files and WIRE not in files and not (files.keys() & before["training_objects"].keys())
    for name, changes in files.items():
        assert name.startswith(("compiler/rustc_", "tests/run-make/", "tests/incremental/")) and name.endswith(".rs")
        left, right = changes["before"], changes["after"]
        assert actual[name] == [left["mode"] if left else "000000", right["mode"], left["oid"] if left else "0" * 40,
                                right["oid"], "M" if left else "A"]
        for item in (left, right):
            if item is not None:
                body = git(repo, "cat-file", "blob", item["oid"])
                assert item["mode"] == "100644" and len(body) == item["bytes"] and digest(body) == item["sha256"]
    expected_ctfe = {path: files[path]["after"]["oid"] if path in files else oid
                     for path, oid in before["source"]["ctfe_blob_ids"].items()}
    assert source["ctfe_blob_ids"] == expected_ctfe
    for path, oid in (before["training_objects"] | expected_ctfe).items():
        assert value(repo, "rev-parse", tip + ":" + path) == oid
    assert value(repo, "rev-parse", tip + ":" + WIRE) == value(repo, "rev-parse", PARENT + ":" + WIRE)
    value(repo, "checkout", "--quiet", "--detach", "--no-recurse-submodules", tip)
    for name, changes in files.items():
        assert value(repo, "hash-object", name) == changes["after"]["oid"]
    assert "const HEADER_FORMAT_VERSION: u16 = 43323;" in (repo / EPOCH).read_text()
    assert re.search(r"const OHM_METADATA_EPOCH:\s*u(?:32|64)\s*=\s*43319;", (repo / WIRE).read_text())


def main(role):
    assert role == ROLE
    manifest = json.loads((HERE / "origin-source.json").read_bytes())
    runpy.run_path(str(HERE / "materialize-derive.py"))["main"](PREVIOUS_ROLE)
    setup = runpy.run_path(str(HERE / "materialize.py"))
    rust, qa, reference = (setup[key] for key in ("R", "QA", "REF"))
    current = qa / "source.json"
    before = json.loads(current.read_bytes())
    apply(rust, before, manifest, (HERE / "origin-production.pack").read_bytes())
    source = manifest["source"]
    pinned = json.loads((reference / "toolchains/1.99.0/22.json").read_bytes())
    pinned["sources"]["rust"]["revision"] = source["commit"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "1.99.0").mkdir()
        (root / "manifest.schema.json").write_bytes((reference / "toolchains/manifest.schema.json").read_bytes())
        candidate = root / "1.99.0/22.json"
        setup["write"](candidate, pinned)
        assert setup["assert_sources"](candidate, source["commit"]) == before["component_git"]
    previous = qa / "previous-derive-source.json"
    assert not previous.exists() and (qa / "previous-domain-source.json").is_file()
    current.rename(previous)
    result = before | {"role": role, "source": source, "source_pack_sha256": manifest["pack_sha256"],
                       "overlay_description_sha256": digest((HERE / "origin-source.json").read_bytes()),
                       "previous_derive_source_sha256": digest(previous.read_bytes()),
                       "published_parent_source_sha256": manifest["published_parent_source_sha256"],
                       "published_parent_projection_sha256": manifest["published_parent_projection_sha256"],
                       "prospective_protocol_sha256": PROTOCOL}
    setup["write"](current, result)
    assert value(rust, "rev-parse", "HEAD") == source["commit"] and os.environ["REVIEWED_HEAD"] == result["reviewed_head"]


if __name__ == "__main__":
    main(*sys.argv[1:])
