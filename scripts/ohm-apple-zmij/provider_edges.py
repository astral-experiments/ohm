"""Exercise a native provider with or without declared Cargo inputs on two genuine Apple compilers."""
import argparse
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dyld import check as dyld
from execs import ExecTrace
from measure import capture, native_rows, select, typed
from study import CHILD, MISSING, PARENT, RECHECK, check_host, compress_bytes, digest, env_for, load, need, physical, run, save, sha


BARRIER = '''#[inline(never)]
pub fn barrier(value: i32) -> i32 {
    unsafe { core::arch::asm!("mov fp, fp", options(nomem, nostack, preserves_flags)); }
    value
}
'''
MAIN = '''#[link(name="qa_owned_external", kind="static")]
unsafe extern "C" { fn qa_value() -> i32; }
fn main() {
    println!("{} {}", barrier(unsafe { qa_value() }), trigger::value());
}
'''
# Every change of the local Rust dependency carries a different runtime value, including repair.
STEPS = (
    ("lower", "lower", 7), ("unchanged-lower", "lower", 7),
    ("higher-no-rust", "higher", 7), ("higher-rust-edit", "higher", 11),
    ("malformed-no-rust", "malformed", 11), ("malformed-rust-edit", "malformed", 13),
    ("repair-before-missing", "higher", 13), ("missing-no-rust", "missing", 13),
    ("missing-rust-edit", "missing", 15), ("restored-rust-edit", "lower", 19),
    ("restored-unchanged", "lower", 19),
)
NATIVE = {"lower":17, "higher":29, "malformed":None, "missing":None}
NO_RUST = {"higher-no-rust", "malformed-no-rust", "missing-no-rust", "repair-before-missing"}


def form(src, placement, watched):
    def put(name, body):
        n=src/name;n.parent.mkdir(parents=True,exist_ok=True);n.write_text(body)
    crate='[package]\nname="{}"\nversion="0.0.1"\nedition="2021"\n'
    deps='[dependencies]\ntrigger={path="trigger"}\n'
    if placement=="library":
        deps+='barrier={path="barrier"}\n'
        put("barrier/Cargo.toml",crate.format("barrier"))
        put("barrier/src/lib.rs", BARRIER)
    put("Cargo.toml",crate.format("qa_owned_test")+deps+'[workspace]\nresolver="2"\n')
    put("trigger/Cargo.toml",crate.format("trigger"))
    put("src/main.rs",(BARRIER if placement=="direct" else "use barrier::barrier;\n")+MAIN)
    watches='println!("cargo:rerun-if-changed={name}");' if watched else ""
    put("build.rs",'''fn main() {
    let root=std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    println!("cargo:rerun-if-changed=build.rs");
    for name in ["early","late"] {
        '''+watches+'''
        println!("cargo:rustc-link-search=native={}",root.join(name).display());
    }
}
''')
    # Keep tracked directories present even while their archive is missing.
    for part in ("early","late"):(src/part).mkdir()
    (src/"trigger/src").mkdir(exist_ok=True)
    return src/"trigger/src/lib.rs"


def provider_factory(root, out):
    store=root/"provider-factory";store.mkdir()
    clang=Path(run(["xcrun","--find","clang"]).decode().strip()).resolve()
    ar=Path(run(["xcrun","--find","ar"]).decode().strip()).resolve()
    env=dict(os.environ, ZERO_AR_DATE="1")
    src=store/"provider.c";obj=store/"provider.o";data={};receipt={}
    for val in (17,29):
        src.write_text(f'int qa_value(void) {{ return {val}; }}\n')
        dest=store/f"provider-{val}.a"
        ops=[]
        for cmd in ([str(clang),"-O1","-c",str(src),"-o",str(obj)], [str(ar),"rcs",str(dest),str(obj)]):
            step=subprocess.run(cmd,env=env,cwd=store,capture_output=True,timeout=30)
            ops.append({"argv":cmd,"exit":step.returncode,"stdout":step.stdout.decode(),"stderr":step.stderr.decode()})
            need(step.returncode==0, f"failed Xcode archive production {ops[-1]}")
        data[val]=dest.read_bytes()
        need(data[val].startswith(b"!<arch>\n") and obj.read_bytes()[:8]==bytes.fromhex("cffaedfe0c000001"),"not a real Mach-O archive")
        (out/f"provider-{val}.a").write_bytes(data[val])
        (out/f"provider-{val}.o").write_bytes(obj.read_bytes())
        receipt[val]={"compiler":physical(clang),"archiver":physical(ar),"calls":ops,"source":src.read_text(),"object":sha(obj),"archive":sha(dest)}
    need(data[17]!=data[29],"identical providers")
    save(out/"providers.json",receipt)
    return data


