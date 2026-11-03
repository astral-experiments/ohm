"""Recompute the published native and sampled results from the literal Actions artifact."""
import argparse
import gzip
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import domains
import native_code
import verify

EVIDENCE=HERE/"evidence"
ARCHIVE_SHA="df3081a35e1daffbafe4ce38956515ea52ff7355d72c837cf5265ff722ab46dd"


def main(driver, mutate):
    archive=EVIDENCE/"signed-23-semantic.zip"
    result=verify.run(archive,ARCHIVE_SHA,driver)
    assert result==json.loads((EVIDENCE/"native-and-pcs.json").read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert domains.run(z,result)==json.loads((EVIDENCE/"disjoint-and-salsa.json").read_bytes())
        if driver is not None:
            assert native_code.run(z,driver)==json.loads((EVIDENCE/"signed-native-hot.json").read_bytes())
        if mutate:
            selftests(z,result)
    pc=result["pc"]
    print(f'{pc["owner_samples"]:,} literal samples, {pc["hardware_instructions"]:,} exclusive rustc instructions, '
          f'{pc["all_process_samples"]:,} whole-history samples. PID {result["target"]["pid"]}.')
    print("Driver coverage:", dict(pc["coverage"]), "outside original body-qualified ranges:", dict(pc["unplaced"]))
    print("All seven native histories, the signed compiler metadata and disjoint leaf results match.")


class Overlay:
    def __init__(self,z,patch):
        self.z=z
        self.patch=patch
    def read(self,name):
        return self.patch.get(name,self.z.read(name))
    def namelist(self):
        return self.z.namelist()


def encoded(obj):
    return json.dumps(obj,separators=(",",":")).encode()


def selftests(z,result):
    def rejected(name,call):
        try:
            call()
        except (ValueError,KeyError) as e:
            print(f"Rejected {name}: {e}")
        else:
            raise AssertionError("mutation accepted: "+name)
    owner=result["target"]
    real=json.loads(z.read("pc-sdk.json"))
    samples="profile/samples.ndjson.gz"
    lines=gzip.decompress(z.read(samples)).splitlines()
    for i,line in enumerate(lines):
        row=json.loads(line)
        if row[0]!="f" and row[2]==owner["pid"]:
            row[6][1]+=1;lines[i]=encoded(row);break
    else:raise ValueError("missing owner sample")
    altered=gzip.compress(b"\n".join(lines)+b"\n",mtime=0)
    rejected("an actual sampled IP shifted one byte",lambda:verify.score(Overlay(z,{samples:altered}),real,owner))
    full={r["crate"]:r["argv"] for r in json.loads(z.read("release23/edited/rustcs.json"))}
    key=f'profile/exec/{owner["epoch"]:05d}.nul'
    raw=z.read(key);bad=raw.replace(b"--crate-name\0ty_python_semantic\0",b"--crate-name\0ty_python_semantiC\0")
    assert raw!=bad
    rejected("wrong compiler argv on the actual observed PID",lambda:verify.owners(Overlay(z,{key:bad}),full,real["rustc"]))
    placements="profile/leaf-placements.ndjson.gz";sumfile="profile/semantic.json"
    rows=[json.loads(x) for x in gzip.decompress(z.read(placements)).splitlines()]
    r=next(r for r in rows if r["dso"]==real["driver"]["path"] and len(r["symbol_ranges"])==1)
    r["symbol_ranges"][0][0]=r["va"]+1
    payload=gzip.compress(b"\n".join(encoded(v) for v in rows)+b"\n",mtime=0)
    s=json.loads(z.read(sumfile));s["leaf_placements_sha256"]=verify.sha(payload)
    rejected("claimed symbol range excludes actual PC even after recomputing its transport hash",
             lambda:verify.score(Overlay(z,{placements:payload,sumfile:encoded(s)}),real,owner))
    s=json.loads(z.read(sumfile));m=next(m for m in s["binaries"] if "/libsalsa_macros-"in m)
    old=s["binaries"][m]["gnu_build_id"];s["binaries"][m]["gnu_build_id"]="f"+old[1:]
    assert s["binaries"][m]["gnu_build_id"]!=old
    rejected("independently rebuilt macro ID contradicts the native PERF_HEADER_BUILD_ID",
             lambda:domains.run(Overlay(z,{sumfile:encoded(s)}),result))
    error="release23/invalid/stdout";v=z.read(error).replace(b"E0308",b"E0309")
    ref=json.loads((HERE.parent/"pc-reference.json").read_bytes())
    rejected("different real type-checking diagnostic",lambda:verify.native_controls(Overlay(z,{error:v}),ref))


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--driver",type=Path,help="optionally verify all signed-driver ranges and hottest-function instructions")
    ap.add_argument("--mutations",action="store_true")
    args=ap.parse_args()
    main(args.driver,args.mutations)
