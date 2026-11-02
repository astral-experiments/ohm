"""Reopen the original six GitHub worker archives before scoring a single ordinary Ruff edit."""
import argparse, collections, contextlib, gzip, hashlib, itertools, json, math, mmap, os, re, shutil, statistics, stat, struct, subprocess, sys, tarfile, tempfile, zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import role_graph, normal_registry

def need(value,reason):
    if not value:raise ValueError(reason)

def read_json(path):return json.loads(path.read_bytes())
def sha(path):
    with path.open('rb')as fd:return hashlib.file_digest(fd,'sha256').hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
H=read_json(HERE/'hardware.json');C=read_json(HERE/'confirmation.json');M=read_json(HERE/'matched.json');SCHEMA=read_json(HERE/'role-schemas.json');PRIOR=read_json(HERE/'prior-natively-executed.json');CMD=['cargo','+ohm','test','--no-run','-p','ruff_db','--lib','--locked','--offline','-j2','--message-format=json'];REG='e6b51ac24de2407057a1e62f77c748cd247bd37e515fb086c9da12ad94eb968c';WILD='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5';HEAD='34a6dc52b4543454e7512018ce0586a562d8a03c';RUN=41442143564

class Raw:
    def __init__(self,tf,tmp):
        self.tf=tf;self.tmp=tmp;self.proved=set();members=tf.getmembers();need(len(members)<2000 and all((x.isfile()or x.isdir())and Path(x.name).parts[0]=='receipt'and '..'not in Path(x.name).parts and not Path(x.name).is_absolute()for x in members),'unsafe stored tar');self.entries={x.name.removeprefix('receipt/'):x for x in members if x.isfile()};need(len(self.entries)==sum(x.isfile()for x in members),'duplicate stored path')
    def read(self,n):
        member=self.entries[n];need(member.size<100<<20,'oversized record');return self.tf.extractfile(member).read()
    def json(self,n):return json.loads(self.read(n))
    def graph(self,n,target):
        with self.tf.extractfile(self.entries[n])as f,gzip.GzipFile(fileobj=f)as g,target.open('wb')as out:shutil.copyfileobj(g,out,1<<20)
        need(target.stat().st_size<96<<20,'oversized compiler file')
    def cas(self,h):
        need(re.fullmatch('[a-f0-9]{64}',h),'bad native identity');out=self.tmp/h
        if not out.exists():
            packed=self.tmp/'one.zst';packed.write_bytes(self.read('native/'+h+'.zst'))
            with out.open('xb')as fd:subprocess.run(['zstd','-q','-d','-c',str(packed)],stdout=fd,check=True,timeout=90)
            packed.unlink()
        need(out.stat().st_size<64<<20 and sha(out)==h,'wrong physical native CAS bytes');return out

    def prove(self,h):
        if h in self.proved:return
        need(re.fullmatch('[a-f0-9]{64}',h),'bad digest key');packed=self.tmp/'stream-input.zst';packed.write_bytes(self.read('native/'+h+'.zst'))
        with subprocess.Popen(['zstd','-q','-d','-c',str(packed)],stdout=subprocess.PIPE)as proc:
            got=hashlib.file_digest(proc.stdout,'sha256').hexdigest();need(proc.wait(timeout=60)==0 and got==h,'physical native machine bytes differ')
        packed.unlink();self.proved.add(h)

@contextlib.contextmanager
def original(path,meta,tmp):
    need(path.stat().st_size==meta['size_in_bytes'] and 'sha256:'+sha(path)==meta['digest'],'wrong raw GitHub upload')
    with zipfile.ZipFile(path)as z:
        member,=z.infolist();need(member.filename=='matched-heldout-proof.tar' and member.compress_type==zipfile.ZIP_STORED and member.file_size<330<<20 and z.testzip() is None,'unexpected archive')
        with z.open(member)as f,tarfile.open(fileobj=f,mode='r:')as tf:yield Raw(tf,tmp)

