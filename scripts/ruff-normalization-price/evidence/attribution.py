"""Reopen each of the four disjoint rustc lifetimes. Keep the untraced whole count separate."""
import argparse
import json
import re
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from records import digest, dump, file_hash, from_counter, load, physical

def main():
    p = argparse.ArgumentParser()
    p.add_argument("originals", type=Path)
    p.add_argument("verdict", type=Path)
    p.add_argument("out", type=Path)
    args = p.parse_args()
    verdict = load(args.verdict)
    result = {}
    for b in verdict["blocks"]:
        file = args.originals / (str(b["archive"]) + ".zip")
        assert "sha256:" + file_hash(file) == b["archive_digest"]
        rows = {}
        owner_args = {}
        with zipfile.ZipFile(file) as z:
            for role in b["order"]:
                base = role + "/check/observed-edit/"
                selected = physical(lambda n:z.read(base+"tasks/"+n),
                    json.loads(z.read("installed-"+role+".json")),"0.1.25",True)
                by_crate = {r["name"]:r["instructions"] for r in selected["all"]}
                assert len(by_crate) == 4 and all(by_crate.values())
                assert selected["owner"] == b["prices"][role]["check"]["observed-edit-rustc"]
                owner, = [r for r in selected["all"] if r["name"] == "unicode_normalization"]
                owner_args[role] = owner["argv"]
                ordinary = b["prices"][role]["check"]["ordinary-edit"]
                assert ordinary == from_counter(json.loads(z.read(role+"/check/ordinary-edit/hardware.json")))
                sizes = {}
                for mode in ("check","build"):
                    emitted = json.loads(z.read(role+"/"+mode+"/ordinary-edit/result.json"))
                    sizes[mode] = {k:f["bytes"] for k,f in emitted["products"]["unicode_normalization"].items()}
                rows[role] = {"observed_rustcs":by_crate, "observed_tree":selected["whole_traced"],
                              "untraced_whole_cargo":ordinary, "unicode_normalization_product_bytes":sizes}
        parent, child = owner_args["C5"], owner_args["C7"]
        normalized = {}
        for role, argv in owner_args.items():
            out = argv[argv.index("--out-dir") + 1]
            shard, = re.findall(r"/registries/(v2-[0-9a-f]{16})/", out)
            normalized[role] = [a.replace("/registries/" + shard + "/", "/registries/<actual-role>/") for a in argv]
        rows["literal_owner_argv"] = {"parent_argc":len(parent), "candidate_argc":len(child),
            "equal_if_only_actual_registry_directory_is_replaced":normalized["C5"] == normalized["C7"],
            "differences":[{"index":i,"C5":a,"C7":b} for i,(a,b) in enumerate(zip(parent,child)) if a != b]}
        result[b["slot"]] = rows
    dump(args.out,{"qualified_projection":file_hash(args.verdict),"blocks":result})

if __name__ == "__main__":
    main()
