"""Typed #22619 probes using the real uv-lock rustc argv. Never included in time."""
from pathlib import Path
import hashlib,json,os,re,subprocess

HERE=Path(__file__).resolve().parent
NAMES={"uv_redacted","uv_distribution_types","url"}

def need(value,msg):
    if not value:raise ValueError(msg)

def sha(path):
    with open(path,"rb") as handle:return hashlib.file_digest(handle,"sha256").hexdigest()

def flags(argv,key):
    return [arg.split("=",1)[1] if arg.startswith(key+"=") else argv[i+1]
            for i,arg in enumerate(argv) if arg==key or arg.startswith(key+"=")]

def inputs(rustc,argv,cwd):
    rustc=Path(rustc);cwd=Path(cwd)
    need(rustc.is_absolute() and cwd.is_absolute() and os.path.samefile(rustc,argv[0]),"rustc executable")
    need(flags(argv,"--crate-name")==["uv_lock"] and flags(argv,"--crate-type")==["lib"] and "--test" not in argv,"ordinary uv-lock lib")
    need(flags(argv,"--edition")==["2024"] and not any(s.startswith('feature=') for s in flags(argv,"--cfg")),"edition/features")
    need(any("metadata" in s.split(",") for s in flags(argv,"--emit")),"checked product")
    bound={};bflags=[];search=[]
    for i,arg in enumerate(argv):
        if arg=="-L" or (arg.startswith("-L") and len(arg)>2):
            value=argv[i+1] if arg=="-L" else arg[2:]
            bflags.extend(["-L",value]);search.append(value)
    need(any(s.startswith("dependency=") for s in search),"rustc dependency search")
    for val in flags(argv,"--extern"):
        name,eq,filename=val.partition("=")
        if name not in NAMES:continue
        need(eq and name not in bound,"duplicate or implicit extern")
        p=(cwd/filename).resolve(strict=True);need(p.is_file() and p.suffix==".rmeta","ordinary checked external metadata")
        need(bool(re.fullmatch(r"lib"+name+r"-[0-9a-f]{16}\.rmeta",p.name)), "wrong crate product")
        bound[name]={"name":p.name,"bytes":p.stat().st_size,"sha256":sha(p)}
        bflags.extend(["--extern",val])
    need(bound.keys()==NAMES,"missing genuine Cargo extern")
    return bflags,bound

def verify_diags(stderr,expected_kind):
    data=[json.loads(line) for line in stderr.decode().splitlines()]
    fatal=[r for r in data if r["level"]=="error"]
    need(all(isinstance(r,dict) and r.get("$message_type")=="diagnostic" and r["level"] in {"error","warning","note","help","failure-note"} for r in data),"non-native diagnostic")
    if expected_kind is None:
        need(not fatal,"unexpected positive-probe error");return []
    coded=[r for r in fatal if r.get("code")]
    need(len(coded)==1 and coded[0]["code"]["code"]=="E0277","expected one trait-bound E0277")
    row=coded[0];needle="SafeUrl" if expected_kind=="safe" else "Url"
    need(needle in row["message"] and "RemoteSource" in row["message"] and "not satisfied" in row["message"],"unrelated E0277")
    spans=[s for s in row["spans"] if s.get("is_primary")]
    line={"bare":5,"safe":6}[expected_kind]
    need(len(spans)==1 and Path(spans[0]["file_name"]).name==expected_kind+".rs" and spans[0]["line_start"]==line,"wrong primary witness")
    need(all(r.get("code") or (r["message"].startswith("aborting due to") and not r["spans"]) for r in fatal),"unrelated error")
    return ["E0277"]

def run(phase,rustc,uv_lock_argv,cargo_cwd,fresh_out,clean_env):
    """Validate an A/B product from the actual check. Caller separately owns runtime and SDK admission."""
    need(phase in ("A","B"),"phase");out=Path(fresh_out);need(out.is_absolute(),"absolute private output");out.mkdir(exist_ok=False)
    extra,bound=inputs(rustc,uv_lock_argv,cargo_cwd);results={}
    for name in ("bare","safe","behavior"):
        expected_bad=name==("safe" if phase=="A" else "bare")
        crate_kind="bin" if name=="behavior" else "lib";src=HERE/"fixture"/(name+".rs");dest=out/(name+".rmeta")
        args=[str(rustc),str(src),"--crate-name","ohm_22619_"+name,"--edition=2024","--crate-type="+crate_kind,
              "--emit=metadata","--error-format=json",*extra,"-o",str(dest)]
        cmd=subprocess.run(args,cwd=cargo_cwd,env=clean_env,capture_output=True,timeout=90)
        (out/(name+".diagnostics.jsonl")).write_bytes(cmd.stderr)
        need(not cmd.stdout and cmd.returncode==(1 if expected_bad else 0),"unexpected witness status for "+name)
        errors=verify_diags(cmd.stderr,name if expected_bad else None)
        need((not dest.exists()) if expected_bad else (dest.is_file() and (dest.stat().st_size>0 or crate_kind=="bin")),"unexpected metadata output")
        results[name]={"returncode":cmd.returncode,"errors":errors,"source_sha256":sha(src),"diagnostics_sha256":hashlib.sha256(cmd.stderr).hexdigest()}
    report={"phase":phase,"checked_consumer":"uv_lock","artifacts":bound,"probes":results,"runtime_execution":False}
    (out/"passed.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n");return report