def renderer_objects(lib):
    objects={};long=None
    with lib.open('rb')as f:
        need(f.read(8)==b'!<arch>\n','wrong Rust library')
        while block:=f.read(60):
            need(len(block)==60 and block[-2:]==b'`\n','invalid ar header');ref=block[:16].strip().decode();n=int(block[48:58]);body=f.read(n);need(len(body)==n and (n%2==0 or f.read(1)==b'\n'),'truncated or misaligned archive')
            if ref=='//':long=body
            elif ref.startswith('/')and ref[1:].isdigit():
                at=int(ref[1:]);end=long.index(b'/\n',at);name=long[at:end].decode();m=re.fullmatch(r'annotate_snippets-[a-f0-9]+\.([a-z0-9]+)\.[a-z0-9]+\.rcgu\.o',name);need(m and m[1]not in objects,'wrong native member');objects[m[1]]=hashlib.sha256(body).hexdigest()
    need(len(objects)==118,'incomplete renderer native objects');return objects

def frames(data):
    out=[]
    while data:
        need(len(data)>=8,'truncated renderer framing');n=struct.unpack('<Q',data[:8])[0];need(n<=len(data)-8,'truncated renderer frame');out.append([hashlib.sha256(data[8:8+n]).hexdigest(),n]);data=data[8+n:]
    return out

def native(raw,stem,row,rev,source):
    actual=row['native'];old=PRIOR['source'][rev];expect=H['expected'][rev];raw.prove(actual['elf']);raw.prove(actual['client']);test=raw.cas(actual['elf'])if source else None;client=raw.cas(actual['client'])if source else None;lib=raw.cas(actual['rlib']);need(actual['elf']==expect['elf_sha256']==old['test_binary'] and actual['client']==old['client'],'changed independently executed artifact');list_=raw.read(stem+'tests.list');need(len(list_.splitlines())==actual['test_count']==126 and hashlib.sha256(list_).hexdigest()==old['roster_sha256']==M['tests']['sha256'],'native test inventory');need(actual['tests']==old['tests']and actual['oracle']==expect['oracle'],'different test/native renderer endpoints');declared=raw.json(stem+'provider-folds.json');syms=subprocess.check_output(['nm','--extern-only','--defined-only','--format=posix',lib],stderr=subprocess.DEVNULL,timeout=90);need(len(declared)==actual['exports']==expect['provider_fold_exports']and all(v['symbol'].encode()+b' T 'in syms for v in declared),'missing actual Rust provider');objects=renderer_objects(lib);need(objects==raw.json(stem+'renderer-object-hashes.json') and digest(objects)==expect['native_renderer_objects_sha256'],'incorrect source-specific renderer machine objects');env=dict(PATH='/usr/bin:/bin',HOME=str(raw.tmp),TMPDIR=str(raw.tmp),LC_ALL='C',INSTA_UPDATE='no')
    if source:
        test.chmod(0o700);client.chmod(0o700);need(subprocess.check_output([test,'--list','--format','terse'],cwd=source,env=env,timeout=90)==list_,'fresh native test inventory')
    for i,name in enumerate(sorted(actual['tests'])):
        output=raw.read(stem+f'test-{i}.stdout');tag=f'test {name} ... ok'.encode();need(tag in output and b'1 passed; 0 failed;'in output,'hosted executable test failed')
        if source:
            p=subprocess.run([test,'--exact',name,'--test-threads=1'],cwd=source,env=env,capture_output=True,timeout=90);need(p.returncode==0 and tag in p.stdout and b'1 passed; 0 failed;'in p.stdout,'fresh executable test failed')
    for key,gold in expect['oracle'].items():
        stdout=raw.read(stem+key+'.stdout');stderr=raw.read(stem+key+'.stderr');need(frames(stdout)==gold['frames'] and hashlib.sha256(stdout).hexdigest()==old['runtime'][key]['stdout_sha256']and (not stderr if gold['exit']==0 else b'index out of bounds: the len is 11 but the index is 11'in stderr),'genuine renderer behavior changed')
        if source:
            p=subprocess.run([client,key],cwd=source,env=env,capture_output=True,timeout=90);need(p.returncode==gold['exit']and p.stdout==stdout and (not p.stderr if p.returncode==0 else b'index out of bounds: the len is 11 but the index is 11' in p.stderr),'fresh renderer verdict differs')
    lib.unlink();return dict(elf=actual['elf'],client=actual['client'],rlib=actual['rlib'])

