"""Counterbalanced blocking, inherited and thread-only visits over a restored genuine first-edit session."""
from pathlib import Path
import gzip,json,os,re,runpy,shutil,signal,subprocess,sys,uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import CASE,HERE,LOCK,PLAN,Env,EVENTS,SIX,canon,digest,filehash,kernel,read,readz,setup,shape,write,writez
from opening import qualify,changed_forms
from semantics import products,probe,typed_compare
import fixed_products,producer_map,live_metadata
from managed_sdk import Managed
K=HERE/'kit';W=runpy.run_path(str(K/'wall_clock.py'));P=runpy.run_path(str(K/'per_rustc.py'))
def current():return Path('/proc/sys/kernel/random/boot_id').read_text().strip(),sorted(os.sched_getaffinity(0))
def clock(path):
    r=read(path);assert set(r)=={'start','stop','user_us','system_us','instructions','enabled','running','event_errno','code'}and all(type(v)is int for v in r.values())
    assert r['event_errno']==r['code']==0 and 0<r['running']<=r['enabled']and 1000*r['running']>=995*r['enabled']and r['instructions']>0 and r['start']<r['stop']and r['user_us']+r['system_us']>0;return r
def calibrate(e):
    boot,cpus=current();excluded=e.inp['excluded_boots'];assert str(uuid.UUID(boot))==boot and boot not in excluded and len(cpus)==8 and len(set(excluded))==len(excluded)>20
    out=e.results/'calibration';out.mkdir();b=e.bin_dir
    for name,flags in [('whole',['-O2','-Wall','-Werror',K/'watch.c']),('wall',['-O2','-Wall','-Werror',K/'wall_probe.c']),('libpmu.so',['-O2','-Wall','-Werror','-shared','-fPIC',K/'pmu.c']),('workload',['-O2','-Wall','-Werror','-pthread',K/'workload.c'])]:
        subprocess.run(['/usr/bin/cc',*flags,'-o',b/name],check=True)
    t=out/'scoped';t.mkdir();P['calibrate'](t,b/'libpmu.so',b/'workload');assert read(t/'calibration.json')['reexec_rejected']
    wall=W['calibrate'](out/'wall',b/'wall');assert wall['machine']['boot']==boot
    public={}
    for mode,slope in [('serial',1),('threads',3),('fork',1),('reexec',1)]:
        xs=[]
        for n in (3_000_000,14_000_000):
            z=out/(mode+'-'+str(n)+'.json');subprocess.run([b/'whole',z,b/'workload',mode,str(n)],stdout=subprocess.DEVNULL,check=True);xs.append(clock(z)['instructions'])
        assert abs(xs[1]-xs[0]-22_000_000*slope)<100_000,(mode,xs);public[mode]=xs
    assert current()==(boot,cpus);d={'boot':boot,'cpus':cpus,'excluded':excluded,'whole':public,'scoped':filehash(t/'calibration.json'),'blocking':filehash(out/'wall/passed.json'),'binaries':{n:filehash(b/n)for n in ('whole','wall','libpmu.so','workload')},'protocol':CASE['protocol']};write(out/'accepted.json',d);return d
def stamps(e):
    paths=subprocess.check_output(['git','-C',e.src,'ls-files','-z'],env=e.env).split(b'\0');return {os.fsdecode(n):(e.src/os.fsdecode(n)).lstat().st_mtime_ns for n in paths if n}
def targetsha(root):
    rows=[];aliases={}
    for f in sorted(root.rglob('*')):
        name=str(f.relative_to(root))
        if f.is_symlink():rows.append([name,'symlink',os.readlink(f)])
        elif f.is_file():
            s=f.stat();first=aliases.setdefault((s.st_dev,s.st_ino),name)
            rows.append([name,first,s.st_mode&0o7777,s.st_mtime_ns,s.st_size,filehash(f)])
    return digest(canon(rows))
def copy_target(source,dest):
    copied={}
    def copy_file(src,dst):
        stat=os.stat(src);key=(stat.st_dev,stat.st_ino)
        if stat.st_nlink>1 and key in copied:os.link(copied[key],dst)
        else:
            shutil.copy2(src,dst)
            if stat.st_nlink>1:copied[key]=dst
        return dst
    shutil.copytree(source,dest,dirs_exist_ok=True,symlinks=True,copy_function=copy_file)
def seed(e,location):
    assert not location.exists();copy_target(e.target,location);h=targetsha(e.target);assert targetsha(location)==h;return stamps(e),h