def configure(src, state, bodies):
    # Replace only bytes that really change. Never touch the native directories on a Rust-only step.
    goals={"early":(bodies[29] if state=="higher" else b"not a native archive\n" if state=="malformed" else None),
           "late":bodies[17] if state in ("lower","higher") else None}
    for d,want in goals.items():
        p=src/d/"libqa_owned_external.a"
        if want is None:
            p.unlink(missing_ok=True)
        elif not p.is_file() or p.read_bytes()!=want:
            tmp=p.with_suffix(".next");tmp.write_bytes(want);os.replace(tmp,p)
    return {d:(sha(src/d/"libqa_owned_external.a") if (src/d/"libqa_owned_external.a").is_file() else None) for d in goals}


def mach(body):
    magic,cpu,_,kind,count,end,_,_=struct.unpack_from("<8I",body)
    need((magic,cpu,kind)==(0xfeedfacf,0x0100000c,2),"not an ARM64 executable")
    i=32;text=[];uid=[]
    for _ in range(count):
        cmd,sz=struct.unpack_from("<II",body,i)
        need(sz>=8 and i+sz<=32+end,"invalid Mach-O load command")
        if cmd==27:uid.append(body[i+8:i+24].hex())
        if cmd==25:
            n,=struct.unpack_from("<I",body,i+64)
            need(sz==72+80*n,"invalid segment table")
            for j in range(n):
                se,sg,_,size,off=struct.unpack_from("<16s16sQQI",body,i+72+80*j)
                if (sg.rstrip(b"\0"),se.rstrip(b"\0"))==(b"__TEXT",b"__text"):
                    need(size>0 and off+size<=len(body),"invalid __text")
                    text.append([size,digest(body[off:off+size])])
        i+=sz
    need(i==32+end and len(text)==len(uid)==1,"missing Mach-O section or UUID")
    return {"raw":digest(body),"text":text[0],"uuid":uid[0],"bytes":len(body)}


def markers(work, placement, capture_dir):
    crate="qa_owned_test" if placement=="direct" else "barrier"
    found={};inodes=set()
    for base in ("target","shared"):
        for path in sorted((work/base).rglob("*.d")):
            if not path.is_file() or not (path.name.startswith(crate+"-") or path.name==crate+".d" or
                    path.name.startswith("lib"+crate+"-") or path.name=="lib"+crate+".d"):
                continue
            st=path.stat();node=(st.st_dev,st.st_ino)
            if node in inodes:continue
            body=path.read_bytes()
            if b"src/main.rs" not in body and b"src/lib.rs" not in body:continue
            inodes.add(node);h=digest(body);out=capture_dir/(h+".d.gz")
            if not out.exists():compress_bytes(out,body)
            found[str(path.relative_to(work))]={"sha256":h,"hard":MISSING in body,"recheck":RECHECK in body}
    return found