def graph(path,schema,q,storage):
    names=schema['names'];nkind=len(names);bits=(nkind-1).bit_length();mask=(1<<bits)-1;counts=[0]*nkind;roots={};matches=[];observed={r['index']:r for r in q['bucket_rows']};required=collections.defaultdict(set)
    for xs in q['paths'].values():
        for a,b in zip(xs,xs[1:]):required[a].add(b)
    with path.open('rb')as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)as m:
        p,end=role_graph.header(m,schema['format']);p+=8;slots,nodes,total=struct.unpack_from('<QQQ',m,end-24);need(0<nodes<=slots<2_000_000 and total<10_000_000,'unbounded graph');limit=struct.unpack_from('<Q',m,end-48)[0]if m[end-32:end-24]==b'OHMIDX01'else end-24;seen=bytearray(slots);edges=0
        for _ in range(nodes):
            frac,idx=struct.unpack_from('<HI',m,p);kind=frac&mask;w=((frac>>bits)&3)+1;n=(frac>>(bits+2))-1;h=p;p+=38
            if n<0:n,p=role_graph.leb(m,p,limit)
            stop=p+n*w;need(0<kind<nkind and idx<slots and not seen[idx]and stop<=limit,'invalid physical graph');seen[idx]=1;counts[kind]+=1;edges+=n;label=names[kind]
            if label in ('CompileCodegenUnit','upstream_monomorphizations_for')or idx in observed:
                key=role_graph.stable(m[h+6:h+22]);val=role_graph.stable(m[h+22:h+38])
                if label=='CompileCodegenUnit':need(key not in roots,'duplicate actual CGU root');roots[key]=idx
                if label=='upstream_monomorphizations_for'and key==H['different_broad_row']['old']['key']:matches.append((idx,key,val))
                if idx in observed:
                    row=observed.pop(idx);need(label=='upstream_monomorphizations_in'and (key,val)==(row['key'],row['value']),'incorrect observed candidate lookup')
            if idx in required:
                children={int.from_bytes(m[i:i+w],'little')for i in range(p,stop,w)};need(required.pop(idx)<=children,'declared CGU edge absent')
            p=stop
        for c in counts:
            n,p=role_graph.leb(m,p,limit);need(n==c,'serialized node histogram mismatch')
        sessions,p=role_graph.leb(m,p,limit);need(p==limit and total==edges==storage['edges'] and nodes==storage['nodes'] and slots==storage['node_slots'] and len(m)==storage['bytes'] and not required and not observed,'footer/physical graph counts differ');need(sorted(matches)==sorted((r['index'],r['key'],r['value'])for r in q['matches']),'wrong upstream owner lookup identity');return roots,dict(nodes=nodes,edges=edges,bytes=len(m),named_values=[m[2]for m in matches],bucket_rows=len(q['bucket_rows']))

def calibrated(raw):
    report={}
    for mode,copies in [('0',1),('1',2),('thread',2),('exec',1)]:
        vv=[]
        for i in range(4):
            c=raw.json(f'meter/calibration/native-{mode}-{i}.json');need(c['event_errno']==0 and c['enabled']==c['running']>0 and c['instructions']>0,'invalid inherited counter calibration');vv.append(c['instructions'])
        delta=statistics.mean(vv[1:3])-statistics.mean((vv[0],vv[3]));expected=2*copies*700000;need(abs(delta/expected-1)<.02,'inherited event calibration fails');report[mode]=dict(values=vv,delta=delta,expected=expected)
    return report

