"""Apply the callable patch to the exact previously qualified production −22 compiler."""
from pathlib import Path
import hashlib
import json
import os
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "callable-source.json").read_bytes())
BASE_ROLE = "fa7a_stack_ctfe318"
ROLE = "callables_ctfe318"

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def main(role):
    assert role == ROLE
    base = runpy.run_path(str(HERE / "materialize.py"))
    base["main"](BASE_ROLE)
    qa, rust, release = (base[name] for name in ("QA", "R", "REF"))
    git = base["git"]
    before = json.loads((qa / "source.json").read_bytes())
    source = CONFIG["source"]
    assert before["role"] == BASE_ROLE and before["source"] == base["S"]["arms"][BASE_ROLE]
    assert [git(rust, "rev-parse", expr) for expr in ("HEAD", "HEAD^{tree}")] == [source["parent"], source["parent_tree"]]
    assert before["source"]["epoch"] == source["epoch"] == 43309
    assert before["source"]["ctfe_blob_ids"] == source["ctfe_blob_ids"]
    packet = HERE / "callable-production.pack"
    assert packet.stat().st_size == CONFIG["pack_bytes"] and sha(packet) == CONFIG["pack_sha256"]
    with packet.open("rb") as stream:
        receipt = subprocess.check_output(["git","-C",rust,"index-pack","--strict","--stdin"],stdin=stream,text=True).split()
    assert receipt[-1] == CONFIG["pack_git_id"]
    index = Path(git(rust, "rev-parse", "--absolute-git-dir")) / "objects/pack" / ("pack-" + receipt[-1] + ".idx")
    output = subprocess.check_output(["git", "verify-pack", "-v", index],text=True)
    packed = sorted(row.split()[0] for row in output.splitlines() if row and len(row.split()[0]) == 40)
    assert len(set(packed)) == len(packed) == CONFIG["pack_objects"]
    assert hashlib.sha256("".join(v + "\n" for v in packed).encode()).hexdigest() == CONFIG["objects_sha256"]
    commit = source["commit"]
    assert git(rust, "rev-parse", commit + "^") == source["parent"]
    assert git(rust, "rev-parse", commit + "^{tree}") == source["tree"]
    assert git(rust, "diff", "--name-only", source["parent"], commit).splitlines() == sorted(CONFIG["files"])
    for path, oid in {**before["training_objects"], **source["ctfe_blob_ids"], **CONFIG["files"], **CONFIG["codec"]}.items():
        assert git(rust,"rev-parse",commit+":"+path) == oid,path
    git(rust,"checkout","--quiet","--detach","--no-recurse-submodules",commit)
    assert all(git(rust,"hash-object",path)==oid for path,oid in CONFIG["files"].items())
    assert f"const HEADER_FORMAT_VERSION: u16 = {source['epoch']};" in (rust/"compiler/rustc_incremental/src/persist/file_format.rs").read_text()
    manifest=json.loads((release/"toolchains/1.99.0/22.json").read_bytes())
    manifest["sources"]["rust"]["revision"]=commit
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); (root/"1.99.0").mkdir()
        (root/"manifest.schema.json").write_bytes((release/"toolchains/manifest.schema.json").read_bytes())
        candidate_manifest=root/"1.99.0/22.json"
        base["write"](candidate_manifest,manifest)
        assert base["assert_sources"](candidate_manifest,commit)==before["component_git"]
    (qa/"source.json").rename(qa/"previous-production-source.json")
    after={**before,"role":ROLE,"source":source,"source_pack_sha256":sha(packet),
           "previous_qualified_source_sha256":sha(qa/"previous-production-source.json"),
           "overlay_description_sha256":sha(HERE/"callable-source.json")}
    base["write"](qa/"source.json",after)
    assert git(rust,"rev-parse","HEAD")==commit and os.environ["REVIEWED_HEAD"]==after["reviewed_head"]
if __name__=="__main__":
    main(*sys.argv[1:])