def capture_visit(root, src, work, sdk, env, trace, out, defaults, placement):
    argv=["cargo","+ohm"]+([] if defaults else ["-Zohm-defaults=no"])+["build","--locked","--offline","-j4","--message-format=json"]
    code,stdout,stderr,events,sums=capture(argv,src,env,out,trace)
    need(code in (0,101),"non-Cargo termination")
    arts,dirty,codes,roster=typed(stdout,code==0);native=native_rows(events,sdk)
    need(native["scope"]=="kernel-exec" and native["cargo"]==1 and all(l["stock"] for l in native["linkers"]),"unrecognized native process")
    final=[]
    for link in native["linkers"]:
        a=link["argv"]
        if "-lqa_owned_external" not in a:continue
        path,=[a[n+1] for n,s in enumerate(a) if s=="-o"]
        search=[s[2:] if s.startswith("-L") and s!="-L" else a[n+1] for n,s in enumerate(a) if s.startswith("-L")]
        need(str(src/"early") in search and str(src/"late") in search and search.index(str(src/"early"))<search.index(str(src/"late")),"wrong native archive search order")
        ee,=[e for e in events if e["argv"]==a and Path(e["path"]).name in ("ld","ld-classic","ld-prime","ld64")]
        final.append({"output":path,"pid":ee["pid"],"parent":ee["ppid"],"cdhash":ee["cdhash"],"linker":link["sha"],"argv_sha":digest(json.dumps(a, separators=(",",":")).encode()),"search":search})
    need(len(final)<=1,"ambiguous final native link")
    image=None;answer=None;error=None;returned=None
    if code==0:
        exe,=[Path(r["executable"]) for r in arts if r.get("executable") and r["target"]["name"]=="qa_owned_test"]
        returned=str(exe);body=exe.read_bytes();image=mach(body)
        program=root/"receipts/edge-images"/(image["raw"]+".macho.gz")
        if not program.exists():compress_bytes(program,body)
        need(gzip.decompress(program.read_bytes())==body,"changed archived executable")
        proc=subprocess.run([str(exe)],cwd=src,env=env,capture_output=True,timeout=15)
        compress_bytes(out/"program.stdout.gz",proc.stdout);compress_bytes(out/"program.stderr.gz",proc.stderr)
        save(out/"program.json",{"exit":proc.returncode,"path":str(exe),"sha256":image["raw"]})
        need(proc.returncode==0 and not proc.stderr and re.fullmatch(rb"(17|29) (7|11|13|15|19)\n",proc.stdout),"unexpected program verdict")
        answer=list(map(int,proc.stdout.split()))
        for item in final:
            at=Path(item["output"])
            item["retained"]=at.is_file();item["same_inode"]=at.is_file() and exe.samefile(at)
            item["output_sha"]=sha(at) if at.is_file() else None
            if at.is_file():need(item["output_sha"]==image["raw"],"true linker output differs from promoted executable")
    else:
        text=(stdout+b"\n"+stderr).decode(errors="replace")
        need("qa_owned_external" in text or "qa_value" in text,"unrelated compiler error")
        error={"named_archive":"qa_owned_external" in text,"named_symbol":"qa_value" in text,"codes":codes}
    # The on-disk build-script output records what the script actually declared, including its watched directories.
    reports={}
    for base in ("target","shared"):
        for f in sorted((work/base).rglob("output")):
            if not f.is_file() or f.stat().st_size>64*1024:continue
            body=f.read_bytes()
            if b"cargo:rustc-link-search=native=" not in body:continue
            h=digest(body);loc=root/"receipts/edge-markers"/(h+".build-output.gz")
            if not loc.exists():compress_bytes(loc,body)
            reports[str(f.relative_to(work))]=h
    # Preserve emitted build-script directives directly in typed streams.
    directives=[{"linked_paths":r["linked_paths"],"rerun":r["package_id"]} for r in [json.loads(l) for l in stdout.splitlines()] if r["reason"]=="build-script-executed"]
    row={"argv":argv,"status":code,"image":image,"answer":answer,"error":error,"returned":returned,"native":native,"final_links":final,
         "marker":markers(work,placement,root/"receipts/edge-markers"),"typed":roster,"dirty":dirty,"build_script":directives,"build_script_output":reports,"streams":sums["streams"]}
    save(out/"verified.json",row)
    return row


def with_empty(work, task):
    names=("target","shared","cargo-home")
    parked=work/"parked";parked.mkdir()
    for n in names:
        (work/n).rename(parked/n);(work/n).mkdir()
    try:return task()
    finally:
        for n in names:
            p=work/n;need(p.is_dir() and not p.is_symlink(),"untrusted clean directory")
            shutil.rmtree(p);(parked/n).rename(p)
        parked.rmdir()