def ordinary(raw,folder,role,source):
    observations={};maps={};kept=[];blobs=set();registered={'P':'normal','C':'defer'};install=raw.json('compiler-installations.json')['arms'][registered[role]]['files'];need(all(install.get(k)==v for k,v in M['roles'][role]['files'].items())and install['bin/cargo']=='3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871' and WILD in install.values(),'source-built driver, real Cargo or Wild has changed')
    for phase in ('old','edit','unchanged','invalid','repair','clean'):
        stem=f'{folder}/{role}-{phase}/';rev='old'if phase=='old'else'new';visit=raw.json(stem+'visit.json');proc=raw.json(stem+'process.json');expected=101 if phase=='invalid'else 0;scored=phase in H['scored'];argv=proc['argv'];need((argv[2:]==CMD and argv[0].endswith('/work/watch')and argv[1].endswith('/clock.json'))if scored else argv==CMD,'foreign Cargo entry/counter or timed tests');need(proc['exit']==expected and proc['min_memory']>8<<30 and proc['min_disk']>15<<30 and visit['source']==M[rev+'_commit'],'changed Ruff source, result or resource floor');rows=[json.loads(x)for x in raw.read(stem+'cargo.stdout').splitlines()];need(rows[-1]=={'reason':'build-finished','success':not expected},'Cargo failed the build');arts=[v for v in rows if v.get('reason')=='compiler-artifact'];dirty=[v for v in arts if not v['fresh']];rec={'minimum_available_memory':proc['min_memory'],'minimum_available_disk':proc['min_disk'],'nonfresh':[v['target']['name']for v in dirty]};observations[phase]=rec
        if phase=='invalid':
            error=[v for v in rows if v.get('reason')=='compiler-message'and v['message']['level']=='error'and v['message'].get('code')];need(len(error)==1 and error[0]['target']['name']=='ruff_db'and error[0]['message']['code']['code']=='E0308'and any(s['file_name']==H['invalid_source']and s['is_primary']for s in error[0]['message']['spans']),'expected real E0308');rec['allocated']=visit['allocated'];continue
        state=raw.json('setup.json')['state'];placement=normal_registry.capture(rows,Path(state),False);need(len(arts)==171 and (placement['sha256'],placement['products'],placement['shared'])==(REG,123,114),'normal signed registry graph changed');rec['native']=native(raw,stem,visit,rev,source)
        if phase in ('old','edit','clean'):
            need(len(dirty)==171 if phase!='edit'else sorted(v['target']['name']for v in dirty)==['annotate_snippets','ruff_db'],'different cold/edit packages');objects=raw.json(stem+'objects.json');maps[phase]=objects;blobs.update(v['sha256']for v in objects.values());need(len(objects)==216 and digest({k:v['sha256']for k,v in objects.items()})==H['expected'][rev]['ruff_db_cgu_sha_by_role'][role],'consumer object inventory differs');storage=raw.json(stem+'storage.json');rec['allocated']=storage['total'];rec['query_cache']=storage['ruff_db']['query_cache']['bytes'];schema=SCHEMA[M['roles'][role]['commit']];graphs=raw.tmp/'consumer-graph.bin';products=raw.tmp/'consumer-products.bin';raw.graph(stem+'work-products.bin.gz',products);raw.graph(stem+'graph.bin.gz',graphs);need(sha(graphs)==visit['digests']['graph']and sha(products)==visit['digests']['work_products'],'compiler artifacts altered');q=raw.json(stem+'query.json');roots,rec['graph']=graph(graphs,schema,q,storage['ruff_db']['dep_graph']);products_=role_graph.products(products,schema['format']);graphs.unlink();need(set(roots)==set(products_)and all(v['product']==products_[v['cgukey']]['product'] and v['filename']==products_[v['cgukey']]['files']['o'] for v in objects.values()),'wrong CGU ID / native-file ownership');need(all(roots[objects[k]['cgukey']]==chain[0]for k,chain in q['paths'].items()),'path starts at wrong physical CGU');
        elif phase=='unchanged':
            rec['allocated']=visit['allocated'];only,=dirty;need(only['target']['name']=='ruff_db'and only['target']['kind']==['lib']and only['profile']['test'] and only['executable'],'foreign unchanged Cargo unit');steady=raw.json(stem+'unchanged-physical.json');need(steady['caller_objects']==216 and steady['session']==raw.json(f'{folder}/{role}-edit/visit.json')['session']and set(steady['protected'])==set(maps['edit'])|{':elf',':rlib'},'wrong unchanged session/roster');
            for name,x in steady['protected'].items():
                before,now,live=map(x.get,('before','after','live_old'));ref=rec['native']['elf']if name==':elf'else rec['native']['rlib']if name==':rlib'else maps['edit'][name]['sha256'];need(before[:3]==now[:3]==live[:3] and before[-1]==now[-1]==live[-1]==ref and (before[3]!=now[3])==(name==':elf')and now[3]==live[3],'physical steady output differed: '+name)
        else:rec['allocated']=visit['allocated']
    for name,old in maps['old'].items():
        new=maps['edit'][name];need(old['sha256']==new['sha256']==maps['clean'][name]['sha256']and (old['identity']==new['identity'])==new['same_pinned_donor'],'stale, absent or incorrectly identified Old CGU');
        if new['same_pinned_donor']:kept.append(name)
    need(observations['old']['native']['elf']!=observations['clean']['native']['elf']and len({observations[k]['native']['elf']for k in ('edit','repair','unchanged','clean')})==1,'wrong whole test executable, invalid repair or freshness');return observations,sorted(kept),blobs

