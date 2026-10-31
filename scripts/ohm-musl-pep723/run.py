"""Run the structural Ruff #26693 P/C control after authenticating a previously admitted SDK."""
import argparse, gzip, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, tomllib
from pathlib import Path

HERE=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location("traces",HERE/"native_trace.py");traces=importlib.util.module_from_spec(sp);sp.loader.exec_module(traces)
PLAN=json.loads((HERE/'plan.json').read_bytes()); SRC=json.loads((HERE/'source.json').read_bytes()); T='x86_64-unknown-linux-musl'
N='ruff_python_ast'; LOCKED={'zmij','compact_str'}; ADDED={'script::tests::'+n for n in SRC['new']['tests_in_this_file']}
def check(ok,why):
    if not ok:raise ValueError(why)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(p):return json.loads(Path(p).read_bytes())
def save(p,x):
    tmp=p.with_suffix('.writing');tmp.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n');tmp.replace(p)
def zipraw(p,b):p.write_bytes(gzip.compress(b,mtime=0,compresslevel=4));return digest(b)
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*map(str,args)]).decode().strip()
def source_versions(root):
    versions={}
    for role in ('old','new'):
        record=SRC[role]
        versions[role]={'rev':record['commit'],'tree':git(root,'rev-parse',record['commit']+'^{tree}'),'lock':record['cargo_lock_sha256']}
    return versions
def body(p):return [sha(p),p.stat().st_size,p.stat().st_mode&0o777]
def check_rustdoc(enrolled,admission,parent,dkey):
    members=HERE/'C-rustdoc-source-components.json'
    check(sha(members)=='91e99bcc12bda4e8786420718fd0e7b12d94f3a17de1bd63f6caac4738e35f27','original rustdoc source-build record')
    components=load(members)
    doc=admission['rustdoc'];fresh=components['all']['bin/rustdoc']
    check(doc['fresh_candidate']==fresh and doc['operational']==parent['bin/rustdoc'] and components['different_non_driver']=={'bin/rustdoc':[doc['operational'],fresh]},'both independently built rustdoc payloads')
    check(enrolled['rustdoc']==dict(doc,fresh_candidate=fresh[0]),'rustdoc hashes in the original transfer')
    check(components['parent_driver']==parent[dkey] and components['all'][dkey]==enrolled['candidate_driver'] and admission['product_driver']=={'P':parent[dkey],'C':enrolled['candidate_driver']},'physical driver pair')
def wrong_source(raw):
    key=b'if content == "///" {';prefix,test=raw.split(b'#[cfg(test)]',1)
    check(prefix.count(key)==1,'unique production site')
    return prefix.replace(key,b'if closing.is_none() && content == "///" {')+b'#[cfg(test)]'+test
def invalid_source(raw):return raw+b'\nconst _: usize = "ohm_26693_type_error";\n'