def run_case(root, trace, role, placement, watch, defaults, bodies, *, visits=STEPS, change=configure, evidence=None, label=None):
    name="-".join((label or role,placement,watch,"default" if defaults else "off"))
    out=root/"receipts/provider-matrix"/name;out.mkdir()
    work=root/"provider-build";src=root/"provider-source";work.mkdir();src.mkdir()
    for n in ("target","shared","cargo-home"):(work/n).mkdir()
    sdk=select(root,role);env=env_for(work,sdk)
    driver,=(sdk/"lib").glob("librustc_driver*.dylib")
    ident={**physical(driver),"ctime_ns":driver.stat().st_ctime_ns}
    need(ident["sha256"]==load(root/"receipts/pair.json")["products"][role]["runtime"]["lib/"+driver.name],"wrong driver")
    save(out/"development-environment.json", {k:digest(v.encode()) for k,v in sorted(env.items())})
    trigger=form(src,placement,watch=="declared")
    trigger.write_text("#[inline(never)] pub fn value()->i32 {7}\n")
    run(["cargo","+ohm","generate-lockfile","--offline"],cwd=src,env=env)
    sources={str(p.relative_to(src)):p.read_text() for p in sorted(src.rglob("*")) if p.is_file()}
    save(out/"inputs.json",{"role":role,"placement":placement,"watch":watch,"defaults":defaults,"driver":ident,"source":sources,"steps":visits})
    rows={};last_rust=7
    prior = {"warm": {}, "empty": {}}
    for name,state,rust in visits:
        check_host(root,7)
        if rust!=last_rust:trigger.write_text(f"#[inline(never)] pub fn value()->i32 {{{rust}}}\n");last_rust=rust
        snapshots=change(src,state,bodies)
        def visit(kind):
            d=out/name/kind
            row=capture_visit(root,src,work,sdk,env,trace,d,defaults,placement)
            if evidence:
                evidence(work,d,row)
                if defaults and row["image"]:
                    from cgu_inputs import witness
                    key = row["image"]["raw"]
                    if row["final_links"]:
                        final, = row["final_links"]
                        argv, = [l["argv"] for l in row["native"]["linkers"]
                                 if l["stock"] and digest(json.dumps(l["argv"], separators=(",", ":")).encode()) == final["argv_sha"]]
                        owned = witness(root, d, Path(row["returned"]).read_bytes(), final["output"], linker=argv)
                        prior[kind][key] = owned
                    else:
                        need(kind == "warm" and key in prior[kind], "no earlier physical link for this returned image")
                        owned = prior[kind][key]
                        save(d/"prior-cgu-proof.json", {"raw": key, "recipe": owned["recipe"],
                                                       "observed_link": owned["linker_argv"]})
                    row["cgu"] = owned
            return row
        a=visit("warm")
        b=with_empty(work,lambda:visit("empty"))
        need(ident=={**physical(driver),"ctime_ns":driver.stat().st_ctime_ns},"driver changed between warm and clean")
        item={"provider":state,"rust":rust,"trigger_sha256":sha(trigger),"archives":snapshots,
              "warm":[a["status"],a["answer"],a["image"]["raw"] if a["image"] else None],
              "empty":[b["status"],b["answer"],b["image"]["raw"] if b["image"] else None],
              "same_raw":a["image"]["raw"]==b["image"]["raw"] if a["image"] and b["image"] else None,
              "same_text":a["image"]["text"]==b["image"]["text"] if a["image"] and b["image"] else None}
        if evidence:
            from cgu_inputs import agrees
            item["same_checked_image"] = item["same_raw"]
            if defaults and a["image"] and b["image"]:
                item["same_checked_image"] = agrees(a["cgu"], b["cgu"])
            if not defaults and item["same_raw"] is False:
                # In the explicitly disabled mode rustc emits no retained Cargo recipe.
                # That independent negative must never inherit default-mode proofs.
                item["same_checked_image"] = False
        save(out/name/"compared.json",item);rows[name]=item
    save(out/"terminal.json",rows)
    # All source states, native provider bytes, raw streams and complete executables remain in the artifact.
    need(src.parent==root and work.parent==root,"foreign test directory")
    shutil.rmtree(work);shutil.rmtree(src)
    return rows


