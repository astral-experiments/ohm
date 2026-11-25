"""Compare released and candidate Ohm SDKs on local, offline regression fixtures."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback

pair, control, candidate, output = sys.argv[1:]
out = Path(output).resolve()
out.mkdir(exist_ok=True, parents=True)
kits = {"control": Path(control).resolve(), "candidate": Path(candidate).resolve()}
root = Path(tempfile.mkdtemp(prefix="probes9-", dir=os.environ["RUNNER_TEMP"]))
roles = list(kits) if int(pair) % 2 else list(reversed(kits))
registry = {}

def case(label):
    def register(fn):
        registry[label] = fn
        return fn
    return register


def require(value, evidence):
    if not value:
        raise AssertionError(str(evidence)[-3000:])


def decoded(s):
    return [json.loads(ln) for ln in s.splitlines() if ln.startswith('{"')]


class Trial:
    def __init__(self, role, name):
        self.role = role
        self.kit = kits[role]
        self.dir = root / role / name
        self.dir.mkdir(parents=True)
        self.logs = out / "probes" / name / role
        self.logs.mkdir(parents=True, exist_ok=True)
        self.serial = 0
        self.notes = {}
        self.known_bug = False
        self.env = {
            "HOME": str(Path.home()), "LANG": "C.UTF-8",
            "PATH": str(self.kit / "bin") + os.pathsep + os.environ["PATH"],
            "CARGO_HOME": str(self.dir / "cargo-home"),
            "CARGO_TERM_COLOR": "never", "CARGO_NET_OFFLINE": "true",
            "CARGO_BUILD_JOBS": "4", "CARGO_TARGET_DIR": str(self.dir / "target"),
        }
        for key in ("USER", "SDKROOT", "DEVELOPER_DIR"):
            if key in os.environ: self.env[key] = os.environ[key]

    def write(self, name, content):
        path = self.dir / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content, encoding="utf-8")

    def package(self, name, source, extra="", binary=False):
        folder = "" if name == "app" else name + "/"
        self.write(folder+"Cargo.toml", f"[package]\nname='{name}'\nversion='0.1.0'\nedition='2024'\n"
                   + ("[workspace]\n" if not folder else "") + extra + "\n")
        self.write(folder+("src/main.rs" if binary else "src/lib.rs"), source)

    def run(self, *args, check=True, env=None, target="target"):
        local = dict(self.env, CARGO_TARGET_DIR=str(self.dir / target))
        local.update(env or {})
        p = subprocess.run(args, cwd=self.dir, text=True, env=local, capture_output=True, timeout=180)
        self.serial += 1
        self.log = p.stdout + p.stderr
        (self.logs / f"{self.serial:02}.txt").write_text(
            f"{args} {target} {env or {}} ({p.returncode})\n" + self.log)
        require(p.returncode >= 0 and "internal compiler error" not in self.log, self.log)
        if check: require(p.returncode == 0, self.log)
        return p

    def cargo(self, args, **kw):
        return self.run(self.kit/"bin/cargo", *args.split(), **kw)

    def diagnostics(self, args="check", **kw):
        p = self.cargo(args+" --message-format=json", check=False, **kw)
        ms = [item["message"] for item in decoded(p.stdout)
              if item.get("reason") == "compiler-message" and item["message"]["level"] in ("warning","error")]
        # Compare the public message, spans, suggestions and children, independent of Cargo progress.
        norm = json.dumps(ms, sort_keys=True, ensure_ascii=False).replace(str(self.dir), "PROJECT").replace(str(self.kit), "KIT")
        return p.returncode, json.loads(norm)

    def compare_error(self, args, code, may_miss=False, **kw):
        warm = self.diagnostics(args, **kw)
        fresh = self.diagnostics(args, target="fresh", **kw)
        require(fresh[0] and any(m["level"]=="error" and code in str(m) for m in fresh[1]), self.log)
        if may_miss and warm[0] == 0 and all(m["level"]!="error" for m in warm[1]):
            self.known_bug = True
        else:
            require(warm == fresh, (warm,fresh))
        self.notes["warm_status"] = warm[0]
        return fresh

    def doc_edit(self, error, env=None):
        def result(target):
            p = self.cargo("test --doc",check=False,target=target,env=env)
            if p.returncode:
                require(error in self.log,self.log)
                return error
            require("1 passed" in p.stdout,self.log)
            return "accepted"
        warm,fresh = result("target"),result("fresh")
        require(fresh == error, self.log)
        self.notes["warm"] = warm
        self.known_bug = warm == "accepted"
        return fresh


DEP = "[dependencies]\ndep.path='dep'"

def mode(t):
    return t.role=='candidate' and not pilot
def outputs(s):
    out={}
    for e in decoded(s):
        if e.get('reason')=='compiler-artifact':
            key=e['target']['name']
            for file in e['filenames']:
                if file.endswith('.rmeta'):
                    require(key not in out,e)
                    out[key]=Path(file)
    return out
def read(t,paths):
    cmd=[t.kit/'bin/rustc','--edition=2024','reader.rs','--emit=metadata']
    for key,value in paths.items():
        require(value.is_file() and value.stat().st_size>0,key)
        cmd.extend(["--extern",f"{key}={value}","-L","dependency="+str(value.parent)])
    return t.run(*cmd,check=False)
@case("672")
def consumer(t):
    t.package("app","pub use dep::Data;", "[dependencies]\ndep={path='dep'}")
    t.package("dep","", "[[example]]\nname='adapter'\ncrate-type=['rlib']")
    t.write("dep/examples/adapter.rs","pub use dep::Data;")
    t.write("reader.rs","fn main(){ let _: [dep::Data;2]=[app::Data,adapter::Data]; }")
    stats=[]
    for command in ("check --release","check","clippy"):
        for n in (1,2):
            t.write("dep/src/lib.rs", "pub struct Data; fn hidden()->u8{"+str(n)+"}")
            p=t.cargo(command+" --workspace --lib --examples --message-format=json",target=command.replace(" ","-"))
            files=outputs(p.stdout)
            require(set(files)=={"app","dep","adapter"},files)
            c=read(t,files)
            if n==1 or mode(t): require(c.returncode==0,t.log)
            if n==2 and not mode(t) and "release" in command:require(c.returncode and "E0460" in c.stderr,t.log)
            stats.append([command,n,c.returncode])
    return stats

@case("674")
def hardlink(t):
    t.package("app","pub const LEN: usize=1;")
    t.write("src/main.rs","fn main() { let _: [u8;2] = [0; app::LEN]; }")
    require("E0308" in t.cargo("check --bin app",check=False).stderr,t.log)
    t.write("src/lib.rs","pub const LEN: usize=2;")
    t.cargo("build --lib")
    t.cargo("check --lib")
    t.write("src/lib.rs","pub const LEN: usize=1;")
    p=t.cargo("check --bin app",check=False)
    require((p.returncode and "E0308" in t.log) if mode(t) else not p.returncode,t.log)
    return p.returncode

@case("681")
def exe(t):
    t.package("app","fn main() {}",binary=True)
    t.write("tests/cli.rs", 'const BIN: &str = env!("CARGO_BIN_EXE_app"); const _: () = assert!(!matches!(BIN.as_bytes(), b"placeholder:app"));')
    assert "E0080" in t.cargo("check --test cli", check=False).stderr
    t.cargo("test --test cli --no-run")
    p=t.cargo("check --test cli",check=False)
    require((p.returncode and "E0080" in t.log) if mode(t) else not p.returncode,t.log)
    return p.returncode

@case("685")
def sbom(t):
    t.package("app",'pub const PATH: &str=env!("CARGO_SBOM_PATH");')
    t.env["CARGO_BUILD_SBOM"]="true"
    assert t.cargo("-Zsbom check --lib",check=False).returncode
    t.cargo("-Zsbom build --lib")
    p=t.cargo("-Zsbom check --lib",check=False)
    require((p.returncode and "CARGO_SBOM_PATH" in t.log) if mode(t) else not p.returncode,t.log)
    if mode(t):
        t.env["CARGO_BUILD_SBOM"]="false"
        require(t.cargo("check --lib",check=False).returncode,t.log)
    return p.returncode

@case("684")
def early(t):
    t.package("app","pub fn v()->u32{42}")
    t.write("tests/cli.rs",'#[test] fn x(){let s=include_str!(env!("CARGO_SBOM_PATH"));assert!(s.contains("app"));assert_eq!(app::v(),42);}')
    p=t.cargo("-Zsbom test -j2 --test cli",env={"CARGO_BUILD_SBOM":"true"},check=False)
    if mode(t):require(not p.returncode and "1 passed" in t.log,t.log)
    return p.returncode

@case("678")
def marker(t):
    t.package("app",'fn main(){unsafe {core::arch::asm!("nop");}}',binary=True)
    t.cargo("build")
    f=t.dir/'target/debug/app.d'
    contents=f.read_text()
    result=t.run('make','-f',str(f),check=False)
    if mode(t):require(not result.returncode and "/dev/null/ohm-recheck-dependent-links:" in contents,t.log+contents)
    return result.returncode

@case("676-687")
def seed(t):
    t.package("app",'fn main(){dep::v();}', "[dependencies]\ndep={path='dep'}",binary=True)
    t.package("dep",'include!("generated.rs");')
    t.write("dep/src/generated.rs",'pub fn v(){}')
    t.write(".gitignore","target/\nshared/\ncargo-home/\n")
    t.env.update(CARGO_BUILD_BUILD_DIR=str(t.dir.parent/"shared"),CARGO_PROFILE_DEV_DEBUG="0",CARGO_BUILD_SBOM="true")
    t.run("git","init","-q","--initial-branch=main")
    t.cargo("generate-lockfile")
    t.run("git","add",".")
    t.run("git","-c","user.name=Charlie Marsh","-c","user.email=charlie.r.marsh@gmail.com","commit","-qm","Create example")
    stats=[]
    for level in range(3):
        if level:
            dest=t.dir.parent/f"child{level}"
            t.cargo(f"worktree add -b charlie/child{level} {dest} --target-dir {dest}/target HEAD")
            t.dir=dest
        p=t.cargo("-Zsbom build --workspace --message-format=json")
        n=sum(not q["fresh"]for q in decoded(p.stdout)if q.get("reason")=="compiler-artifact")
        graph=json.loads((t.dir/"target/debug/app.cargo-sbom.json").read_text())
        depgraph=json.loads((t.dir/"target/debug/libdep.rlib.cargo-sbom.json").read_text())
        valid=all(x["id"].startswith("path+"+t.dir.as_uri())for x in graph["crates"]+depgraph["crates"])
        deps=(t.dir/"target/debug/app.d").read_text()
        name=str(t.dir/"dep/src/generated.rs") in deps.split()
        if mode(t):require(valid and name,(graph,deps))
        stats.append([level,n,valid,name])
    return stats

@case("689")
def warnings(t):
    t.package("app","", "[[example]]\nname='demo'\nrequired-features=['missing']\n[profile.dev.package.removed]\nopt-level=2")
    t.write("examples/demo.rs","fn main(){}")
    t.cargo("build")
    stats=[]
    for _ in range(2):
        p=t.cargo("check --examples")
        counts=[p.stderr.count(s)for s in ("profile package spec `removed`","invalid feature `missing`","no targets matched")]
        if mode(t):require(counts==[1]*3,p.stderr)
        stats.append(counts)
    return stats

@case("690-693")
def metadata(t):
    def update(n):
        t.write("src/lib.rs",f"pub const N: usize={n};")
        t.write("reader.rs",f"fn main(){{let _: [u8;{n}]=[0; app::N];}}")
    t.package("app","")
    update(1)
    term="-Zohm-check-only --emit=dep-info"
    cmd="check --lib -v"
    assert term not in t.cargo(cmd).stderr
    f,=list((t.dir/'target').rglob('libapp*.rmeta'))
    assert read(t,{'app':f}).returncode==0
    opt=mode(t) and not fallback
    t.env['CARGO_UNSTABLE_OHM_TERMINAL_CHECKS']="true"
    update(2)
    p=t.cargo(cmd)
    require((term in p.stderr)==opt,p.stderr)
    require("--crate-name app" not in t.cargo(cmd).stderr,t.log)
    p=t.cargo(cmd+" --message-format=json")
    assert term not in p.stderr
    require(not read(t,outputs(p.stdout)).returncode,t.log)
    update(3)
    p=t.cargo(cmd)
    require(term not in p.stderr,p.stderr)
    require(not read(t,{'app':f}).returncode,t.log)
    update(4)
    p=t.cargo(cmd)
    require((term in p.stderr)==opt,p.stderr)
    p=t.cargo("rustc --profile check --lib --message-format=json")
    require(not read(t,outputs(p.stdout)).returncode,t.log)
    update(5)
    if mode(t):
        assert term not in t.cargo("-Zohm-terminal-checks=no "+cmd).stderr
        require(not read(t,{'app':f}).returncode,t.log)
    return dict(skipped=opt,preserved_json=True)

@case("694")
def cutoff(t):
    def update(n,ty="u8"):
        t.write("dep/src/lib.rs",f'#[deprecated(note="use other")] pub fn value()->{ty}{{{n}}}')
    t.package("app","pub fn result()->u8{dep::value()}", "[dependencies]\ndep={path='dep'}")
    t.package("dep","")
    t.env['CARGO_UNSTABLE_OHM_TERMINAL_CHECKS']="true"
    cmd="check -v -p app"
    jobs=[]
    for n in range(3):
        update(n)
        p=t.cargo(cmd)
        require("use other" in p.stderr,t.log)
        jobs.append("--crate-name app" in p.stderr)
    if mode(t) and not fallback:require(jobs==[True,False,False],jobs)
    paths=list((t.dir/'target').rglob("dep-lib-app"))
    require(paths,t.log)
    for f in paths:f.unlink()
    require("--crate-name app" in t.cargo(cmd).stderr,t.log)
    update(4,"i8")
    require("E0308" in t.cargo(cmd,check=False).stderr,t.log)
    update(5)
    t.cargo(cmd)
    t.write("src/lib.rs","pub fn result()->i8{dep::value()}")
    for _ in range(2):
        require("E0308" in t.cargo(cmd,check=False).stderr,t.log)
    return jobs

pilot=os.environ.get('PILOT')=='1'
fallback=os.environ.get('LOCAL_FALLBACK')=='1'
report={}
for name,fn in registry.items():
    report[name]={}
    for role in roles:
        try: report[name][role]=dict(passed=True,observed=fn(Trial(role,name)))
        except Exception:
            report[name][role]=dict(passed=False,error=traceback.format_exc())
            traceback.print_exc()
    print(name,json.dumps(report[name])[-700:],flush=True)
    (out/'proof.json').write_text(json.dumps(report,indent=2))
assert all(r['passed']for a in report.values()for r in a.values())