def verify_sources(raw,slot,entry,source):
    boot=raw.json('heldout-worker.json');binding=raw.json('hardware-binding.json');order=C['orders'][slot-1];index=H['order'].index(order);j=entry['job'];need(j['conclusion']=='success'and boot['boot']==binding['boot']==raw.json('setup.json')['boot'] and boot['boot']!=C['pilot_boot']and boot['run']==RUN and boot['job']==j['id']and boot['runner_id']==j['runner_id']and boot['runner']==j['runner_name'] and boot['slot']==slot and boot['order']==order and boot['head']==HEAD and boot['confirmation']==sha(HERE/'confirmation.json'),'different independent worker or treatment');need(raw.json('confirmation-registration.json')==C and binding['hardware_protocol']==sha(HERE/'hardware.json') and binding['command']==CMD and len(set(binding['cpus']))==4 and raw.json('factory.json')['run']==41431225435,'incorrect P/C factory + toolchain or protocol');need(raw.json('terminal.json')==dict(complete=True,slot=slot,order=order,confirmation=sha(HERE/'confirmation.json'))and'hardware-confirmation.json'in raw.entries and'incomplete.json'not in raw.entries,'incomplete native history');need(sum(k.endswith('/clock.json')for k in raw.entries)==6,'unexpected measured Cargo commands');obs={};sets={};allb=set();cal=calibrated(raw)
    for role in order:
        folder=f'{index}-{role}';obs[role],sets[role],files=ordinary(raw,folder,role,source);allb.update(files);summary=raw.json(folder+'/summary.json');need(summary['kept']==sets[role]and summary['role']==role and summary['order']==order and summary['boot']==boot['boot']and summary['counted']==H['scored'],'native summary fails independent reconstruction')
    for key in sorted(allb):raw.prove(key)
    need(len(allb)==216,'changed caller machine bytes');return dict(slot=slot,order=order,boot=boot['boot'],runner=boot['runner'],runner_id=j['runner_id'],cpu=binding['cpus'],calibration=cal,source=obs,kept=sets,graph_bytes=entry['artifact']['digest'])

def score(raw,pre):
    order=pre['order'];index=H['order'].index(order);allc={};proof=raw.json('hardware-confirmation.json');need(proof['slot']==pre['slot']and proof['order']==order and proof['primary']=='edit','wrong terminal observations');
    for role in order:
        counts={};allc[role]=counts
        for phase in H['scored']:
            c=raw.json(f'{index}-{role}/{role}-{phase}/clock.json');need(c['enabled']==c['running']>0 and not c['event_errno']and c['instructions']>0,'multiplexed or failed native hardware event');counts[phase]=c['instructions']
    percent={phase:1-allc['C'][phase]/allc['P'][phase]for phase in H['scored']};extra=sorted(set(pre['kept']['C'])-set(pre['kept']['P']));lost=sorted(set(pre['kept']['P'])-set(pre['kept']['C']));need(proof['price']==allc and proof['reductions']==percent and proof['old_object_gain']==extra and proof['old_object_loss']==lost,'reported prices/donors differ from original evidence');return dict(slot=pre['slot'],order=order,measurement=allc,reductions=percent,pinned_parent=len(pre['kept']['P']),pinned_candidate=len(pre['kept']['C']),gained=extra,lost=lost)