def classify(results):
    issues=[];unwatched=[];image_differences=[];differential=[]
    def verdict(row,kind):
        return row[kind][:2]
    for key,rows in results.items():
        role,placement,watch,mode=key.split("-")
        for name,state,rust in STEPS:
            row=rows[name];expected=[0,[NATIVE[state],rust]] if NATIVE[state] is not None else [101,None]
            if verdict(row,"empty")!=expected:issues.append([key,name,"independent-empty",row["empty"][:2],expected])
            if verdict(row,"warm")!=expected:
                hold=unwatched if watch=="unwatched" and name in NO_RUST else issues
                hold.append([key,name,"warm",row["warm"][:2],expected])
            if row["same_raw"] is False and verdict(row,"warm")==verdict(row,"empty"):
                image_differences.append([key,name,row["same_text"],row["warm"][2],row["empty"][2]])
            if role=="C":
                parent=results["P-"+placement+"-"+watch+"-"+mode][name]
                if verdict(parent,"warm")!=verdict(row,"warm"):
                    differential.append([placement,watch,mode,name,verdict(parent,"warm"),verdict(row,"warm"),expected])
    return {"unexpected_declared_or_Rust_outcomes":issues,"unwatched_classification":unwatched,
            "parent_child_differences":differential,"byte_differences_for_equal_verdicts":image_differences}


def main(root, part):
    root=root.resolve();out=root/"receipts/provider-matrix"
    pair=load(root/"receipts/pair.json")
    need(pair["products"]["P"]["source"]==PARENT and pair["products"]["C"]["source"]==CHILD,"wrong source pair")
    need(len(pair["differ"])==1 and pair["differ"][0].startswith("lib/librustc_driver"),"unmatched pair")
    need((root/"receipts/observer.json").is_file(),"kernel exec is required")
    all_cases=[(r,p,w,d) for w in ("unwatched","declared") for p in ("direct","library") for d in (True,False) for r in "PC"]
    if part=="first":
        out.mkdir()
        for n in ("edge-images","edge-markers"):(root/"receipts"/n).mkdir()
        save(out/"registered.json",{"roles":{"P":PARENT,"C":CHILD},"steps":STEPS,"grammars":[BARRIER],"cases":all_cases,
             "ordinary":True,"profile":"ordinary unmodified dev defaults","early_checkpoint":all_cases[:2],
             "worker":sha(Path(__file__)),"plan":sha(Path(__file__).with_name("provider-edges.md"))})
        bodies=provider_factory(root,out)
        for r in "PC":dyld(root,r,select(root,r),out/("driver-"+r))
        cases=all_cases[:2]
    else:
        reg=load(out/"registered.json")
        need(reg["worker"]==sha(Path(__file__)) and reg["cases"]==list(map(list,all_cases)),"registered controls changed")
        bodies={n:(out/f"provider-{n}.a").read_bytes() for n in (17,29)}
        for n,b in bodies.items():need(digest(b)==load(out/"providers.json")[str(n)]["archive"],"provider bytes changed")
        cases=all_cases[2:]
    trace=ExecTrace();trace.ready()
    try:
        for role,placement,watch,defaults in cases:
            label="-".join((role,placement,watch,"default" if defaults else "off"))
            run_case(root,trace,role,placement,watch,defaults,bodies)
            print("completed",label,flush=True)
    finally:trace.close()
    done=[f for f in out.glob("*/terminal.json")]
    results={f.parent.name:load(f) for f in done}
    need(len(results)==(2 if part=="first" else 16),"incomplete matrix")
    result=classify(results)
    save(out/("first.json" if part=="first" else "terminal.json"),{"cases":len(results),"commands":len(results)*len(STEPS)*2,**result})
    print(json.dumps({k:len(v) for k,v in result.items()},sort_keys=True),flush=True)
    if part=="rest":need(not result["unexpected_declared_or_Rust_outcomes"],"declared or genuine Rust edit differs from the independently empty reference")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("part",choices=("first","rest"))
    args=parser.parse_args()
    main(args.root,args.part)
