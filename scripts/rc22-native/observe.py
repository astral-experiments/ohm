"""Cross-check kernel process identity, real registry dep-info and the resulting whole native executable."""
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *
from fixture import APP,LIB

def import_helpers():
    global evidence,apple,cgu
    sys.path.insert(0,str(seed('marker-reader')/'scripts/ohm-musl-ast-pair/v2'))
    import evidence
    if host()==APPLE:
        sys.path.insert(0,str(seed('apple-reader')/'scripts/ohm-apple-zmij'))
        import provider_edges as apple, cgu_inputs as cgu

def keep(out,blob):
    key=hashlib.sha256(blob).hexdigest();f=out/(key+'.gz')
    if not f.exists():f.write_bytes(gzip.compress(blob,compresslevel=2,mtime=0))
    require(gzip.decompress(f.read_bytes())==blob,'CAS readback');return key

class Native:
    def __init__(self,root):
        self.host=host();self.root=root;self.apple=None
        if self.host==APPLE:
            from execs import ExecTrace
            self.apple=ExecTrace();self.apple.ready()
        else:
            k=seed('kernel-reader')/'scripts/branch-return-execstop/kernel';sys.path.insert(0,str(k))
            import read_events
            self.reader=read_events.read;self.observer=root/'tools/observe';self.observer.parent.mkdir()
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',k/'observe.c','-lcrypto','-o',self.observer],check=True)
    def command(self,cmd,out,cwd,env):
        with (out/'stdout').open('xb') as so,(out/'stderr').open('xb') as se:
            if self.apple:
                code,rows=self.apple.command(cmd,env=env,cwd=cwd,out=so,err=se)
                observed=[{'pid':r['pid'],'path':r['path'],'argv':r['argv'],'ppid':r['ppid'],'seq':r['seq'],'cdhash':r['cdhash']} for r in rows]
            else:
                native=out/'kernel.tsv';pr=subprocess.run([self.observer,native,'--',*cmd],env=env,cwd=cwd,stdout=so,stderr=se,timeout=900)
                code=pr.returncode;j=self.reader(native,expected_code=code)
                observed=[{'pid':r['pid'],'path':r['exe'],'argv':r['argv'],'image':r['image'],'ordinal':r['ordinal'],'lifetime':r['lifetime']} for r in j['execs']]
                with native.open('rb') as i,gzip.open(str(native)+'.gz','wb',compresslevel=2) as o:shutil.copyfileobj(i,o)
                native.unlink()
        stdout=(out/'stdout').read_bytes();stderr=(out/'stderr').read_bytes()
        for f,data in [('stdout',stdout),('stderr',stderr)]:
            (out/(f+'.gz')).write_bytes(gzip.compress(data,mtime=0));(out/f).unlink()
        save(out/'exec.json',observed);return code,stdout,stderr,observed
    def close(self):
        if self.apple:self.apple.close()

def actual(rows,path):
    p=Path(path).resolve(strict=True);wanted=ident(p)
    hits=[r for r in rows if Path(r['path']).is_file() and Path(r['path']).samefile(p)]
    for r in hits:
        if 'image' in r:
            s=r['image'];require((s['dev'],s['ino'],s['size'],s['sha256'])==(wanted['dev'],wanted['ino'],wanted['bytes'],wanted['sha256']),'unrelated image for '+str(p))
    return hits

def markers(typed,kind,work,store):
    result={};primary=None
    for row in typed:
        if row['reason']!='compiler-artifact' or 'lib' not in row['target']['kind']:continue
        name=row['target']['name'];pkg=row['package_id']
        if not pkg.startswith('registry+'):continue
        rlib,=[Path(p) for p in row['filenames'] if p.endswith('.rlib')]
        require(rlib.is_file() and rlib.name.startswith('lib'+name+'-') and rlib.parent.name=='out',str(rlib))
        dep=rlib.with_name(rlib.name[3:-5]+'.d');record=rlib.parent.parent/'fingerprint'/('dep-lib-'+name)
        for p in (dep,record):require(p.is_file() and p.resolve().is_relative_to(work/'shared'),('absent or foreign producer record',p))
        raw=dep.read_bytes();translated=record.read_bytes()
        rules=evidence.raw_rule(dep,raw);require(rules is not None,'raw .d must be compiler-owned')
        encoded=evidence.encoded(translated)
        source=Path(row['target']['src_path']);require(source.is_file() and source.resolve().is_relative_to(work/'registry/registry/src'),'not registry source')
        data={'crate':name,'package':pkg,'features':row['features'],'fresh':row['fresh'],'raw':{**ident(dep),'cas':keep(store,raw),'rules':rules},'record':{**ident(record),'cas':keep(store,translated),'LNK1':encoded['LNK1'],'markers':encoded['markers']},'rlib':ident(rlib),'source':ident(source)}
        require(name not in result,'ambiguous producer');result[name]=data
        if name==kind:primary=data
    require(primary is not None and ('#'+kind+'@'+LOCKED[kind][0]) in primary['package'],'wrong active registry producer')
    wanted=evidence.V1 if kind=='zmij' else evidence.V2
    require(primary['raw']['rules']==[wanted],'physical release producer disagrees with source prediction')
    require(all(not v['raw']['rules'] for k,v in result.items() if k!=kind),'another marker can force this binary')
    return result

