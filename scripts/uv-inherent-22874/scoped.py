"""Price the exact unwrapped compiler processes on a separate restored first edit."""
import os,shutil,subprocess,sys
from pathlib import Path
import core as c
m=c.m;P=c.P;METER=c.HERE/'thread-meter';DRIVER=m.load('native_selected_rustcs',METER/'per_rustc.py')
def machine():
 return {'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'cpus':sorted(os.sched_getaffinity(0))}
def cal_raw(dest):
    rec=m.read(dest/"calibration.json")
    assert rec["reexec_rejected"] is True
    rows=rec["known_two_instruction_loop"]
    assert set(rows)=={"serial","threads","fork"}
    n,many=3_000_000,14_000_000
    for mode,factor in (("serial",1),("threads",3),("fork",0)):
        vals=[]
        for x in (n,many):
            p=dest/f"{mode}-{x}";rep=m.read(p/"per-rustc.json")
            req=m.read(dest/f"{mode}-{x}.json")
            assert set(rep["targets"])=={"probe"} and req["command"]==req["selectors"]["probe"]
            row=rep["targets"]["probe"]
            assert all(row[k]==v for k,v in DRIVER.read_counter(bytes.fromhex(row["raw_hex"])).items())
            events=m.read(p/"kernel-events.json");tree=DRIVER.EVENTS["decode"](events)
            assert row["pid"]==tree["root"]==rep["root"] and tree["exits"][row["pid"]]==0
            assert len([e for e in tree["images"]if e["pid"]==row["pid"] and e["argv"]==req["command"]])==1
            forks=[e[1]>>16 for e in events["events"] if isinstance(e[1],int) and os.WIFSTOPPED(e[1]) and e[0]==events["root"]]
            assert mode!="threads" or forks.count(3)==3
            assert mode!="fork" or forks.count(1)+forks.count(2)==1
            assert (p/"stdout").read_bytes()==f"completed {mode} {x}\n".encode()
            vals.append(row["instructions"])
        want=2*factor*(many-n);delta=vals[1]-vals[0]
        assert abs(delta-want)<=100_000 and rows[mode]=={"counts":vals,"measured_delta":delta,"expected_delta":want}
    assert b"measured process executed a second image" in (dest/f"reexec-{n}.stderr").read_bytes()
    assert not (dest/f"reexec-{n}/per-rustc.json").exists()
    return rows


def calibrate():
 w,tmp=c.host();p=w/'trait-results/per-rustc-calibration';p.mkdir();kit=tmp/'inventory-rustc-meter';kit.mkdir();base=m.read(w/'trait-results/calibration.json')['ready']
 c.guard(machine()=={'boot':base['boot'],'cpus':base['affinity']},'PMU host or CPU set')
 c.guard(all(m.filesha(METER/f)==v for f,v in P['meter_files'].items()),'changed calibrated native meter')
 args=['/usr/bin/cc','-O2','-Wall','-Wextra','-Werror'];lib=kit/'libohm_pmu.so';load=kit/'workload'
 subprocess.run([*args,'-fPIC','-shared',METER/'pmu.c','-o',lib],check=True);subprocess.run([*args,'-pthread',METER/'workload.c','-o',load],check=True)
 subprocess.run([sys.executable,'-ISB',METER/'per_rustc.py','calibrate',p,lib,load],check=True,timeout=240);cal_raw(p)
 for f in(lib,load):shutil.copyfile(f,p/f.name)
 m.save(p/'source.json',{'host':machine(),'library':m.filesha(lib),'fixture':m.filesha(load),'sources':P['meter_files']})
def read(path,req):
 guard=c.guard;raw=m.read(path/'per-rustc.json');ev=DRIVER.EVENTS['decode'](m.read(path/'kernel-events.json'));images=ev['images'];main=images[0];meta=m.read(path/'images.json')
 guard(raw['scope']=='retired userspace instructions in the selected process and its threads'and raw['root']==ev['root']==main['pid']and ev['exits'][main['pid']]==0,'wrong process lifetime')
 guard(main['exe']==req['command'][0]and main['argv']==req['command']and main['file']==meta['cargo_file'],'wrong root image or invocation')
 compiler=req['compiler_path'];seen={}
 for i in images:
  args=i.get('argv')or []
  if i['file']!=meta['rustc_file']and Path(i['exe']).name!='rustc'and not(args and Path(args[0]).name=='rustc'):continue
  guard(i['file']==meta['rustc_file']and i['exe']==compiler and args and args[0]==compiler and ev['exits'].get(i['pid'])==0,'foreign compiler image or failure')
  if args==[compiler,'-vV']:continue
  guard('--crate-name'in args,'unexpected compiler invocation');label=args[args.index('--crate-name')+1]
  guard(label not in seen and req['selectors'].get(label)==args,'incomplete or different true rustc argv');seen[label]=i['pid']
 guard(set(seen)==raw['targets'].keys()==req['selectors'].keys()==set(P['edited_workspace_roster']),'wrong measured compiler set')
 guard(len(set(seen.values()))==len(seen)==len({r['event_id']for r in raw['targets'].values()}),'reused PID or event ID')
 for k,r in raw['targets'].items():
  guard(r['pid']==seen[k]and r['file']==meta['rustc_file']and r['argv']==req['selectors'][k]and r['exe']==compiler,'PID/argv/file mismatch')
  guard(all(r[n]==v for n,v in DRIVER.read_counter(bytes.fromhex(r['raw_hex'])).items()),'raw counter bytes')
 return {k:v['instructions']for k,v in raw['targets'].items()}
def measure(path,forms,runtime):
 w,tmp=c.host();p=w/'trait-results/per-rustc-calibration';kit=tmp/'inventory-rustc-meter';lib=kit/'libohm_pmu.so';cal=m.read(p/'source.json')
 c.guard(cal['host']==machine()and m.filesha(lib)==cal['library']and all(m.filesha(m.SDK/k)==v for k,v in runtime.items()),'wrong calibrated machine or SDK')
 picked={}
 for v in forms:
  c.guard(v[0]==str(m.RUSTC)and v.count('--crate-name')==v.count('--crate-type')==1 and v[v.index('--crate-type')+1]=='lib','wrong rustc unit')
  name=v[v.index('--crate-name')+1];c.guard(name not in picked,'repeated crate selector');picked[name]=v
 c.guard(picked.keys()==set(P['edited_workspace_roster']),'true typed native roster changed; requires adjudication')
 request={'command':c.CHECK,'environment':m.ENV,'cwd':str(m.SRC),'compiler_path':str(m.RUSTC),'selectors':picked};req=path.parent/'scoped-request.json';m.save(req,request);path.mkdir()
 pair={'cargo_file':DRIVER.EVENTS['file_id'](Path(c.CHECK[0])),'rustc_file':DRIVER.EVENTS['file_id'](m.RUSTC)}
 subprocess.run([sys.executable,'-ISB',METER/'per_rustc.py','capture',req,path,lib],env={'PATH':'/usr/bin:/bin','LC_ALL':'C'},timeout=1800,check=True)
 m.save(path/'images.json',pair);m.save(path/'counts.json',read(path,request))
 c.guard(cal['host']==machine()and all(m.filesha(m.SDK/k)==v for k,v in runtime.items()),'compiler or host changed during counted visit')
 for name in('stdout','stderr'):os.link(path/name,path/('cargo.'+name))