def fixture_tree(root):
    def ident(kind,data):return hashlib.sha1(kind+b' '+str(len(data)).encode()+b'\0'+data).digest()
    rows=[]
    for item in root.iterdir():
        name=os.fsencode(item.name);t=item.lstat().st_mode
        if stat.S_ISDIR(t):sort_key,mode,value=name+b'/',b'40000',fixture_tree(item)
        elif stat.S_ISLNK(t):sort_key,mode,value=name,b'120000',ident(b'blob',os.fsencode(os.readlink(item)))
        else:
            need(stat.S_ISREG(t)and item.stat().st_size<10<<20,'unbounded fixture file');sort_key,mode,value=name,(b'100755'if t&0o100 else b'100644'),ident(b'blob',item.read_bytes())
        rows.append((sort_key,mode+b' '+name+b'\0'+value))
    return ident(b'tree',b''.join(v for _,v in sorted(rows)))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('packet',type=Path);parser.add_argument('--ruff-source',type=Path,help='Optional actual Ruff checkout for an additional execution of precisely these binaries');args=parser.parse_args();dir_=args.packet.resolve();source=args.ruff_source.resolve()/'crates/ruff_db'if args.ruff_source else None
    if source:need(source.is_dir()and fixture_tree(source).hex()=='7c6bb1c27985d99bd3a76eea7e0ab6e2cc6a3410','the libtest fixture tree must match both actual Ruff commits')
    need(sha(HERE/'hardware.json')==C['pilot_hardware_protocol_sha256']and sha(HERE/'confirmation.json')=='c9e420ff70158c08f7aac6aadee181840d878682608c574a7ddde552b121c2a5','changed pre-registration');provenance=read_json(dir_/'github-provenance.json');run=provenance['run'];need(run['id']==RUN and run['head_sha']==HEAD and run['run_attempt']==1 and run['conclusion']=='success'and run['event']=='workflow_dispatch','different real enrollment');obs=[];prices=[]
    for slot in range(1,7):
        entry=provenance['slots'][str(slot)];art=entry['artifact'];need(art['workflow_run']['id']==RUN and art['workflow_run']['head_sha']==HEAD and entry['job']['name']==f'Ruff library-test confirmation boot {slot}' and entry['job']['runner_id']>0,'incorrect custody');need(shutil.disk_usage(dir_).free>(15<<30)+((170 if source else 48)<<20),'local reconstruction disk reserve');mem=int(next(l.split()[1]for l in Path('/proc/meminfo').read_text().splitlines()if l.startswith('MemAvailable:')))*1024
        if source:need(mem>(8<<30)+(96<<20),'local native execution memory reserve')
        with tempfile.TemporaryDirectory(dir=dir_)as tmp,original(dir_/entry['file'],art,Path(tmp))as raw:obs.append(verify_sources(raw,slot,entry,source))
        print('verified original source/native/custody',slot,obs[-1]['order'],len(obs[-1]['kept']['P']),len(obs[-1]['kept']['C']),flush=True)
    for attr in ('boot','runner','runner_id'):need(len({item[attr]for item in obs})==6,'reused independent worker: '+attr)
    for item in obs:
        entry=provenance['slots'][str(item['slot'])]
        with tempfile.TemporaryDirectory(dir=dir_)as tmp,original(dir_/entry['file'],entry['artifact'],Path(tmp))as raw:prices.append(score(raw,item))
    reductions=[x['reductions']['edit']for x in prices];nonzero=[x for x in reductions if x!=0];tails=min(sum(x<0 for x in nonzero),sum(x>0 for x in nonzero));p=min(1,2*sum(math.comb(len(nonzero),i)for i in range(tails+1))/(2**len(nonzero)));eligible=p<.05 and min(reductions)>0 and all(x['gained']and not x['lost']for x in prices);summary=dict(run=RUN,head=HEAD,artifact_api='github-provenance.json',primary='edit',workers=6,prices=prices,median_reduction=statistics.median(reductions),median_speedup=statistics.median([1/(1-x)for x in reductions]),median_interval=[min(reductions),max(reductions)],distribution_free_coverage=1-2/(2**6),two_sided_exact_sign_p=p,eligible=eligible,controls={phase:statistics.median([x['reductions'][phase]for x in prices])for phase in ('old','unchanged')},all_native=obs,extra_local_execution=bool(source));target=dir_/('reopened-with-execution.json'if source else'reopened.json');target.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n');print('complete',eligible,'median',summary['median_reduction'],'interval',summary['median_interval'],'2-sided exact P',p,flush=True)
if __name__=='__main__':main()