def restore(e,location,stamp):
    e.source('A');assert e.target.parent==e.root and location.parent==e.bank and not location.is_symlink()
    for n,mtime in stamp[0].items():
        f=e.src/n;s=f.lstat()
        if s.st_mtime_ns!=mtime:os.utime(f,ns=(s.st_atime_ns,mtime),follow_symlinks=False)
    e.reset();copy_target(location,e.target);assert targetsha(e.target)==stamp[1] and stamps(e)==stamp[0]
def verify_scoped(e,d,forms):
    events=EVENTS['decode'](read(d/'kernel-events.json'));raw=read(d/'per-rustc.json');assert events['exits'][events['root']]==0 and events['images'][0]['argv']==e.argv
    fid=EVENTS['file_id'](e.bin);actual={z['pid']:z for z in events['images']if z['file']==fid};assert len(actual)==6 and set(raw['targets'])==set(SIX)and len({r['event_id']for r in raw['targets'].values()})==6
    for name,row in raw['targets'].items():
        pid=row['pid'];assert actual[pid]['argv']==forms[name][0]==row['argv']and events['exits'][pid]==0 and row['file']==fid
        assert all(row[k]==v for k,v in P['read_counter'](bytes.fromhex(row['raw_hex'])).items())and 1000*row['time_running_ns']>=995*row['time_enabled_ns']
    writez(d/'kernel.json.gz',read(d/'kernel-events.json'));(d/'kernel-events.json').unlink();return {n:r['instructions']for n,r in raw['targets'].items()}
def capture(e,state,mode,d,forms,mask):
    assert e.source(state)==CASE['states'][state]['source']and current()==mask
    if mode=='wall':
        rec=W['command'](d,e.argv,'native',e.src,e.env,seconds=1500);assert rec['exit']==0 and not rec['deadline_fired'];answer=rec['ns']
    elif mode=='whole':
        d.mkdir()
        with (d/'cargo.stdout').open('xb')as out,(d/'cargo.stderr').open('xb')as err:subprocess.run([e.bin_dir/'whole',d/'whole.json',*e.argv],cwd=e.src,env=e.env,stdout=out,stderr=err,check=True,timeout=1500)
        answer=clock(d/'whole.json')['instructions']
    elif mode=='scoped':
        d.mkdir();request={'compiler_path':str(e.bin),'selectors':{k:x[0]for k,x in forms.items()},'command':e.argv,'environment':e.env,'cwd':str(e.src)};P['capture'](request,d,e.bin_dir/'libpmu.so');writez(d/'request.json.gz',request);answer=verify_scoped(e,d,forms)
    else:raise ValueError(mode)
    stderr=(d/('stderr'if mode=='scoped'else'cargo.stderr')).read_bytes();stdout=(d/('stdout'if mode=='scoped'else'cargo.stdout')).read_bytes();assert not stdout and b'Finished 'in stderr and current()==mask;return answer
