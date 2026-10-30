"""Acquire the exact upstream stable host and target kit and run the same two provider histories."""
import hashlib,json,shutil,subprocess,sys,tomllib
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import edge_guard
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-registers'))
import edges
from edges import rt,save,need,sha

COMMIT="b940084d7eb6a299eb4bfeb8e34901bc051e7ac4"
MANIFEST_SHA="ce6dddc886364f8d786514771212cebe9b731ba82d6b859951c6b0ccc516b6a2"

def fetch(url,path):
    subprocess.run(["curl","--fail","--location","--silent","--show-error","--retry","3","-o",str(path),url],check=True)

def main():
    mode=sys.argv[1:];need(mode in ([],["native-only"]),"bad scope")
    table=json.loads((HERE.parent/"ohm-aarch64-registers/stock-components.json").read_bytes());root=rt.ROOT/"official";root.mkdir()
    manifest=root/"channel-rust-1.99.0.toml";fetch("https://static.rust-lang.org/dist/channel-rust-1.99.0.toml",manifest);need(sha(manifest)==MANIFEST_SHA,"upstream manifest changed")
    d=tomllib.loads(manifest.read_text());rt.SDK.parent.mkdir(parents=True,exist_ok=True)
    for name,rec in table.items():
        triple=rt.HOST if name.endswith(rt.HOST) else rt.TARGET
        pkg=name.removesuffix("-"+triple); row=d["pkg"][pkg]; target=row["target"][triple]
        need(row["git_commit_hash"]==rec["commit"]==COMMIT and target["xz_url"]==rec["url"] and target["xz_hash"]==rec["sha256"],"upstream manifest mismatch")
        arc=root/rec["url"].rsplit("/",1)[1];fetch(rec["url"],arc);need(sha(arc)==rec["sha256"],"official upstream component changed")
        subprocess.run(["tar","-xJf",str(arc),"-C",str(root)],check=True)
        folder=root/arc.name.removesuffix(".tar.xz")
        subprocess.run(["sh",str(folder/"install.sh"),"--prefix="+str(rt.SDK),"--disable-ldconfig"],cwd=folder,check=True)
    env=rt.environment();tools={}
    for tool in ("cargo","rustc"):
        ret=rt.record([tool,"+ohm","-vV" if tool=="rustc" else "-Vv"],rt.LOG/(tool+"-stock-version"),root,env)
        physical=rt.record(["rustup","which","--toolchain","ohm",tool],rt.LOG/(tool+"-dispatch"),root,env).stdout.decode().strip()
        need(Path(physical).samefile(rt.SDK/"bin"/tool),"wrong actual stable dispatch")
        if tool=="rustc":need(COMMIT.encode() in ret.stdout and b"1.99.0" in ret.stdout,"wrong stable compiler")
        else:need(b"cargo 1.99.0" in ret.stdout and b"5f94df478" in ret.stdout,"wrong stable Cargo")
        tools[tool]=sha(Path(physical))
    save(rt.LOG/"stock-sdk.json",{"manifest":sha(manifest),"version":COMMIT,"components":table,"executables":tools,
         "driver":{p.name:sha(p) for p in (rt.SDK/"lib").glob("librustc_driver*.so")},"plain_Cargo":True})
    rec={}
    assert not mode
    edges.BARRIER=edge_guard.BARRIER
    original=edges.BUILD
    for watch in ("files","directories","undeclared"):
        declared={"files":'println!("cargo:rerun-if-changed={n}/libqa_owned_external.a");',
                  "directories":'println!("cargo:rerun-if-changed={n}");',"undeclared":""}[watch]
        edges.BUILD=original.replace('for n in ["early","late"]{','for n in ["early","late"]{'+declared)
        for placement in ("direct","library"):
            for kind in ("change","missing"):
                label="-".join(("stock",watch,placement,kind));p=rt.LOG/label;p.mkdir()
                edges.run(p,"stock",placement,True,stock_source=COMMIT,native_only=(kind=="missing"))
                rec[label]=sha(p/"completed.json")
    save(rt.LOG/"terminal.json",{"native_stock":COMMIT,"completed":rec,"literal_barrier":edges.BARRIER})
if __name__=="__main__":main()
