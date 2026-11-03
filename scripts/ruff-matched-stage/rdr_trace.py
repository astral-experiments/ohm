"""Replay an ordinary source edit under one diagnostic compiler, outside all counters."""
import hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
WS=Path(os.environ['GITHUB_WORKSPACE']).resolve();here=Path(__file__).resolve().parent
sys.path.insert(0,str(WS/'qa/scripts/ruff-linter-check-attribution'))
import worker as w
import scope_inventory as inv
REF='1273cbdd1b8c827ea4d2fc2141348c8e683336ed';BRANCH='charlie/qa-rdr-visibility-scope-20261103';BASE_SHA='2d4199583df1d3e7b61fbcd52f7223f4565c7e712e9130e3922e97c057619c8c'
FACTORY=Path(os.environ['RUNNER_TEMP'])/'ohm-branch-object-qa'

def check():
    w.need(os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']==w.git(WS/'qa-code','rev-parse','HEAD')and os.environ['GITHUB_REF']=='refs/heads/'+BRANCH and os.environ['GITHUB_REPOSITORY']==w.REPO and os.environ['GITHUB_RUN_ATTEMPT']=='1'and os.environ['GITHUB_EVENT_NAME']=='workflow_dispatch','wrong experiment')
    for name,ref in [('qa',REF),('donor',w.DONOR)]:w.need(w.git(WS/name,'rev-parse','HEAD')==ref and not w.git(WS/name,'status','--porcelain','--untracked-files=all'),'different native harness')
    w.need(w.sha(w.KITS/'exec_count.c')=='1c80d6640d8bfdad197839552c7c324c3d74be189718e7702cfaa4a1e2f71e43'and w.sha(w.KITS/'perf_hook.py')=='67ffd29e3bf97cea39f71e5a3d5fd685b89746402f283e35835ac1fdaeea928b','wrong donor')
w.checked_head=check
w.BRANCH=BRANCH

def prepare():
    w.acquire();inv.prefetch()

def check_traces(directory):
    names={'end.tsv','registration.bin','canonical.bin','sites.tsv','nodes.bin','base.bin','edges.bin','roots.bin'}
    w.need({p.name for p in directory.iterdir()}==set(inv.PACKAGES),'missing complete crate graphs');out={}
    for crate in sorted(inv.PACKAGES):
        data=directory/crate;w.need({p.name for p in data.iterdir()}==names,'missing trace members')
        fields=(data/'end.tsv').read_text().split();w.need(len(fields)==6 and fields[0]=='1','missing terminal graph');events,sites,nodes,edges,roots=map(int,fields[1:]);w.need(0<events<=12_000_000 and 0<sites<65536 and 0<nodes<3_000_000 and 0<edges<=events and 0<roots<=nodes,'invalid summary')
        w.need((data/'nodes.bin').stat().st_size==68*nodes and (data/'base.bin').stat().st_size==16*nodes and (data/'edges.bin').stat().st_size==4*edges and (data/'registration.bin').stat().st_size==12*events and (data/'roots.bin').stat().st_size==4*roots and (data/'canonical.bin').stat().st_size%4==0,'incomplete trace extent');w.need(len((data/'sites.tsv').read_text().splitlines())==sites,'missing source origin')
        out[crate]={}
        for file in sorted(data.iterdir()):
            w.need(file.is_file()and not file.is_symlink()and file.stat().st_size<300*2**20,'oversize or irregular raw'); sha=w.sha(file); size=file.stat().st_size; packed=file.with_suffix(file.suffix+'.zst');subprocess.run(['zstd','-q','-T1','-7',str(file),'-o',packed],check=True);out[crate][file.name]=dict(bytes=size,sha256=sha,zstd=w.sha(packed));file.unlink()
    return out

def run():
    check();w.resources();original=json.loads((FACTORY/'logs/diagnostic.json').read_bytes());root=Path(original['root']);w.need(root==FACTORY/'diagnostic-sdk' and root.is_dir()and not root.is_symlink(),'unregistered source SDK');w.SDK.rename(w.ROOT/'prior-signed-sdk');subprocess.run(['cp','-a','--reflink=auto',root,w.SDK],check=True)
    for record in original['files'].items():
        name,values=record;w.need(w.sha(w.SDK/name)==values[0],'changed SDK bytes')
    w.checkout(w.OLD);w.fresh_state();env=w.environment();directory=w.OUT/'rdr';directory.mkdir();old=directory/'old';old.mkdir();new=directory/'edit';new.mkdir();volatile='OHM_QA_RDR_EDGE_DIRECTORY';w.need(volatile not in env,'ambient tracing')
    def invoke(name,source,selected=None):
        v=inv.check(name,source,env if selected is None else {**env,volatile:str(selected)});w.need(len(v['roster'])==308,'different native Cargo graph');return v
    old_result=invoke('scope-old',w.OLD,old);old_trace=check_traces(old);idle=invoke('scope-old-unchanged',w.OLD);w.need(all(r[-1]for r in idle['roster']),'unexpected unchanged work');parts,times=w.make_snapshot();w.checkout(w.NEW);ordinary=invoke('scope-edit',w.NEW);w.restore_snapshot(parts,times);w.checkout(w.NEW);replay=invoke('scope-traced-edit',w.NEW,new);w.need(ordinary==replay,'diagnostic changed the native edit, any metadata or the roster');edit_trace=check_traces(new);idle_new=invoke('scope-new-unchanged',w.NEW);w.need(all(r[-1]for r in idle_new['roster']),'new unchanged work');w.need(sorted(r[1]for r in ordinary['roster']if not r[-1])==sorted(inv.PACKAGES),'wrong four compiler workloads');w.need(old_result['oracle']['messages']!=ordinary['oracle']['messages'],'stale native oracle')
    source=w.SRC/w.SOURCE;actual=source.read_bytes();source.write_bytes(actual+b'\nconst OHM_INVALID_CHECK_SENTINEL: u64 = "incorrect";\n')
    try:
        bad=w.OUT/'scope-invalid';w.run(inv.CHECK,env,bad,101);w.cargo_result(bad,False)
    finally:source.write_bytes(actual)
    repair=invoke('scope-repaired',w.NEW);w.need(repair['oracle']==ordinary['oracle'] and all(repair['selected'][k]['sha256']==ordinary['selected'][k]['sha256']for k in inv.PACKAGES),'wrong repair');w.fresh_state();empty=invoke('scope-empty-new',w.NEW);w.need(all(empty['oracle'][k]==ordinary['oracle'][k]for k in ('native_object','executable','messages')),'wrong clean native client');w.save(w.OUT/'rdr-accepted.json',dict(old=old_trace,edit=edit_trace,prior_resource=BASE_SHA,driver=original['driver'],source=original['source'],actual=original['revision'],work='off-clock original graph and true registration sites; no hardware or time measurements'))
if __name__=='__main__': {'prepare':prepare,'run':run}[sys.argv[1]]()
