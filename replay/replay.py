"""Replay fixed upstream changes with two complete Linux SDKs."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig

wd = Path.cwd()
sys.path.insert(0, str(wd / "replay"))
import history

case, pair = sys.argv[1].split("/")
root = Path(os.environ["RUNNER_TEMP"])
out = wd / "counts"
out.mkdir(exist_ok=True)
record = json.loads((wd / "replay/cases.json").read_text())[case]
baseline = "a7478c768cb329d97dca35bc1fd8cd463780d0ed7432ef6310383ed383625079"
order = ["control", "candidate"] if int(pair) % 2 else ["candidate", "control"]
src = root / "source"
target = root / "target"
sdk = root / "installed"
cargo = sdk / "bin/cargo"
rustc = sdk / "bin/rustc"
meter = root / "meter"
registry = root / "registry"
rustup = root / "rustup"
result = dict(case=case, pair=pair, record=record, order=order, archive={},
              cpu=re.search(r"^model name\s*:\s*(.+)$", Path("/proc/cpuinfo").read_text(), re.M)[1],
              boot=history.sha(Path("/proc/sys/kernel/random/boot_id")), kernel=platform.release())
env = dict(HOME=str(Path.home()), USER=os.environ["USER"], LANG="C.UTF-8",
           PATH=str(Path.home() / ".cargo/bin") + ":" + os.environ["PATH"],
           CARGO_HOME=str(registry), CARGO_BUILD_JOBS="8", CARGO_TARGET_DIR=str(target),
           RUSTUP_HOME=str(rustup), RUSTUP_TOOLCHAIN="ohm", CARGO_TERM_COLOR="never")
toolchain = rustup / "toolchains/ohm"
toolchain.parent.mkdir(parents=True)
toolchain.symlink_to(sdk)


def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)


def install(role):
    tag = "7" if role == "control" else "8"
    kit = wd / "kits" / tag
    archive, = kit.rglob("*.tar.gz")
    h = history.sha(archive)
    result["archive"][role] = h
    if tag == "7":
        assert h == baseline
    else:
        checksum, = kit.rglob("*.tar.gz.sha256")
        assert checksum.read_text().strip().split()[0] == h
    run("tar", "xzf", archive, "-C", root)
    tree = root / "rust-1.100.0-dev-x86_64-unknown-linux-gnu"
    run("sh", tree / "install.sh", "--prefix=" + str(root / role),
        "--disable-ldconfig", "--without=rust-docs", stdout=subprocess.DEVNULL)
    shutil.rmtree(tree)


def git(*args):
    return history.git(src, *args).decode().strip()


def count(name, command, directory, allowed=(0,)):
    receipt = directory / (name + ".tsv")
    timecmd = ["/usr/bin/time","-f","%M","-o",receipt.with_suffix(".rss")] if Path("/usr/bin/time").exists() else []
    p = subprocess.run([*timecmd, meter, rustc, receipt, *command],
                       cwd=src, capture_output=True, env=env)
    if p.returncode not in allowed:
        print(p.stdout[-800:].decode(errors="replace"), p.stderr[-2800:].decode(errors="replace"), flush=True)
        raise RuntimeError((command, p.returncode))
    counts = history.read_counts(receipt)
    total = int(Path(str(receipt) + ".tree").read_text().split()[0])
    return dict(instructions=total, jobs=len(counts), rustc=sum(c["instructions"] for c in counts)), p


import time, resource
for role in order:install(role)
pilot=result["archive"]["control"]==result["archive"]["candidate"]
history.save(out/"result.json",result)
variants=["control","candidate"]+(["opt"] if case=="ruff" else [])
if int(pair)%2==0: variants.reverse()
result["variants"]=variants
def sha(b):return hashlib.sha256(b).hexdigest()
def cpu():
    u=resource.getrusage(resource.RUSAGE_CHILDREN)
    return u.ru_utime+u.ru_stime
def write(file,contents):
    p=src/file
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(contents)
def probes(folder,role):
    base='[package]\nname="%s"\nversion="1.0.0"\nedition="2024"\n'
    write("Cargo.toml",base%"facade"+'[workspace]\nmembers=["reader"]\n[dependencies]\nleaf.path="leaf"\nmiddle.path="middle"\n')
    write("middle/Cargo.toml",base%"middle"+'[dependencies]\nleaf.path="../leaf"\n')
    write("reader/Cargo.toml",base%"reader"+'[dependencies]\nmiddle.path="../middle"\n')
    write("reader/src/lib.rs",'#[doc(inline)] pub use middle::read;\n')
    write("leaf/Cargo.toml",base%"leaf")
    write("middle/src/lib.rs",'pub use leaf::read;\n')
    write("src/lib.rs",'#[doc(inline)] pub use leaf::read;\n#[doc(inline)] pub use middle::read as via;\n')
    def leaf(value,newline=' '):
        write("leaf/src/lib.rs",'#![doc(html_root_url = "https://docs.invalid/")]\npub fn read() ->'+newline+'u32 { '+str(value)+' }\n')
    leaf(7,'\n    ')
    def action(phase,args,dest=target,allowed=0):
        p=subprocess.run([cargo,*args.split(),'-v','--offline'],cwd=src,env=env|dict(CARGO_TARGET_DIR=str(dest)),capture_output=True,text=True)
        (folder/(phase+'.log')).write_text(p.stderr+p.stdout)
        assert p.returncode==allowed,(phase,p.stderr[-1000:])
        return p
    def doc(phase,dest=target):
        p=action(phase,'doc -p facade -p reader --no-deps',dest)
        if phase=='doc3':assert 'Documenting' not in p.stderr
        return [re.findall('src/leaf/lib.rs.html#([0-9-]+)',(dest/'doc'/pkg/'fn.read.html').read_text())[0]for pkg in ('facade','reader')]
    proof={}
    proof["initial"]=doc("doc1"); assert proof["initial"]==["2-3"]*2
    leaf(7)
    action("check","check -p leaf")
    proof["after_edit"]=doc("doc2")
    assert proof["after_edit"]==(["2"]*2 if role=="candidate"and not pilot else proof["initial"]),proof
    assert doc("doc3")==proof["after_edit"]
    proof["fresh"]=doc("fresh",target/'separate')
    assert proof["fresh"]==["2"]*2
    write("src/main.rs",'fn main(){println!("{}",leaf::read());}\n')
    outvals=[]
    for value in (17,18,19):
        leaf(value)
        p=action("build"+str(value),"-Zrelink-only=yes build")
        actual=run(target/'debug/facade',capture_output=True,text=True).stdout.strip()
        assert actual==str(value)
        outvals.append(dict(value=int(actual),link_only='link-only' in p.stderr))
        if value==18:
            assert outvals[-1]["link_only"],p.stderr[-1600:]
            saved=list(target.rglob('*.rlink'))
            assert saved
            for f in saved:
                with open(f,'ab') as h:h.write(b'corrupt')
    assert not outvals[-1]["link_only"],outvals
    proof["outputs"]=outvals
    write("src/main.rs","fn main(){let x: u64 = leaf::read();}\n")
    def messages(phase,code):
        p=action(phase,'check --message-format=json',allowed=code)
        return [m['message']for m in map(json.loads,p.stdout.splitlines())if m['reason']=='compiler-message']
    errors=messages('error',101)
    assert any(x['code'] and x['code']['code']=='E0308'for x in errors)
    write("src/main.rs","fn main(){let x: u32 = leaf::read();}\n")
    warnings=messages("warning",0)
    assert any(x['code'] and x['code']['code']=='unused_variables'for x in warnings)
    assert warnings==messages('cached-warning',0)
    proof["diagnostics"]=sha(json.dumps([errors,warnings],sort_keys=True).encode())
    return proof
def sequence(variant):
    if target.exists():shutil.rmtree(target)
    folder=out/variant;folder.mkdir()
    env.pop("CARGO_UNSTABLE_OHM_OPTIMIZE_MACRO_DEPS",None)
    opt=(variant=="opt"and not pilot)
    if opt:env["CARGO_UNSTABLE_OHM_OPTIMIZE_MACRO_DEPS"]="true"
    if case=='cargo-probes':
        if src.exists():shutil.rmtree(src)
        return probes(folder,variant)
    rows=[]
    def launch(phase,args):
        cmd=['cargo','+ohm',*args,'--locked','--offline']
        start=time.perf_counter();used=cpu()
        numbers,p=count(phase,cmd,folder)
        seconds=cpu()-used;elapsed=time.perf_counter()-start
        (folder/(phase+'.log')).write_bytes(p.stderr)
        row=dict(name=phase,command=cmd,wall=elapsed,cpu=seconds,rev=git("rev-parse","HEAD"),
                 lock=history.sha(src/'Cargo.lock'),**numbers)
        errors=p.stderr.decode()
        row['warnings']=sorted(l for l in errors.splitlines()if l.startswith('warning:'))
        if phase.startswith('metadata'):
            row['output']=sha(p.stdout)
        elif case=="uv":
            tests=sorted(l for l in p.stdout.decode().splitlines()if l.startswith('test ')and not l.startswith('test result:'))
            row.update(tests=len(tests),output=sha(json.dumps(tests).encode()))
            if phase.startswith('warm'): assert len(tests)==55,len(tests)
        elif case=='ty':
            artifacts=[v for v in map(json.loads,p.stdout.splitlines())if v['reason']=='compiler-artifact']
            row["artifacts"]=len(artifacts)
            if phase.startswith('warm'):assert all(a["fresh"] for a in artifacts),len(artifacts)
        if phase.startswith(('warm','metadata')):assert numbers['jobs']==0,numbers
        if case=='ruff'and phase=='cold':
            tokens=[(n,'-C opt-level=1 ' in line)for line in errors.splitlines()for n in ('proc_macro2','quote','syn')if '--crate-name '+n+' 'in line and '--emit=dep-info,metadata,link' in line]
            assert tokens,errors[-1600:]
            if opt:assert any(v for n,v in tokens)
            row['helper_profiles']=tokens
        rows.append(row);history.save(folder/'partial.json',rows)
        print(case,variant,phase,numbers,round(elapsed,3),flush=True)
        return p
    git('checkout','-q','-f','--detach',record["revs"][0])
    run(cargo,"fetch","--locked",cwd=src,env=env,stderr=subprocess.DEVNULL)
    def metas():
        launch('metadata-prime',['metadata','--format-version=1'])
        for i in range(3):launch('metadata'+str(i),['metadata','--format-version=1'])
    if case=='ruff':
        args=['check','-p','ruff_linter','-v']
        for name,rev in zip(('cold','edit','undo'),record["revs"]):
            git('checkout','-q','--detach',rev)
            launch(name,args)
        for i in range(3):launch("warm"+str(i),args)
        metas()
        launch("clippy",["clippy","-p","ruff_linter","-v"])
        for i in range(2):launch("clippy-repeat"+str(i),["clippy","-p","ruff_linter","-v"])
    elif case=='uv':
        args=['test','-p','uv-pypi-types']
        launch("cold",args)
        git('checkout','-q','--detach',record["revs"][1])
        launch("edit",args+["simple_json::"])
        for i in range(3):launch("warm"+str(i),args)
        metas()
    elif case=='ty':
        flags=['test','-p','ty_python_semantic','--test','mdtest','--no-run','--message-format=json']
        git('apply',str(wd/'replay'/'ty-29327-regression.patch'))
        p=launch("cold",flags)
        def mdtest(phase,p):
            path,=[v["executable"]for v in map(json.loads,p.stdout.splitlines())if v.get("executable")and v['target']['name']=='mdtest']
            log=subprocess.run([path,'mdtest::liskov.md'],env=env,cwd=src/'crates/ty_python_semantic',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            assert log.returncode!=0 and 'invalid-method-override'in log.stdout,log.stdout[-900:]
            (folder/(phase+'.log')).write_text(log.stdout)
            diag=sorted((l.strip()for l in log.stdout.splitlines()if "invalid-method-override" in l))
            assert len(diag)>=3
            rows[-1]["diagnostics"]=dict(count=len(diag),sha=sha(json.dumps(diag).encode()))
        mdtest('first-red',p)
        git('apply',str(wd/'replay'/'ty-29327-expanded-regression.patch'))
        for i in range(3): p=launch("warm"+str(i),flags)
        mdtest('expanded-red',p)
        metas()
    return rows
if case!='cargo-probes':
    run("git","init","-q",src)
    run("git","-C",src,"fetch","-q","--depth=2",record['repo'],*dict.fromkeys(record["revs"]))
    env.update(record['env'])
    history.calibrate(root,out)
for variant in variants:
    role='candidate' if variant=='opt'else variant
    (root/role).rename(sdk)
    result[variant]=sequence(variant)
    sdk.rename(root/role)
    history.save(out/'result.json',result)
if case=='cargo-probes':assert result['control']['diagnostics']==result['candidate']['diagnostics']
else:
    for steps in zip(*(result[v]for v in variants),strict=True):
        for k in ('command','name','rev','lock','warnings','tests','artifacts','output','diagnostics'):
            assert all(x.get(k)==steps[0].get(k)for x in steps),(case,k,[x.get(k) for x in steps])
    if case=='ruff':
        helpers={k:sorted(result[k][0]['helper_profiles'])for k in variants}
        assert helpers['control']==helpers['candidate'],helpers
        assert (helpers['candidate']==helpers['opt'])==pilot,helpers