def arm(e,role,armname,index,cal,ref):
    mask=(cal['boot'],cal['cpus']);assert current()==mask;e.choose(role);e.source('A');e.reset();d=e.results/'pairs'/str(index+1)/armname;d.mkdir(parents=True);cold=kernel(e,d/'cold-A','cold');assert producer_map.same_raw_roster(cold['forms'],ref['_cold_forms']);paths=cold['workspace_rmeta_from_argv'];base=products(e,paths);kernel(e,d/'noedit-A','unchanged');assert products(e,paths)==base;archive=e.bank/('single-'+armname);a=seed(e,archive);write(d/'seed.json',{'target_bytes_modes_times_sha256':a[1],'all_source_mtimes_sha256':digest(canon(a[0])),'cold_executable_identity':EVENTS['file_id'](e.bin),'source_tree':CASE['states']['A']['tree'],'cold_source':CASE['states']['A']['source']})
    golden={};form={};rows={};ordinary={};expected=fixed_products.paths(paths);orders=PLAN['pairs']['visit_orders_by_pair'][index].split('-');assert orders[0]=='native'and set(orders)=={'native','scoped','whole','wall'}
    for mode in orders:
        restore(e,archive,a)
        for state in 'BCD':
            e.source(state);dest=d/(mode+'-'+state)
            if mode=='native':
                before=fixed_products.ordinary_stats(e.target)
                rec=kernel(e,dest,'edited');form[state]=changed_forms(rec);assert form[state]==ref[state][2],(role,index,state,'literal per-role argv changed');assert rec['workspace_rmeta_from_argv']=={n:paths[n]for n in SIX};golden[state]=products(e,paths,store=True);writez(dest/'products.json.gz',golden[state]);oracle=probe(e,state,form[state],dest)
                fixed_products.changed(before,fixed_products.ordinary_stats(e.target),expected);ordinary[state]=fixed_products.recorded(e.target,expected);writez(dest/'fixed-products.json.gz',ordinary[state])
                cert=ref[state][1];coverage={n:r['coverage']for n,r in cert['covered'].items()}if cert else {}
                reference=(ref['_cold_forms'],ref[state][2],ref[state][3])
                assert live_metadata.qualify(e,role,state,dest,paths,cold['forms']|rec['forms'],reference,golden[state],ref[state][0],oracle,coverage)['accepted'];kernel(e,d/('noedit-'+state),'unchanged');assert products(e,paths)==golden[state]
            else:
                value=capture(e,state,mode,dest,form[state],mask);observed=products(e,paths);assert observed==golden[state],(role,index,state,mode,'same-seed product mismatch');writez(dest/'products.json.gz',observed);rows.setdefault(state,{})[mode]=value
                stable=fixed_products.recorded(e.target,expected);assert stable==ordinary[state],(role,index,state,mode,'Cargo fixed output mismatch');writez(dest/'fixed-products.json.gz',stable)
    shutil.rmtree(archive);result={'pair':index+1,'arm':armname,'compiler':role,'seed_target':a[1],'boot':mask[0],'hold':1+index//4,'values':rows,'argument_surface':{k:{n:shape(x[0])for n,x in by.items()}for k,by in form.items()}};writez(d/'complete.json.gz',result);return result
def main(cfg,e=None):
    e=e or Managed(cfg);gate=read(e.results/'qualification/accepted.json');assert gate['suitable_to_score']and gate['plan']==CASE['protocol']and gate['treatment']=='F'and gate['control']in('S','R')
    live=read(e.results/'fresh-publication.json');assert live['immutable']and not live['draft']and not live['prerelease']and live['id']==PLAN['control']['published_at_freeze']['id']and live['tag_name']==LOCK['release']['tag'];cal=read(e.results/'calibration/accepted.json');lookup={'P':gate['control'],'T':'F'}
    base=e.results/'qualification';control=base/('signed-1'if gate['control']=='R'else'corrected')
    assert producer_map.compare(control,base/'treatment')==readz(base/'producer-bijection.json.gz'), 'genuine source/PID/argv qualification required before scoring'
    fresh={}
    for char,role in lookup.items():
        folder=e.results/'qualification'/('treatment'if char=='T'else('signed-1'if role=='R'else'corrected'));fresh[char]={}
        fresh[char]['_cold_forms']=readz(folder/'cold-A/argv.json.gz')['forms']
        for st in 'BCD':
            dr=folder/('fresh-'+st);cf=dr/'fixed/fixed-input.json.gz';cert=readz(cf)if cf.is_file()else None
            assert cert is None or(cert['role']==role and cert['source']==CASE['states'][st]['source']and cert['state']==st and cert['rule']==filehash(HERE/'fixed-layout-rule.json'))
            fresh[char][st]=(readz(dr/'products.json.gz'),cert,readz(folder/('warm-'+st)/'argv.json.gz')['forms'],readz(dr/'argv.json.gz')['forms'])
    barrier=read(e.results/'compatibility.json');assert barrier['eligible']and barrier['roles']==[lookup['P'],'F']and barrier['runtime']=={k:LOCK['roles'][v]['hash']for k,v in lookup.items()}
    for i,order in enumerate(PLAN['pairs']['pair_orders']):
        visits=[arm(e,lookup[k],k,i,cal,fresh[k])for k in order];assert visits[0]['argument_surface']==visits[1]['argument_surface'],('unexpected cross-arm argument surface',i)
    from score import replay
    write(e.results/'result.json',replay(e.results));e.close()
if __name__=='__main__':
    cfg=read(sys.argv[2]);e=Env(cfg)
    if sys.argv[1]=='setup':setup(e)
    elif sys.argv[1]=='qualify':qualify(e)
    elif sys.argv[1]=='calibrate':calibrate(e)
    elif sys.argv[1]=='panel':
        managed=Managed(cfg)
        try:main(cfg,managed)
        finally:managed.home()
    else:raise SystemExit('setup|qualify|calibrate|panel config.json')