class Study:
    def __init__(self,args):
        self.args=args;self.work=args.work.resolve();self.out=args.out.resolve();self.source=self.work/'ruff'
        check(not self.work.is_relative_to(self.out) and not self.out.is_relative_to(self.work),'disjoint work/output')
        for d in (self.work,self.out):
            check(not d.exists() and d.parent.is_dir(),'fresh private work/output');d.mkdir(mode=0o700)
        self.products=self.out/'elf';self.products.mkdir();self.closed=self.work/'closed';self.closed.mkdir()
        self.kit=load(args.receipts/'sdk.json');self.roles=load(args.receipts/'guard-subjects.json')
        base=args.qa/'scripts/ohm-musl-ast-pair'
        check(git(args.qa,'rev-parse','HEAD')==PLAN['qa_head'] and all(sha(base/n)==h for n,h in PLAN['verified_input_files'].items()),'source qualification checkout')
        admission=load(HERE/'admission.json')
        check(sha(HERE/'admission.json')==PLAN['admission_sha256'] and all(os.environ.get(k)==v for k,v in admission['env'].items()),'seven admitted source/provider bindings')
        self.parent=load(base/'parent.json')['files'];check(len(self.parent)==183 and self.kit['source']==load(base/'source.json'),'source suite and parent')
        sm=self.kit['source_transfer'];check(sm==admission['source_transfer'],'qualified original transfer')
        check(self.kit['role']=='P' and self.kit['installed']==self.parent,'start from restored parent')
        check(self.roles['drivers']['P']['source']==PLAN['P'] and self.roles['drivers']['C']['source']==PLAN['C'] and self.roles['cargos']['aware']['source']==PLAN['cargo'],'product provenance')
        self.sdk=Path(self.roles['sdk']);self.driver=self.sdk/'lib'/self.roles['driver_basename'];self.files=list(self.parent);self.dkey=self.driver.relative_to(self.sdk).as_posix()
        check(sha(self.sdk/'bin/rustc')==self.roles['frontend_sha256'] and (self.sdk/'bin/cargo').samefile(self.roles['cargos']['aware']['path']),'source-bound physical tools')
        transfer_file=args.receipts.parent/'reopened/identity.json'
        check(sha(transfer_file)==sm['identity'],'physically authenticated source-transfer receipt')
        enrolled=load(transfer_file)
        check(enrolled['source']==self.kit['source'] and enrolled['base']==self.parent and (enrolled['run'],enrolled['head'],enrolled['attempt'])==(sm['run'],sm['head'],1),'fixture source to product binding')
        check_rustdoc(enrolled,admission,self.parent,self.dkey)
        check(body(Path(self.roles['drivers']['P']['path']))==self.parent[self.dkey] and body(Path(self.roles['drivers']['C']['path']))==enrolled['candidate_driver'],'two authenticated physical drivers')
        check(self.parent[self.dkey]!=enrolled['candidate_driver'] and body(self.sdk/'bin/cargo')==self.parent['bin/cargo'],'different rustc, identical aware Cargo')
        self.inodes={n:((self.sdk/n).stat().st_dev,(self.sdk/n).stat().st_ino) for n in self.files if n!=self.dkey}
        check(len(self.inodes)==182 and sha(self.driver)==self.roles['drivers']['P']['sha256'],'one driver transition')
        self.result={'source_transfer':sm,'source_and_providers':admission,'source_enrollment':sha(HERE/'source.json'),'plan':sha(HERE/'plan.json'),'common_sdk':digest(json.dumps(self.parent,sort_keys=True).encode()),'roles':{},'comparisons':{}}
        self.active=None;self.prepare()
    def space(self):
        for p in [self.work,self.out]:
            f=shutil.disk_usage(p).free;check(f>2*2**30,('capacity',p,f))
    def prepare(self):
        self.space();check(sha(HERE/'source.json')==PLAN['source_registration'],'source receipt')
        check(min(shutil.disk_usage(p).free for p in (self.work,self.out))>=8*2**30,'eight GiB after actual SDK provisioning')
        proxy=Path(shutil.which('rustup')).resolve(strict=True);shim=self.work/'bin';shim.mkdir()
        for n in ('rustup','cargo','rustc','rustdoc'):(shim/n).symlink_to(proxy)
        h=self.work/'home';h.mkdir();self.cargo_home=self.work/'cargo-home'
        private_tmp=self.work/'tmp';private_tmp.mkdir()
        self.env={'HOME':str(h),'PATH':f'{shim}:/usr/local/bin:/usr/bin:/bin','RUSTUP_HOME':str(self.sdk.parent.parent),'RUSTUP_AUTO_INSTALL':'0','CARGO_HOME':str(self.cargo_home),'CARGO_TARGET_DIR':str(self.work/'target'),'CARGO_BUILD_BUILD_DIR':str(self.work/'shared'),'CARGO_TERM_COLOR':'never','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','TMPDIR':str(private_tmp),'LC_ALL':'C','TZ':'UTC'}
        if self.args.ruff:
            subprocess.run(['git','clone','--quiet','--shared','--no-checkout',self.args.ruff,self.source],check=True)
        else:
            self.source.mkdir();git(self.source,'init','--quiet');git(self.source,'fetch','--depth=2','--no-tags','https://github.com/astral-sh/ruff.git',SRC['new']['commit'])
        check(git(self.source,'rev-parse',SRC['new']['commit']+'^')==SRC['old']['commit'],'real history')
        if self.args.archive_cache:
            donor=self.args.archive_cache.resolve(strict=True)
            check(donor.is_dir() and os.statvfs(donor).f_flag & os.ST_RDONLY,'read-only registry archive donor')
            source_cache=self.cargo_home/'registry/cache'/donor.name
            source_cache.mkdir(parents=True)
            for state in ('old','new'):
                lock=tomllib.loads(git(self.source,'show',SRC[state]['commit']+':Cargo.lock'))
                for item in lock['package']:
                    if 'checksum' not in item:continue
                    leaf=item['name']+'-'+item['version']+'.crate';stored=donor/leaf;local=source_cache/leaf
                    if stored.is_file() and not local.exists():
                        check(sha(stored)==item['checksum'],('raw source archive',leaf))
                        local.symlink_to(stored)
        out={}
        for state in ('old','new'):
            self.select(state);k=state+'-fetch';v=subprocess.run(['cargo','+ohm','fetch','--locked','--target',T],cwd=self.source,env=self.env,capture_output=True)
            out[k]=[v.returncode,zipraw(self.out/(k+'.stdout.gz'),v.stdout),zipraw(self.out/(k+'.stderr.gz'),v.stderr)]
            check(v.returncode==0,(k,v.stderr[-800:]))
        self.env['CARGO_NET_OFFLINE']='true'
        self.registry={p.name:sha(p) for p in (self.cargo_home/'registry/cache').glob('*/*.crate')}
        locked={}
        for state in ('old','new'):
            doc=tomllib.loads(git(self.source,'show',SRC[state]['commit']+':Cargo.lock'))
            for pkg in doc['package']:
                if 'checksum' in pkg:
                    leaf=pkg['name']+'-'+pkg['version']+'.crate';check(locked.setdefault(leaf,pkg['checksum'])==pkg['checksum'],leaf)
            for n,(v,h) in SRC[state]['selected_registry_inputs'].items():check(self.registry[n+'-'+v+'.crate']==h,(state,n))
        check(all(locked.get(n)==h for n,h in self.registry.items()),'every downloaded crate matches historical locks')
        self.result['preparation']=out;self.result['registry']=self.registry
        self.result['source_versions']=source_versions(self.source)
        save(self.out/'partial.json',self.result)
    def select(self,state):
        normal='old' if state=='old' else 'new';s=SRC[normal];rel=s['path']
        git(self.source,'switch','--quiet','--detach','--discard-changes',s['commit'])
        check(git(self.source,'write-tree')==s['tree'] and sha(self.source/'Cargo.lock')==s['cargo_lock_sha256'] and sha(self.source/rel)==s['file_sha256'],'complete source')
        if state in ('wrong','invalid'):
            f=self.source/rel;raw=f.read_bytes();f.write_bytes((wrong_source if state=='wrong' else invalid_source)(raw));check(sha(f)==PLAN['states'][state] and git(self.source,'diff','--name-only')==rel,state)
        else:check(not git(self.source,'diff','--name-only'),'clean')
    def activate(self,role):
        src=Path(self.roles['drivers'][role]['path']);check(sha(src)==self.roles['drivers'][role]['sha256'],role)
        if not self.driver.samefile(src):
            tmp=self.driver.with_name(self.driver.name+'.pep723-next');os.link(src,tmp);tmp.replace(self.driver)
        got={p.relative_to(self.sdk).as_posix():body(p) for p in self.sdk.rglob('*') if p.is_file()}
        check(set(got)==set(self.files) and all(got[n]==v for n,v in self.parent.items() if n!=self.dkey) and got[self.dkey][0]==sha(src),'whole SDK inventory')
        check(all(((self.sdk/n).stat().st_dev,(self.sdk/n).stat().st_ino)==pair for n,pair in self.inodes.items()),'182 unchanged physical inputs')
        for n in ['cargo','rustc','rustdoc']:
            f=Path(subprocess.check_output(['rustup','which','--toolchain','ohm',n],cwd=self.source,env=self.env).decode().strip());check(f.samefile(self.sdk/'bin'/n),n)
        trace=self.out/(role+'-driver-open.log')
        if not trace.exists():
            vv=subprocess.check_output(['strace','-f','-qq','-yy','-s','4096','-e','trace=openat,openat2','-o',trace,'rustc','+ohm','-vV'],cwd=self.source,env=self.env)
            pat=r'=\s*\d+<([^>]+)>';opened=[]
            for line in trace.read_text().splitlines():
                m=re.search(pat,line)
                if m and self.driver.name in m[1] and Path(m[1]).exists() and Path(m[1]).samefile(self.driver):opened.append(m[1])
            check(opened,(role,'loaded driver'));self.result.setdefault('role_identity',{})[role]={'rustc_vV':vv.decode(),'cargo_Vv':subprocess.check_output(['cargo','+ohm','-Vv'],env=self.env,cwd=self.source).decode(),'loaded_driver':[sha(src),src.stat().st_dev,src.stat().st_ino],'actual_opens':opened,'182_common_inode_map_sha':digest(json.dumps(self.inodes,sort_keys=True).encode())}
        self.active=role
        check(self.driver.samefile(src),'active driver has the parked physical inode')
    def park(self,label):
        where=self.closed/(self.active+'-'+label);where.mkdir()
        for n in ['target','shared']:
            d=self.work/n;check(d.is_dir() and not d.is_symlink(),(n,'owned output'));d.rename(where/n)
    def physical(self,raw,dest):
        jobs=[];links=[];found=[]
        for pid,path,a in traces.read_execs(raw)[0]:
            exe=Path(path)
            if exe.name=='cargo' and exe.samefile(self.sdk/'bin/cargo'):found.append(pid)
            only=any(x in ('-Zlink-only','link-only','-Zlink-only=yes','link-only=yes') for x in a)
            if only or ('--crate-name' in a and any(x.startswith('--emit') for x in a) and '--print' not in a):
                check(exe.samefile(self.sdk/'bin/rustc'),(pid,path))
                crate=a[a.index('--crate-name')+1] if '--crate-name' in a else None
                target=a[a.index('--target')+1] if '--target' in a else None
                row={'pid':pid,'crate':crate,'target':target,'test':'--test' in a,'mode':'cached' if only else 'full','argv':a}
                if not only and crate in LOCKED|{N} and target==T:
                    extra=[x.split('=',1)[1] for x in a if x.startswith('extra-filename=')];check(len(extra)<=1,(pid,'output suffix'))
                    f=Path(a[a.index('--out-dir')+1])/(crate+''.join(extra)+'.d')
                    if f.exists():
                        contents=f.read_bytes();d=dest/'depfiles';d.mkdir(exist_ok=True)
                        leaf=d/(digest(contents)+'.gz')
                        if not leaf.exists():zipraw(leaf,contents)
                        marker_names={'hard':b'/dev/null/ohm-untracked-relink-inputs:', 'v1':b'/dev/null/ohm-recheck-dependent-links:', 'v2':b'/dev/null/ohm-recheck-dependent-links-v2:'}
                        markers=sorted(k for k,v in marker_names.items() if v in contents.splitlines())
                        row['physical_depfile']={'digest':digest(contents),'markers':markers,'path':str(f)}
                jobs.append(row)
            if exe.name in ('ld','ld.bfd','ld.lld','rust-lld','wild'):
                links.append({'pid':pid,'path':path,'sha256':sha(exe),'output':a[a.index('-o')+1] if '-o' in a else None,'argv':a})
        check(len(found)==1,'one physical Cargo');return jobs,links
    def test_program(self,exe,state,dest):
        def visit(n,args):
            v=subprocess.run([exe,*args],cwd=self.source,env=self.env,capture_output=True,timeout=120)
            return v,{'exit':v.returncode,'argv':args,'stdout':zipraw(dest/(n+'.stdout.gz'),v.stdout),'stderr':zipraw(dest/(n+'.stderr.gz'),v.stderr)}
        li,inventory=visit('native-list',['--list'])
        names=[x.removesuffix(': test') for x in li.stdout.decode().splitlines() if x.endswith(': test')]
        expected_count=49 if state=='old' else 53
        check(li.returncode==0 and len(set(names))==len(names)==expected_count and set(names)&ADDED==(set() if state=='old' else ADDED),'real test inventory')
        full,f=visit('native-full',['--test-threads=1'])
        failing=1 if state=='wrong' else 0
        check(full.returncode==(101 if failing else 0) and re.search(rf'^test result: (?:ok|FAILED)\. {expected_count-failing} passed; {failing} failed;'.encode(),full.stdout,re.M),('all tests',state,full.stdout[-800:]))
        cases={}
        for i,n in enumerate([PLAN['anchor'],*sorted(ADDED)]):
            t,k=visit('native-'+str(i),['--exact',n])
            count=int(n in names);bad=state=='wrong' and n==PLAN['wrong_test']
            check(t.returncode==(101 if bad else 0) and re.search(rf'^running {count} tests?$'.encode(),t.stdout,re.M),('selected',state,n))
            check(re.search(rf'^test result: (?:ok|FAILED)\. {count-int(bad)} passed; {int(bad)} failed;'.encode(),t.stdout,re.M),('verdict',state,n))
            cases[n]=k|{'selected':count,'failed':int(bad)}
        content=exe.read_bytes();h=digest(content);check(content[:6]==b'\x7fELF\x02\x01' and int.from_bytes(content[18:20],'little')==62,'native architecture')
        txt=subprocess.check_output(['readelf','-lhWd',exe]);check(b'INTERP' not in txt and b'(NEEDED)' not in txt,'static product')
        fzip=self.products/(h+'.zst')
        if not fzip.exists():subprocess.run(['zstd','-q','-T1','-3',exe,'-o',fzip],check=True)
        check(digest(subprocess.check_output(['zstd','-dc',fzip]))==h,'custodied complete executable')
        return {'sha256':h,'bytes':len(content),'names':names,'inventory':inventory,'all':f,'individual':cases,'readelf':zipraw(dest/'readelf.gz',txt)}
    def visit(self,role,name,state,empty):
        self.space();dest=self.out/role/name;dest.mkdir(parents=True)
        source_sha=sha(self.source/SRC['new']['path']);record={'state':state,'source_sha':source_sha,'lock_sha':sha(self.source/'Cargo.lock'),'git_tree':git(self.source,'rev-parse','HEAD^{tree}'),'target_present':(self.work/'target').exists(),'shared_present':(self.work/'shared').exists()}
        check(record['target_present']==record['shared_present']==(not empty),(role,name,'target roots'))
        if self.active!=role:raise ValueError('wrong active role')
        trace=dest/'exec.log';cmd=PLAN['normal_argv'];pp=subprocess.run(['strace','-f','-qq','-s','131072','-e','trace=execve,execveat','-o',trace,*cmd],cwd=self.source,env=self.env,capture_output=True,timeout=1200)
        raw=trace.read_bytes();record.update(exit=pp.returncode,argv=cmd,exec=zipraw(dest/'exec.gz',raw),stdout=zipraw(dest/'stdout.gz',pp.stdout),stderr=zipraw(dest/'stderr.gz',pp.stderr));trace.unlink()
        jobs,links=self.physical(raw,dest);save(dest/'native.json',{'rustcs':jobs,'actual_linkers':links});record['native_sha256']=sha(dest/'native.json')
        events=[json.loads(s) for s in pp.stdout.splitlines()];ok=state!='invalid';check(pp.returncode==(0 if ok else 101) and events[-1]=={'reason':'build-finished','success':ok},(role,name,pp.returncode,pp.stderr[-1000:]))
        typed=[x for x in events if x['reason']=='compiler-artifact'];record['typed']=[[x['package_id'],x['target']['name'],x['fresh']] for x in typed]
        if empty:check(not any(x['fresh'] for x in typed),(role,name,'cold typed work'))
        if ok:
            one,=[x for x in typed if x['target']['name']==N and x['profile']['test'] and x['executable']];x=Path(one['executable']);check(x.is_file(),'typed executable')
            target_linkers=[v for v in links if v['output'] and Path(v['output']).name==x.name]
            record['program']=self.test_program(x,state,dest)
        else:
            tb=[x['message'] for x in events if x['reason']=='compiler-message' and (x['message'].get('code') or {}).get('code')=='E0308'];err,=tb;spans=[v for v in err['spans'] if v['is_primary']];at,=spans
            check(at['file_name'].endswith(SRC['new']['path']) and at['line_start']==PLAN['E0308']['line'] and [at['byte_start'],at['byte_end']]==[PLAN['E0308']['byte_start'],PLAN['E0308']['byte_end']] and '"ohm_26693_type_error"' in at['text'][0]['text'],(role,name,at))
            record['diagnostic']={'code':'E0308','message':err['message'],'span':[at['file_name'],at['line_start'],at['column_start'],at['line_end'],at['column_end'],at['byte_start'],at['byte_end'],at['label']],'rendered':err['rendered']}
            target_linkers=[v for v in links if v['output'] and re.match(r'ruff_python_ast-[a-f0-9]+$',Path(v['output']).name)]
        if name not in ('unchanged','settled') and ok:check(len(target_linkers)==1,(role,name,'relinked root'))
        if not ok:check(not target_linkers,(role,name,'wrong Rust must fail before native link'))
        check(all(Path(v['path']).resolve()==Path('/usr/bin/ld').resolve() for v in target_linkers),(role,name,'ordinary musl target linker'))
        record['roster']={'full':[[v['crate'],v['target'],v['test']] for v in jobs if v['mode']=='full'],'cached':[[v['crate'],v['target'],v['test']] for v in jobs if v['mode']=='cached'],'all_linkers':[v['path'] for v in links],'target_linkers':[v['path'] for v in target_linkers],'leaf_markers':{v['crate']:v['physical_depfile']['markers'] for v in jobs if v.get('target')==T and v['crate'] in LOCKED and 'physical_depfile' in v}}
        if empty and ok:
            marker=['hard'] if role=='P' else ['v2'];check(record['roster']['leaf_markers']=={n:marker for n in LOCKED},(role,name,record['roster']['leaf_markers']))
        save(dest/'visit.json',record);self.result['roles'][role][name]=record;save(self.out/'partial.json',self.result)
        print(role,name,'Cargo',record['exit'],'typed',len(typed),'full/cached/root-ld',len(record['roster']['full']),len(record['roster']['cached']),len(target_linkers),flush=True)
    def run_role(self,role):
        self.activate(role);self.result['roles'][role]={};prev=None
        for nm,state in zip(PLAN['venues'],['old','new','new','new','wrong','invalid','new','new','old','wrong','invalid'],strict=True):
            empty=nm=='old' or nm.startswith('empty-')
            if nm.startswith('empty-'):self.park('before-'+nm)
            if prev!=state:self.select(state)
            self.visit(role,nm,state,empty);prev=state
        self.park('final');r=self.result['roles'][role]
        own={}
        for a,b in [('old','empty-old'),('edit','unchanged'),('unchanged','settled'),('edit','repair'),('edit','empty-new'),('wrong','empty-wrong')]:
            aa,bb=r[a]['program'],r[b]['program'];own[a+'/'+b]={'whole_elf':aa['sha256']==bb['sha256'],'all_inventory':aa['names']==bb['names'] and aa['inventory']['stdout']==bb['inventory']['stdout']}
        own['invalid/empty-invalid']={'full_diagnostic':r['invalid']['diagnostic']==r['empty-invalid']['diagnostic']}
        self.result.setdefault('within_role',{})[role]=own
        save(self.out/'partial.json',self.result)
        check(len({r[n]['program']['sha256'] for n in ('old','edit','wrong')})==3,(role,'three different behaviors'))
        check(set(r['edit']['program']['names'])-set(r['old']['program']['names'])==ADDED and not set(r['old']['program']['names'])-set(r['edit']['program']['names']),(role,'four named additions'))
        check(self.registry=={p.name:sha(p) for p in (self.cargo_home/'registry/cache').glob('*/*.crate')},'registry byte identity')
    def finish(self):
        for role in 'PC':self.run_role(role)
        self.activate('P');p,c=(self.result['roles'][n] for n in 'PC')
        for phase in PLAN['venues']:
            if 'program' in p[phase]:
                a,b=(v[phase]['program'] for v in (p,c));self.result['comparisons'][phase]={'exact_elf':a['sha256']==b['sha256'],'complete_inventory':a['names']==b['names'] and a['inventory']['stdout']==b['inventory']['stdout'],'all_tests':a['all']['exit']==b['all']['exit'],'named_native_cases':all(a['individual'][n]['failed']==b['individual'][n]['failed'] and a['individual'][n]['selected']==b['individual'][n]['selected'] for n in ADDED|{PLAN['anchor']})}
            else:self.result['comparisons'][phase]={'exact_diagnostic':p[phase]['diagnostic']==c[phase]['diagnostic']}
        self.result['endpoints']={role:{nm:self.result['roles'][role][nm]['roster'] for nm in ('edit','unchanged','settled')} for role in 'PC'}
        save(self.out/'terminal.json',self.result)
        same_role=all(all(row.values()) for one in self.result['within_role'].values() for row in one.values())
        check(same_role and all(all(d.values()) for d in self.result['comparisons'].values()),'mismatch retained in terminal.json and complete ELF bodies; withhold comparison pending explanation')
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--qa',type=Path,required=True);ap.add_argument('--receipts',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--ruff',type=Path,help='existing genuine Git clone holding the two public Ruff revisions (optional, otherwise fetch from astral-sh/ruff)')
    ap.add_argument('--archive-cache',type=Path,help='optional read-only registry/cache/SOURCE_ID containing raw .crate files; every selected file must match the real locks')
    args=ap.parse_args();s=Study(args)
    try:s.finish()
    finally:
        if not s.driver.samefile(s.roles['drivers']['P']['path']):s.activate('P')
if __name__=='__main__':main()
