"""Measure ordinary Ruff test builds, excluding libtest or renderer execution from the window."""
from contextlib import ExitStack
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import matched as checked
sys.path.insert(0,str(checked.FACTORY/'scripts/ruff-indexed-check-pmu'))
import worker as meter
sys.path.insert(0,str(checked.FACTORY/'scripts/ruff-upstream-mono-pilot'))
import graph_costs

PROTOCOL=json.loads((HERE/'hardware.json').read_bytes())
BASE=checked.OUT
CARGO=checked.old.CMD
need,save,sha=checked.need,checked.save,checked.sha


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def renderer_bodies(path):
    bodies={};long_names=None
    with path.open('rb')as raw:
        need(raw.read(8)==b'!<arch>\n','wrong renderer archive')
        while header:=raw.read(60):
            need(len(header)==60 and header[-2:]==b'`\n','bad ar header');ref=header[:16].strip().decode();size=int(header[48:58]);body=raw.read(size);need(len(body)==size,'truncated ar payload')
            if size%2:need(raw.read(1)==b'\n','bad ar padding')
            if ref=='//':long_names=body;continue
            if not ref.startswith('/') or not ref[1:].isdigit():continue
            at=int(ref[1:]);end=long_names.index(b'/\n',at);name=long_names[at:end].decode();cgu=re.fullmatch(r'annotate_snippets-[a-f0-9]+\.([a-z0-9]+)\.[a-z0-9]+\.rcgu\.o',name);need(cgu is not None and cgu[1] not in bodies,'unknown renderer archive object');bodies[cgu[1]]=hashlib.sha256(body).hexdigest()
    return bodies


def cpu_binding():
    cpus={}
    for cpu in sorted(os.sched_getaffinity(0)):
        topology=Path('/sys/devices/system/cpu')/f'cpu{cpu}/topology';identity=tuple((topology/k).read_text().strip() for k in ('physical_package_id','core_id'));cpus.setdefault(identity,cpu)
    selected=list(cpus.values())[:4];need(len(selected)==4,'four real hardware cores required');os.sched_setaffinity(0,selected);return selected


def setup():
    checked.setup();need(sha(HERE/'matched.json')==PROTOCOL['role_registration_sha256'],'different source-native registration');cpus=cpu_binding();meter.WORK.mkdir();env,_=checked.role('P');need(meter.REG['collector']==PROTOCOL['collector'] and checked.git('rev-parse',checked.CFG['new_commit']+'^')==checked.CFG['old_commit'],'inputs differ');need(meter.git(meter.WS/'collector','rev-parse','HEAD')==PROTOCOL['collector'] and not meter.git(meter.WS/'collector','status','--porcelain'),'collector checkout differs');need(meter.calibrate(env)=='native','whole inherited hardware counters unavailable');save(BASE/'hardware-binding.json',dict(cpus=cpus,boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),kernel=os.uname().release,cpuinfo=Path('/proc/cpuinfo').read_text(),hardware_protocol=sha(HERE/'hardware.json'),meter=sha(meter.WORK/'watch'),loop=sha(meter.WORK/'loop'),command=CARGO))


def resources():
    need(checked.old.available()>8<<30 and shutil.disk_usage(checked.ROOT).free>15<<30,'hardware history reserve reached')


def run_cargo(env,folder,counted,invalid=False):
    resources()
    cmd=([str(meter.WORK/'watch'),str(folder/'clock.json')] if counted else [])+CARGO
    checked.old.command(cmd,env,checked.SRC,folder,checked.STATE,expected=101 if invalid else 0)
    if counted:
        event=json.loads((folder/'clock.json').read_bytes());need(not event['event_errno'] and event['enabled']==event['running']>0 and event['instructions']>0,'invalid inherited hardware window');count=event['instructions']
    else:count=None
    rows=[json.loads(line)for line in (folder/'cargo.stdout').read_bytes().splitlines()];need(rows[-1]=={'reason':'build-finished','success':not invalid},'unexpected Cargo verdict');errors=[r for r in rows if r.get('reason')=='compiler-message' and r['message']['level']=='error'];coded=[r for r in errors if r['message'].get('code')]
    if invalid:need(len(coded)==1 and coded[0]['message']['code']['code']=='E0308' and coded[0]['target']['name']=='ruff_db' and any(s['file_name']==PROTOCOL['invalid_source'] and s['is_primary'] for s in coded[0]['message']['spans']),'different invalid source rejection')
    else:need(not errors,'successful Cargo emitted an error')
    resources();return rows,count


