"""Apply the registered generated-impl change to its independently qualified production parent."""
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
PREVIOUS = runpy.run_path(str(HERE / "materialize-domain.py"))
BASE_ROLE = PREVIOUS["ROLE"]
ROLE = BASE_ROLE + "_proc_derive"
BASE = "77ce0545653df71f43e601c28dde01a5e4f02b09"
INCREMENTAL = PREVIOUS["EPOCH"]
METADATA = "compiler/rustc_metadata/src/rmeta/mod.rs"
digest, canon, git = PREVIOUS["digest"], PREVIOUS["canon"], PREVIOUS["text"]


def apply(repo, records, manifest, payload):
    source, parent, files = manifest["source"], manifest["parent"], manifest["files"]
    assert records["role"] == BASE_ROLE and records["source"] == parent
    assert parent["commit"] == BASE and parent["tree"] == "66a77158e627f9fd637dd42eb84f228739d2bef2"
    assert [git(repo, "rev-parse", name) for name in ("HEAD", "HEAD^{tree}")] == [parent["commit"], parent["tree"]]
    projection = {k: records[k] for k in PREVIOUS["stable"]}
    assert digest(canon(projection)) == manifest["published_parent_projection_sha256"]
    assert source["parent"] == BASE and source["parent_tree"] == parent["tree"]
    assert parent["epoch"] == 43317 and source["epoch"] == source["metadata_epoch"] == 43319
    assert manifest["format_versions"] == {"incremental": [43317, 43319], "metadata": [3, 43319]}
    assert len(files) == 15 and sum(k.startswith("compiler/") for k in files) == 9
    assert len(payload) == manifest["pack_bytes"] and digest(payload) == manifest["pack_sha256"]
    pack = subprocess.check_output(["git", "-C", repo, "index-pack", "--strict", "--stdin"], input=payload).decode().split()[-1]
    assert pack == manifest["pack_id"]
    index = Path(git(repo, "rev-parse", "--absolute-git-dir")) / "objects/pack" / ("pack-" + pack + ".idx")
    packed = sorted(l.split()[0] for l in subprocess.check_output(["git", "verify-pack", "-v", index], text=True).splitlines()
                    if re.fullmatch("[a-f0-9]{40}", l.split()[0]))
    tip = source["commit"]
    assert git(repo, "rev-list", "--parents", "-1", tip) == tip + " " + BASE
    assert git(repo, "rev-parse", tip + "^{tree}") == source["tree"]
    assert sorted(git(repo, "rev-list", "--objects", "--no-object-names", tip, "^" + BASE).splitlines()) == packed
    assert len(packed) == len(set(packed)) == manifest["pack_objects"]
    assert digest(("\n".join(packed) + "\n").encode()) == manifest["objects_sha256"]
    lines = git(repo, "diff-tree", "--no-commit-id", "--no-renames", "-r", "--name-status", BASE, tip).splitlines()
    assert {path: status for status, path in (l.split("\t") for l in lines)} == {
        k: "A" if v["before"] is None else "M" for k, v in files.items()}
    for path, changes in files.items():
        for version, key in ((BASE, "before"), (tip, "after")):
            item = changes[key]
            line = git(repo, "ls-tree", version, "--", path)
            if item is None:
                assert not line
                continue
            assert line.split()[:3] == [item["mode"], "blob", item["oid"]] and item["mode"] == "100644"
            body = subprocess.check_output(["git", "-C", repo, "show", version + ":" + path])
            assert len(body) == item["bytes"] and digest(body) == item["sha256"]
    assert not (files.keys() & records["training_objects"].keys())
    for table in (records["training_objects"], source["ctfe_blob_ids"]):
        for path, oid in table.items():
            assert git(repo, "rev-parse", tip + ":" + path) == oid
    assert source["ctfe_blob_ids"] == {p: files[p]["after"]["oid"] if p in files else oid
                                       for p, oid in parent["ctfe_blob_ids"].items()}
    git(repo, "checkout", "--quiet", "--detach", "--no-recurse-submodules", tip)
    for path, item in files.items():
        assert git(repo, "hash-object", path) == item["after"]["oid"]
    assert "const HEADER_FORMAT_VERSION: u16 = 43319;" in (repo / INCREMENTAL).read_text()
    assert re.search(r"const OHM_METADATA_EPOCH:\s*u(?:32|64)\s*=\s*43319;", (repo / METADATA).read_text())


def main(role):
    assert role == ROLE
    manifest = json.loads((HERE / "derive-source.json").read_bytes())
    PREVIOUS["main"](BASE_ROLE)
    setup = runpy.run_path(str(HERE / "materialize.py"))
    qa, rust, reference = (setup[k] for k in ("QA", "R", "REF"))
    old = qa / "source.json"
    before = json.loads(old.read_bytes())
    apply(rust, before, manifest, (HERE / "derive-production.pack").read_bytes())
    source = manifest["source"]
    pinned = json.loads((reference / "toolchains/1.99.0/22.json").read_bytes())
    pinned["sources"]["rust"]["revision"] = source["commit"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "1.99.0").mkdir()
        (tmp / "manifest.schema.json").write_bytes((reference / "toolchains/manifest.schema.json").read_bytes())
        role_manifest = tmp / "1.99.0/22.json"
        setup["write"](role_manifest, pinned)
        assert setup["assert_sources"](role_manifest, source["commit"]) == before["component_git"]
    original = qa / "previous-domain-source.json"
    assert not original.exists() and (qa / "previous-callable-source.json").is_file()
    old.rename(original)
    result = before | {"role": ROLE, "source": source, "source_pack_sha256": manifest["pack_sha256"],
                       "overlay_description_sha256": digest((HERE / "derive-source.json").read_bytes()),
                       "previous_domain_source_sha256": digest(original.read_bytes()),
                       "published_parent_source_sha256": manifest["published_parent_source_sha256"],
                       "published_parent_projection_sha256": manifest["published_parent_projection_sha256"]}
    setup["write"](old, result)
    assert git(rust, "rev-parse", "HEAD") == source["commit"] and os.environ["REVIEWED_HEAD"] == result["reviewed_head"]


if __name__ == "__main__":
    main(*sys.argv[1:])
