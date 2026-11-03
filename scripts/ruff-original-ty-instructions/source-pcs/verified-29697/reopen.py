"""Reopen the physical signed OLD/NEW object+dep-graph join without touching a build tree."""
import hashlib,json,shutil,subprocess,sys,tempfile,zipfile
from collections import Counter,defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import depgraph
Q=Path(__file__).resolve().parent
AUTH="c7fc81990937067e31481f8a082a15317dd8608c6e97673d11919cc9feceef99"
def check(v, m):
    if not v: raise ValueError(m)
def decode(z,item,root):
    out=root/item["sha256"]
    if out.exists():return out
    with z.open("ty-ide-bodies/"+item["body"])as src,out.open("xb")as dest:
        dec=subprocess.Popen(["zstd","-qdc"],stdin=subprocess.PIPE,stdout=dest)
        with dec.stdin:shutil.copyfileobj(src,dec.stdin,2**20)
        check(dec.wait()==0,"zstd decompression")
    check(out.stat().st_size==item["bytes"] and depgraph.sha(out)==item["sha256"],"body length or SHA")
    return out
def ar(path):
    # Compare every true ELF .o payload; archive symbol/long-name tables and metadata cannot pass this gate.
    bodies=Counter()
    with path.open("rb")as f:
        check(f.read(8)==b"!<arch>\n","not an ordinary archive")
        while head:=f.read(60):
            check(len(head)==60 and head[58:]==b"`\n","malformed member")
            n=int(head[48:58]);data=f.read(n);check(len(data)==n,"short member")
            if n%2:check(f.read(1)==b"\n","member padding")
            if data.startswith(b"\x7fELF"):
                # .rmeta uses its own ELF envelope, named lib.rmeta/ in these archives.
                if head[:16].strip().rstrip(b"/")in (b"lib.rmeta",b"lib.rmeta-link"):continue
                check(data[4:7]==b"\x02\x01\x01" and data[16:20]==b"\x01\x00\x3e\x00","wrong native format")
                bodies[hashlib.sha256(data).hexdigest(),len(data)]+=1
    return bodies
def run(z,root):
    if Path("/proc/meminfo").exists():
        avail=int(next(line.split()[1]for line in Path("/proc/meminfo").read_text().splitlines()if line.startswith("MemAvailable:")))*1024
        check(avail>8*2**30+350*2**20,"memory reserve")
    graphs=[];sessions={};expected_kinds=json.loads((Q/"source.json").read_bytes())
    for tag in ("profile-OLD","profile-NEW","independent-NEW"):
        v=json.loads(z.read(tag+"/ty-ide-products.json"));o,=(x for n,x in v["outputs"].items()if n.endswith(".rlib"))
        native=ar(decode(z,o,root));check(sum(native.values())==171,"missing original native member")
        if tag=="independent-NEW":check(native==sessions["profile-NEW"][1],"independent empty object inventory differs");continue
        name,arr=next(iter(v["sessions"].items()));check(len(v["sessions"])==1,"ambiguous session")
        objs={n:x for n,x in arr.items()if n.endswith(".o")}
        check(Counter((i["sha256"],i["bytes"])for i in objs.values())==native,"session and archive objects differ")
        sessions[tag]=(objs,native);graphs.append(decode(z,arr["dep-graph.bin"],root));wp=depgraph.work(decode(z,arr["work-products.bin"],root))
        if tag=="profile-OLD":saved=wp
        else:check(wp==saved,"work product inventories differ")
    old,new=(sessions[tag][0]for tag in ("profile-OLD","profile-NEW"))
    check(old.keys()==new.keys() and sessions["profile-OLD"][1]==sessions["profile-NEW"][1],"old/new actual native objects differ")
    g0,cgus=depgraph.graph(graphs[0],all_cgus=True);bykey={r["key"]:r for r in cgus.values()};check(len(bykey)==171,"CGU key census")
    prior_idx={i for r in cgus.values()for i in r["edges"]};_,prior=depgraph.graph(graphs[0],indices=prior_idx);check(prior.keys()==prior_idx,"missing prior index")
    g1,lookup=depgraph.graph(graphs[1],keys={(r["kind"],r["key"])for r in prior.values()});cur=defaultdict(set)
    for r in lookup.values():cur[r["kind"],r["key"]].add(r["value"])
    count=Counter();owners=Counter();named=0;empty=[]
    for product in saved.values():
        if "o" not in product["files"]:continue
        named+=1;n=product["files"]["o"];node=bykey[depgraph.cgu_key(product["name"])]
        a,b=old[n],new[n];check(a["sha256"]==b["sha256"],"native mismatch")
        physical_equal=(a["dev"],a["ino"])==(b["dev"],b["ino"])
        if physical_equal:check(a["mtime_ns"]==b["mtime_ns"],"shared native object changed")
        changed=[r for i in node["edges"]if cur[((r:=prior[i])["kind"],r["key"])]!={r["value"]}]
        if changed:
            check(not physical_equal and all(r["name"]=="upstream_monomorphizations_for" and r["key"] in expected_kinds["owners"]for r in changed),"different changed direct dependency")
            owners.update(r["key"]for r in changed)
        elif not physical_equal:empty.append(n)
        count[physical_equal,bool(changed)]+=1
    check(named==171 and count=={(True,False):148,(False,True):21,(False,False):2} and sorted(owners.values())==[6,18] and len(prior)==146445,"different direct census")
    return {"graphs":[g0,g1],"retained":148,"regenerated":23,"changed_maps":dict(owners),"without_direct_value_difference":empty,"distinct_prior_direct":len(prior)}
if __name__=="__main__":
    path=Path(sys.argv[1]);temp=Path(sys.argv[2]);check(path.stat().st_size==149582004 and depgraph.sha(path)==AUTH,"wrong source archive")
    check(shutil.disk_usage(temp).free>15*2**30+160*2**20,"disk reserve")
    with zipfile.ZipFile(path)as z,tempfile.TemporaryDirectory(dir=temp)as d:print(json.dumps(run(z,Path(d)),sort_keys=True,indent=2))