def measured(argv,env,src,out,state):
    need(argv==CARGO and src==checked.SRC and state==checked.STATE,'different primary entry');run_cargo(env,out,True)


def allocated():
    found={};logical=0
    for owner in ('target','build'):
        for p in (checked.STATE/owner).rglob('*'):
            if p.is_file() and not p.is_symlink():
                s=p.stat();key=(s.st_dev,s.st_ino)
                if key not in found:found[key]=s.st_blocks*512;logical+=s.st_size
    return dict(distinct_files=len(found),allocated_bytes=sum(found.values()),logical_bytes=logical)


def check_native(role,rev,case,rows,visit,objects):
    expected=PROTOCOL['expected'][rev];n=visit['native'];need(n['elf']==expected['elf_sha256'] and canonical(n['oracle'])==canonical(expected['oracle']) and n['test_count']==126 and set(n['tests'])==set(checked.old.TESTS) and list(n['tests'].values())==[0,0] and n['exports']==expected['provider_fold_exports'],'complete native source-specific verdict differs');need(checked.roster(rows)==expected['native_roster'],'normal Cargo roster changed')
    provider,=[r for r in rows if r.get('reason')=='compiler-artifact' and r['target']['name']=='annotate_snippets' and r['target']['kind']==['lib'] and r['features']==['default','simd','std']];lib,=(Path(k)for k in provider['filenames']if k.endswith('.rlib'));need(sha(lib)==n['rlib'],'renderer changed in custody');bodies=renderer_bodies(lib);need(len(bodies)==expected['native_renderer_objects'] and canonical(bodies)==expected['native_renderer_objects_sha256'],'renderer native members differ from independent reference');save(case/'renderer-object-hashes.json',bodies)
    if objects is not None:
        need(len(objects)==PROTOCOL['stable_caller_count'] and canonical({k:v['sha256']for k,v in objects.items()})==expected['ruff_db_cgu_sha_by_role'][role],'caller CGU inventory or bytes changed')


def checked_visit(role,rev,phase,env,prior,key,*,pins=None,is_counted=False):
    now,objs,visit=checked.visit(role,rev,phase,env,key,prior,pinned=pins,run_cargo=measured if is_counted else None);case=checked.OUT/(role+'-'+phase);rows=[json.loads(s)for s in (case/'cargo.stdout').read_bytes().splitlines()];check_native(role,rev,case,rows,visit,objs)
    for name,rec in objs.items():need(checked.blob(now/rec['filename'])==rec['sha256'],('physical donor changed',name))
    commit=checked.CFG['roles'][role]['commit'];save(case/'storage.json',dict(total=allocated(),ruff_db=graph_costs.session_costs(now,commit)));return now,objs,visit


def control(role,phase,env,*,invalid=False):
    folder=checked.OUT/(role+'-'+phase);folder.mkdir();rows,count=run_cargo(env,folder,phase=='unchanged',invalid=invalid);info={'exit':101 if invalid else 0,'source':checked.git('rev-parse','HEAD'),'allocated':allocated(),'counted':count is not None}
    if not invalid:
        placement=checked.normal_registry.capture(rows,checked.STATE,True);need((placement['sha256'],placement['products'],placement['shared'])==(checked.CFG['registry']['sha256'],123,114),'incorrect signed registry map');save(folder/'registry.json',placement);native=checked.native('new',rows,folder,env);check_native(role,'new',folder,rows,dict(native=native),None);info['native']=native
        if phase=='unchanged':need(all(v['fresh']for v in rows if v.get('reason')=='compiler-artifact'),'unchanged compiled a Cargo unit')
    save(folder/'visit.json',info)