def visit(out,root,work,src,sdk,env,role,kind,registered,observer,previous):
    out.mkdir(parents=True);store=root/'receipts/cas'
    cmd=['cargo','+ohm','build','--locked','--offline','-j4','--message-format=json']
    code,stdout,stderr,rows=observer.command(cmd,out,src,env)
    require(code in (0,101),('not a native Cargo exit',code))
    typed=[json.loads(line) for line in stdout.splitlines() if line.strip()]
    require(typed and typed[-1]=={'reason':'build-finished','success':code==0},'incomplete Cargo JSON')
    cargo=actual(rows,sdk/'bin/cargo');require(any('build' in r['argv'] and '--offline' in r['argv'] for r in cargo),'Cargo root did not run')
    rust=actual(rows,sdk/'bin/rustc')
    rcs=[{'crate':r['argv'][r['argv'].index('--crate-name')+1],'argv':r['argv'],'pid':r['pid']} for r in rust if '--crate-name' in r['argv']]
    native=registered['native_linkers'][0];linkpath=(sdk/native['path']) if host()==GNU else Path(run(['/usr/bin/xcrun','-f','ld'])).resolve(strict=True)
    require(sha(linkpath)==native['sha256'],'platform linker differs from SDK admission')
    links=actual(rows,linkpath)
    # Xcode may run this executable from a selected -ld alias; identity still comes from the kernel.
    final=[r for r in links if any(LIB in a and (a.startswith('-l') or a.endswith('.a')) for a in r['argv'])]
    require(len(final)<=1,('several terminal links',len(final)))
    info=None
    if final:
        a=final[0]['argv'];q=[a[i+1] for i,s in enumerate(a[:-1]) if s=='-o'];require(len(q)==1,'linker output')
        search=[a[i+1] if arg=='-L' else arg[2:] for i,arg in enumerate(a) if arg.startswith('-L')]
        early,late=(str(src.parent/'native'/k) for k in ('early','late'))
        require(early in search and late in search and search.index(early)<search.index(late),('provider order',search))
        info={'output':q[0],'argv':a,'image_sha256':native['sha256'],'pid':final[0]['pid'],'search':search}
    m=markers(typed,kind,work,store)
    pm=m[kind];want=pm['raw']['rules'][0];expect=None if role=='pinned' and want==evidence.V1 else want
    require(pm['record']['LNK1']==expect and pm['record']['markers']==([want] if expect else []),('unexpected active Cargo encoding',pm['record']))
    # The build-script unit is never a surrogate native provider watcher.
    script,=[t for t in typed if t['reason']=='build-script-executed' and t['package_id'].endswith('#'+APP+'@0.1.0')]
    native_dirs=['native='+str(src.parent/'native'/n) for n in ('early','late')]
    require(script['linked_paths']==native_dirs and not script['linked_libs'],'wrong Cargo native-search graph')
    run_dir=Path(script['out_dir']).parent/'run'
    require(run_dir.resolve().is_relative_to(work/'target') and run_dir.name=='run','foreign build-script output directory')
    directives=(run_dir/'stdout').read_bytes()
    require(directives.decode().splitlines()==['cargo:rustc-link-search='+n for n in native_dirs]+['cargo:rerun-if-changed=build.rs'],'external input was watched or another directive changed the graph')
    outs=[keep(store,directives)]
    error_codes=[r['message']['code']['code'] for r in typed if r['reason']=='compiler-message' and r['message'].get('code')]
    errors=(stdout+b'\n'+stderr).decode(errors='replace')
    image=value=cgu_proof=None
    if code==0:
        leaf,=[r for r in typed if r['reason']=='compiler-artifact' and r['target']['name']==APP and r['target']['kind']==['bin']]
        exe=Path(leaf['executable']);require(exe.is_file() and exe.resolve().is_relative_to(work/'target'),'invalid Cargo product')
        b=exe.read_bytes();image=keep(store,b)
        if info:
            linker_out=Path(info['output'])
            require(linker_out.is_file() and sha(linker_out)==image,'promoted output differs from actual link')
        proc=subprocess.run([exe],cwd=src,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
        origins={v:f'OHM_RC22_SELECTED_NATIVE_IMAGE_{v}'.encode() for v in (17,29,41)}
        value=next((v for v,tag in origins.items() if proc.stdout==str(v).encode()+b' '+tag+b'\n'),None)
        require(proc.returncode==0 and not proc.stderr and value is not None and all((tag+b'\0' in b)==(v==value) for v,tag in origins.items()),'incorrect native body or runtime')
        save(out/'runtime.json',{'exit':proc.returncode,'stdout':proc.stdout.decode(),'sha256':image})
        if host()==APPLE:
            if info:cgu_proof=cgu.witness(root,out,b,info['output'],linker=info['argv'])
            else:
                require(image in previous,'no prior physical Apple link for returned program');cgu_proof=previous[image]
            previous[image]=cgu_proof
        else:require(b.startswith(b'\x7fELF'),'not GNU ELF')
    row={'role':role,'command':cmd,'code':code,'value':value,'image':image,'final':info,'rustc':rcs,
         'registry':m,'xcode_cgu':cgu_proof,'build_script_outputs':sorted(set(outs)),'diagnostic_codes':error_codes,
         'native_error':LIB in errors or 'qa_rc22_value' in errors,'raw_mark':want,'translated_mark':expect,'all_physical_linkers':len(links)}
    save(out/'observed.json',row);return row
