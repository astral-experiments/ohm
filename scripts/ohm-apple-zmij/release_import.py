"""Reopen the exact independent release-parent Apple Cargo and its successful native Unicode gate."""
from pathlib import Path
import gzip,hashlib,json,os,subprocess,sys,zipfile
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from study import load,physical,run,save,sha
R="astral-experiments/ohm";RUN=41108831046;QA="69fc9363af822d536b76626d430d03483e3e9d58"
CARGO="fd55a13d0220748794ba3c7c9556ef8ceed8591f";SHA="9f09941432a849b13ee6177c2f4b0f35f5d9c350e518688d64325ce513ec532d"
ART={"cargo":(13002072187,"native-apple-integrated-fd55-cargo",15226218,"c8776e7c63df7ad25fb4089809d41953b8016082949c83eacdbf90198462a94d"),
     "unicode":(13001882997,"native-apple-integrated-fd55-unicode",398957,"112db9cd4e1d29c1b0b3d8a8cb9b82d8ede9cad45bd25ba193fa1d87f0a30e67")}
def api(s,data=False):
 b=subprocess.check_output(["gh","api",f"repos/{R}/"+s]);return b if data else json.loads(b)
def h(b):return hashlib.sha256(b).hexdigest()
def acquire(root):
 assert os.environ["GITHUB_REPOSITORY"]==R
 current=api(f"actions/runs/{RUN}");assert (current["head_sha"],current["run_attempt"],current["conclusion"],current["event"])==(QA,1,"success","workflow_dispatch")
 dest=root/"receipts/cargo-aware";dest.mkdir(parents=True);ids={}
 for key,(idx,name,size,want) in ART.items():
    meta=api(f"actions/artifacts/{idx}");assert (meta["name"],meta["size_in_bytes"],meta["digest"],meta["workflow_run"]["id"],meta["workflow_run"]["head_sha"])==(name,size,"sha256:"+want,RUN,QA) and not meta["expired"]
    orig=root/(key+"-upstream.zip");orig.write_bytes(api(f"actions/artifacts/{idx}/zip",True))
    assert orig.stat().st_size==size and sha(orig)==want
    with zipfile.ZipFile(orig) as z:
        assert z.testzip() is None
        if key=="cargo":
            upstream=json.loads(z.read("build.json"));manifest=json.loads(z.read("manifest.json"));blob=gzip.decompress(z.read("cargo.gz"))
            assert (upstream["source"]["commit"],upstream["source"]["tree"],upstream["source"]["parents"])==(CARGO,"fc9358ddef14d790c6bc6d69f2dc7d465a413ef3",["2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c","c18e91b514b2c4e4966c9ab03232c804af3e1b57"])
            assert h(blob)==manifest["sha256"]==upstream["binary"]["sha256"]==SHA and len(blob)==manifest["bytes"]==40700864 and h(z.read("build.json"))==manifest["build_sha256"] and manifest["workflow"]==QA
            assert blob[:8]==bytes.fromhex("cffaedfe0c000001")
            path=root/"cargo-aware";path.write_bytes(blob);path.chmod(0o555)
            version=run([path,"-Vv"]).decode();assert version==upstream["version"] and "commit-hash: "+CARGO in version
            (dest/"upstream-build.json").write_bytes(z.read("build.json"));(dest/"upstream-manifest.json").write_bytes(z.read("manifest.json"))
            save(dest/"product.json",{"source":upstream["source"],"version":version,"binary":physical(path),"upstream_original_binary":upstream["binary"],"upstream_build_sha256":manifest["build_sha256"],"upstream_archive":want})
        else:
            terminal=z.read("unicode/terminal.json");assert h(terminal)=="f2f5f4dd389cda6b1c8687d67b83a9953e6e36d20253417236bde6bc7741b2b7"
            t=json.loads(terminal);assert t["cases"]==32 and t["integrated"]==CARGO
            for group,rows in t["assignments"].items():
                for phase,d in rows.items():
                    payload=z.read(f"unicode/{group}/{phase}/verified.json");assert h(payload)==d
                    v=json.loads(payload);assert v["status"]==(101 if phase=="bad" else 0)
                    if phase in ("first","repeat","edit-repeat"):assert v["dirty"]==v["work"]["full"]==v["work"]["link_only"]==v["work"]["linkers"]==[]
            (dest/"independent-unicode-terminal.json").write_bytes(terminal)
        ids[key]={"id":idx,"archive":want,"files":len(z.namelist())}
 save(dest/"import.json",{"upstream_run":RUN,"upstream_qa":QA,"artifacts":ids,"selected":SHA})
if __name__=="__main__":acquire(Path(sys.argv[1]).resolve())