def history(index,role):
    b=json.loads((BASE/'hardware-binding.json').read_bytes());need(Path('/proc/sys/kernel/random/boot_id').read_text().strip()==b['boot'] and cpu_binding()==b['cpus'] and sha(meter.WORK/'watch')==b['meter'],'different machine or PMU');resources();env,_=checked.role(role);name=f'{index}-{role}';checked.OUT=BASE/name;checked.OUT.mkdir();key=PROTOCOL['different_broad_row']['old']['key'];checked.fresh(name+'-before-old');old,items,first=checked_visit(role,'old','old',env,set(),key,is_counted=True)
    with ExitStack()as stack:
        pins={n:(stack.enter_context((old/rec['filename']).open('rb')),rec)for n,rec in items.items()};edited,now,second=checked_visit(role,'new','edit',env,{old},key,pins=pins,is_counted=True)
    control(role,'unchanged',env);file=checked.SRC/PROTOCOL['invalid_source'];original=file.read_bytes()
    try:
        file.write_bytes(original+PROTOCOL['invalid_append'].encode());control(role,'invalid',env,invalid=True)
    finally:file.write_bytes(original)
    need(not checked.git('status','--porcelain'),'repair did not restore exact Ruff source');control(role,'repair',env);checked.fresh(name+'-before-clean-new');_,clean,last=checked_visit(role,'new','clean',env,set(),key);need(second['native']['elf']==last['native']['elf'] and all(now[n]['sha256']==clean[n]['sha256'] for n in now),'independent clean consumer differs');kept=sorted(n for n,r in now.items() if r['same_pinned_donor']);save(checked.OUT/'summary.json',dict(role=role,order=PROTOCOL['order'][index],boot=b['boot'],counted=['old','edit','unchanged'],kept=kept,caller_objects=len(now)))


def finish():
    observations=[];reject=[]
    for i,order in enumerate(PROTOCOL['order']):
        items={};prices={}
        for role in order:
            root=BASE/f'{i}-{role}';summary=json.loads((root/'summary.json').read_bytes());need(summary['role']==role and summary['order']==order,'wrong order');items[role]=set(summary['kept']);prices[role]={}
            for phase in PROTOCOL['scored']:
                rec=json.loads((root/(role+'-'+phase)/'clock.json').read_bytes());need(rec['instructions']>0 and rec['enabled']==rec['running']>0 and not rec['event_errno'],'unqualified hardware instructions');prices[role][phase]=rec['instructions']
        deltas={phase:1-prices['C'][phase]/prices['P'][phase] for phase in PROTOCOL['scored']};extra=sorted(items['C']-items['P']);lost=sorted(items['P']-items['C']);qualified=deltas['edit']>=PROTOCOL['minimum_reduction_each'] and len(extra)>len(lost)
        if not qualified:reject.append(order)
        observations.append(dict(order=order,price=prices,reductions=deltas,old_object_gain=extra,old_object_loss=lost,qualified=qualified))
    save(BASE/'hardware-pilot.json',dict(eligible_for_independent_confirmation=not reject,rejected=reject,primary='edit',observations=observations))


def pack():
    checked.OUT=BASE;target=BASE/'meter'
    if (meter.LOG/'calibration').is_dir():
        target.mkdir(exist_ok=True);shutil.copytree(meter.LOG/'calibration',target/'calibration')
    checked.pack()

if __name__=='__main__':
    command=sys.argv[1];checked.governance();need(PROTOCOL['order']==['PC','CP'],'unregistered pilot order')
    if command=='host':checked.host('Whole-command Ruff library-test instructions')
    elif command=='setup':setup()
    elif command=='block':
        block=int(sys.argv[2]);need(block in (0,1),'unregistered pair')
        for role in PROTOCOL['order'][block]:history(block,role)
    elif command=='finish':finish()
    elif command=='pack':pack()
    else:raise ValueError(command)
