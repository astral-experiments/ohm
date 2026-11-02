"""Reopen every ordinary Cargo event stream, ELF hash, inode and hardware reading."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import subprocess

def read(path):
    return json.loads(path.read_bytes())

def require(ok, why):
    if not ok:
        raise ValueError(why)

def check(root, head):
    result = read(root / "pilot.json")
    require(result["head"] == head and all(result["cross_role_native_equal"].values()), "wrong pilot provenance")
    require(set(result["history"]) == {"0-P", "0-C", "1-C", "1-P"}, "missing ordered history")
    manifest = {a: read(root / ("clean-A-" + a) / "visit.json") for a in "PC"}
    output = {}
    for name, history in result["history"].items():
        role = name[2]
        counts, states = {}, {}
        for phase in ("B", "A", "unchanged", "invalid", "repair"):
            p = root / name / phase
            transcript = list(map(json.loads, gzip.decompress((p / "cargo.stdout.gz").read_bytes()).splitlines()))
            require(transcript[-1] == {"reason":"build-finished","success":phase!="invalid"}, "bad original verdict")
            rows = [x for x in transcript if x.get("reason") == "compiler-artifact"]
            if phase == "invalid":
                errors=[x for x in transcript if x.get("reason")=="compiler-message" and x["message"]["level"]=="error" and x["message"].get("code")]
                require(len(errors)==1 and errors[0]["message"]["code"]["code"]=="E0308"
                        and errors[0]["target"]["name"]=="ruff_python_parser", "wrong rejection")
                continue
            entry=read(p/"visit.json")
            native=json.loads(gzip.decompress((p/"native.json.gz").read_bytes()))
            require(len(rows)==375 and {"cli":native["cli"]["whole"],"reader":native["reader"]["whole"]}==entry["whole"], "native/inventory mismatch")
            want=56 if phase=="B" else 64
            require(native["typed"]==f"Expr={want} valid=1 rejected", "wrong observable Ruff revision")
            key = (entry["whole"],entry["roster"])
            if phase != "B":
                require(key==(manifest[role]["whole"],manifest[role]["roster"]), "different source-specific reference")
            states[phase]=key
            if phase in ("B","A","unchanged"):
                raw=read(p/"clock.json")
                require(raw["event_errno"]==0 and raw["running"]>0 and raw["enabled"]==raw["running"]
                        and raw["instructions"]==entry["count"]>0, "unqualified hardware count")
                counts[phase]=raw["instructions"]
        require(counts==dict(B=history["cold"],A=history["edit"],unchanged=history["steady"]), "wrong meter fields")
        same={}
        for owner, row in read(root/name/"objects.json").items():
            matched=0
            for f in row["objects"].values():
                a,b=f["previous"],f["current"]
                kept=bool(a and b and a[:2]==b[:2])
                require(f["same_inode"]==kept and (not kept or f["before_sha256"]==f["after_sha256"]), "inconsistent native object")
                matched+=kept
            same[owner]=matched
        require(same==history["same"],"incorrect reused object count")
        output[name]=dict(counts=counts,same=same,storage=read(root/name/"A/visit.json")["storage"],B=states["B"])
    expected_bodies = {v for record in manifest.values() for v in record["whole"].values()}
    expected_bodies.update(v for result in output.values() for v in result["B"][0].values())
    bodies = root / "reference-bodies"
    require({p.name for p in bodies.iterdir()} == {v+".zst" for v in expected_bodies}, "unregistered clean body")
    for digest in expected_bodies:
        with subprocess.Popen(["zstd", "-dcq", bodies/(digest+".zst")], stdout=subprocess.PIPE) as reader:
            require(hashlib.file_digest(reader.stdout, "sha256").hexdigest()==digest and reader.wait()==0,
                    "physical clean ELF digest disagrees")
    for i in "01":
        require(output[i+"-P"]["B"]==output[i+"-C"]["B"],"independent B references differ")
    rates={p:[1-output[f"{i}-C"]["counts"][p]/output[f"{i}-P"]["counts"][p] for i in "01"] for p in ("B","A","unchanged")}
    packet=dict(head=head,pairs=output,paired_reductions=rates)
    (root/"reopened.json").write_text(json.dumps(packet,sort_keys=True,indent=2)+"\n")
    print(json.dumps(rates))
if __name__=="__main__":
    check(Path(sys.argv[1]),sys.argv[2])
