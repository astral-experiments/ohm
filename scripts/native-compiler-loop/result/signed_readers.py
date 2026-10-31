"""Reopen original Linux PMU, exec, storage, Cargo diagnostic and native-provider bytes offline."""
import argparse,collections,gzip,hashlib,io,json,os,re,statistics,tarfile,zipfile
from pathlib import Path
D=Path(__file__).resolve().parent
HEAD='5d26c524606e556b4934842568ed4acd2e91219d';FIXED='035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4';CARGO='761ea115605c34f11a1cd29afd68812c1e1359dd';SOURCES='93526150df078af7dd8fc4226cdcc469539d2001';PATCH='32c5cd5daba51d9c3da691c5b43afa6a7a4bb731'
SCORED=('cold','historical-edit','first-unchanged','repeat2','repeat3','switch-profile','switch-unchanged');TRACED=('empty-edited','traced-unchanged');ORDINARY=('warm-invalid','warm-repair','empty-invalid','empty-repair')
sha=lambda b:hashlib.sha256(b).hexdigest()

def unique(pairs):
    converted=dict(pairs);assert len(converted)==len(pairs);return converted

def unpack(raw):
    blobs={}
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as t:
        for h in t:
            p=Path(h.name);assert not p.is_absolute() and '..' not in p.parts
            if h.isdir():continue
            assert h.isfile() and str(p) not in blobs and h.size<100_000_000
            blobs[str(p)]=t.extractfile(h).read()
    return blobs

def read(b):return json.loads(b,object_pairs_hook=unique)
def hw(d,returncode=0):
    assert d['code']==returncode and d['event_errno']==0 and d['instructions']>0 and d['enabled']==d['running'] and d['running']>0 and d['stop']>d['start']
    return d['instructions']

def trace(b,base,t,rec):
    rust=t['rustc']['dev_ino'];wild=t['wild']['dev_ino'];rows=[]
    raw=b[base+'/kernel/exec.tsv'].decode().splitlines()
    for s in raw:
        no,p,d,i,match,image=s.split('\t');a=b[base+f'/kernel/args-{int(no):04d}'];assert a.endswith(b'\0');argv=[os.fsdecode(v) for v in a[:-1].split(b'\0')];assert not int(match)
        rows.append([int(p),[int(d),int(i)],image,argv]);
    assert list(range(1,len(raw)+1))==[int(line.split('\t')[0]) for line in raw]
    sub=[(p,a) for p,i,f,a in rows if i==rust and '--crate-name' in a and '--out-dir' in a and not any(x.startswith('--print') for x in a)]
    links=[(p,a[a.index('-o')+1]) for p,i,f,a in rows if i==wild and '-o' in a];hosts=[(p,f) for p,i,f,a in rows if 'ruff_unicode_names2' in f and Path(f).name in ('build_script_build','build-script-build')]
    actual=[(p,a[a.index('--crate-name')+1],next(e for e in a if e.startswith('--emit=')),'link-only' if any(e in ('-Zlink-only','link-only') for e in a) else 'full') for p,a in sub]
    assert [(p,n,e,m) for n,p,e,m in rec['kernel']['compilers']]==actual and rec['kernel']['links']==list(map(list,links)) and rec['kernel']['generators']==list(map(list,hosts));assert len(hosts)==1 and len([r for r in links if r[1]==hosts[0][1]])==1
    roles={};hostopts=[]
    for p,a in sub:
        n=a[a.index('--crate-name')+1];n='unicode_build_script' if 'crates/ruff_unicode_names2/build.rs' in a else n
        if n not in ('unicode_build_script','unicode_names2_generator','phf_generator','unicode_names2','ty_project'):continue
        opts={}
        for i,v in enumerate(a):
            if v=='-C':field=a[i+1]
            elif v.startswith('-C') and len(v)>2:field=v[2:]
            else:continue
            key,_,val=field.partition('=');opts[key]=val
        level=opts.get('opt-level','0');debug=opts.get('debug-assertions','on' if level=='0' else 'off');over=opts.get('overflow-checks',debug)
        assert debug==over=='on';roles.setdefault(n,set()).add(level);hostopts.append((p,n,level))
        local,=[r for r in rec['kernel']['selected'][n] if r['pid']==p];assert local['argv']==a and (local['flags']['opt'],local['flags']['debug'],local['flags']['overflow'])==(level,debug,over)
    return dict(full=sum(r[3]=='full' for r in actual),link_only=sum(r[3]=='link-only' for r in actual),wild=len(links),unicode_wild=1,unicode_generator=len(hosts),roles={n:sorted(v) for n,v in sorted(roles.items())},repeated_full=sorted(n for p,n,e,m in actual if m=='full') if len(actual)<20 else None)

def disk(b,base,r):
    led=read(gzip.decompress(b[base+'/allocated-ledger.gz']));assert len({s[0] for s in led})==len(led) and {'target','shared'}=={Path(q[0]).parts[0] for q in led}
    by={}
    for path,dev,ino,mode,blocks,size,links in led:
        k=dev,ino;seen=by.setdefault(k,(mode,blocks,size,links));assert seen==(mode,blocks,size,links),(path,k,seen)
    total=sum(v[1] for v in by.values())*512;assert sum(int(l.split('\t',1)[0]) for l in r['gnu_du'].splitlines())==total==r['allocated_B'];assert r['paths']==len(led) and r['unique']==len(by) and r['hardlink_aliases']==len(led)-len(by);return total

def graph(b,base):
    doc=read(gzip.decompress(b[base+'/unit-graph.json.gz']));units=doc['units'];assert all(0<=i<len(units) for i in doc['roots']);keys=collections.Counter();opts=collections.Counter()
    for u in units:
        k=(u['pkg_id'],u['target']['name'],tuple(u['target']['kind']),u['mode'],tuple(u['features']))
        keys[k]+=1;opts[(u['mode'],u['profile']['opt_level'])]+=1
    return {'units':len(units),'unique_roles_features':len(keys),'additional_same_roles_features':len(units)-len(keys),'modes_opt_level':dict(sorted((k[0]+'/'+k[1],v) for k,v in opts.items()))}

def verify_one(b,order):
    js=lambda n:read(b[n]);job=js('strict.json');sub=js('subjects.json');tools=sub['tools'];srcroot=sub['environment']['CARGO_TARGET_DIR'].rpartition('/slot/target')[0]+'/source';assert job['plan']=='e88f9d6d07c99cb31880e2835577f51238e6321ce9b4355c9ce19cfa9d3ffbf1' and job['order']==order and job['head']==HEAD and job['cargo']==FIXED and CARGO in job['selected'] and sub['source']==SOURCES and sub['history']==PATCH
    supplied=js('strict-cargo-artifact.json');assert supplied['build']['compiled']==supplied['build']['delivered']==FIXED and supplied['build']['candidate']==CARGO and len(job['locked'])==498
    assert all(n not in job['environment'] for n in ('CI','TF_BUILD','RUSTFLAGS','RUSTC_WRAPPER','CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL','GITHUB_TOKEN','GH_TOKEN'));assert len(js('host.json')['actual'])==8
    cal=[];n=80_000_000
    for z,(mode,copies) in enumerate((('0',1),('1',1),('2',1),('2',2),('exec',1),('thread',1),('thread',2))):
        values=[hw(js(f'calibration/{z}-{j}.json')) for j in range(4)];delta=statistics.median(values[1::2])-statistics.median(values[::2]);assert abs(delta/(2*n*copies)-1)<.02;cal.append([mode,copies,values,delta,2*n*copies]);
    assert cal==js('calibration/verified.json');native={};arms={};allerr=[];one_body=None;allrosters=set();states=js('complete.json');assert states['order']==order
    for arm in order:
        roles={};a='opt'+arm;health=[];warn=[]
        for name in (*SCORED,*TRACED,*ORDINARY):
            base=a+'/'+name;r=js(base+'/visit.json');bad=name.endswith('invalid');assert r['arm']==arm and r['phase']==name and r['exit']==(101 if bad else 0)
            out=[read(l) for l in gzip.decompress(b[base+'/stdout.gz']).splitlines()];assert out[-1]=={'reason':'build-finished','success':not bad};units=[v for v in out if v['reason']=='compiler-artifact'];assert len(units)==r['typed'] and [v['target']['name'] for v in units if not v['fresh']]==r['dirty']
            msgs=[v['message'] for v in out if v['reason']=='compiler-message'];errs=[e for e in msgs if e['level']=='error'];abi=sorted(set(json.dumps([u['package_id'],u['target']['name'],u['target']['kind'],u['features'],u['profile']['test']],separators=(',',':')) for u in units));assert gzip.decompress(b[base+'/logical.gz'])==json.dumps(abi,separators=(',',':')).encode() and len(abi)==r['logical'];assert not any(v['executable'] for v in units)
            assert errs==r['errors'] and len(errs)==int(bad) and len([v for v in out if v['reason']=='build-script-executed' and '/crates/ruff_unicode_names2#' in v['package_id']])==1
            if bad:
                e=errs[0];assert e['code']['code']=='E0308' and any(s['is_primary'] and s['file_name']=='crates/ty_project/src/lib.rs' and 'OHM_HOST_PROFILE_BAD_TYPE' in ''.join(x['text'] for x in s['text']) for s in e['spans']);allerr.append(e)
            else:
                allrosters.add(r['logical_sha']);warn.append(r['warning_sha'])
            assert r['source']==(sub['original_blob'] if name=='cold' else sub['historical_parent_blob']);assert sorted(r['generated'])==['generated.rs','generated_alias.rs','generated_phf.rs']
            for h in r['generated'].values():assert sha(gzip.decompress(b['generated/'+h+'.gz']))==h
            if one_body is None:one_body=r['generated']
            assert r['generated']==one_body
            rec={'typed':len(units),'dirty_count':len(r['dirty'])}
            if name in SCORED:rec.update(instructions=hw(js(base+'/whole.json')),allocated_B=disk(b,base,r['storage']));assert rec['instructions']==r['instructions']
            if name in TRACED:rec['physical']=trace(b,base,tools,r)
            roles[name]=rec
        assert all(x==warn[0] for x in warn);health=roles['empty-edited']['physical']['roles'];assert health=={'phf_generator':[arm],'ty_project':['1'],'unicode_build_script':[arm],'unicode_names2':['1'],'unicode_names2_generator':[arm]}
        assert all(q[1]=='true true true\n' for q in js(a+'/flag-probes.json').values());arms[arm]={'visits':roles,'graph':graph(b,a),'flags':health,'state':{k:v for k,v in states['states'][arm].items() if k not in ('diag','neutral_generated')}}
    assert len(allrosters)==1 and all(x==allerr[0] for x in allerr);assert bool(allerr)
    if order=='01':native=providers(b,js)
    ratios={key:arms['0']['visits'][key]['instructions']/arms['1']['visits'][key]['instructions'] for key in SCORED if key not in ('switch-profile','switch-unchanged')}
    return {'order':order,'host':job['host'],'raw_calibrations':len(cal)*4,'calibration_delta_expected':[[a,b,d,e] for a,b,_,d,e in cal],'whole_instruction_ratios_0_over_1':ratios,'arms':arms,'same_generated':one_body,'native':native}

def providers(b,js):
    summary={};signs={};base='native-provider/';expected={'absent':0,'held-83':83,'held-47':47,'remove':0,'malformed':None};seenelfs=set();retained=js(base+'verified.json')
    for arm in ('0','1'):
        rows={};before83=None
        for history,labels in [('history',list(expected)),('empty',['held-83','held-47','malformed','remove'])]:
            for label in labels:
                prefix=base+f'opt{arm}/{history}/{label}/';r=js(prefix+'observation.json');e=expected[label];assert r['status']==(101 if e is None else 0)
                raw=gzip.decompress(b[prefix+'exec-and-provider-open.gz']);assert sha(b[prefix+'exec-and-provider-open.gz'])==r['trace']
                ld=r['physical']['ld'];assert ld and all(Path(f).name=='ld.bfd' and (' '+str(p)+' execve("'+f+'",').encode() in raw for p,f in ld);ds=js(prefix+'provider.json')
                if e not in (0,None):
                    assert ds['sha256']==sha(b[base+f'observe-{e}.so']);assert r['reader']==[f'Some({e})','Some(0)'];assert ('Some('+str(e)+')\nSome(0)\n').encode()==gzip.decompress(b[prefix+'reader-exec.stdout.gz'])
                    if history=='history' and label=='held-83':before83=ds
                    if history=='history' and label=='held-47':assert all(ds[k]==before83[k] for k in ('size','ino','mtime','dev')) and ds['sha256']!=before83['sha256']
                if e is None:
                    stdout=gzip.decompress(b[prefix+'cargo.stdout.gz']); typed=[read(line) for line in stdout.splitlines()];assert r.get('reader') is None and typed[-1]=={'reason':'build-finished','success':False}
                    diagnostics=[c['message'] for row in typed if row.get('message',{}).get('level')=='error' for c in row['message']['children']]; assert any('wild: error: Failed to process' in text and '/wild-ld/libutil.so' in text for text in diagnostics)
                    assert ds['sha256']==sha(b'not a valid GNU linker input for host-unicode\n'.ljust(ds['size'],b' '))
                else:
                    g=js(prefix+'generator.json');blob=gzip.decompress(b[base+'generators/'+g['sha256']+'.gz']);assert sha(blob)==g['sha256'] and len(blob)==g['size'] and blob[:4]==b'\x7fELF';seenelfs.add(g['sha256']);assert len(r['physical']['generator'])==1 and r['physical']['generator'][0][1]==g['path'];assert any(g['path'].encode() in l and b'execve(' in l for l in raw.splitlines());
                    elf=gzip.decompress(b[base+'objects/'+r['reader_sha256']+'.gz']);assert sha(elf)==r['reader_sha256'] and elf[:4]==b'\x7fELF';assert int(r['generate_code'],16)==e
                    for h in r['generated'].values():assert sha(gzip.decompress(b[base+'objects/'+h+'.gz']))==h
                    if e in (83,47):
                        opens=[q for q in r['search']['probes'] if q['kind']=='higher' and q['call'].startswith('open') and q['result']>=0];assert any(q['exe']==g['path'] for q in opens) and any(q['exe']==f for _,f in ld for q in opens)
                        assert all(any((' '+str(q['pid'])+' '+q['call']+'(').encode() in l and b'/libutil.so"' in l for l in raw.splitlines()) for q in opens)
                rr={'exit':r['status'],'reader':r.get('reader'),'reader_sha256':r.get('reader_sha256'),'generated':r.get('generated'),'loader_elf':g['sha256'] if e is not None else None,'real_wilds':len(ld),'higher_sha':ds['sha256'] if ds else None}
                rows.setdefault(label,{})[history]=rr
                if history=='history':assert {k:r.get(k) for k in ('status','reader','generated','reader_sha256')}==retained[arm][label]
        for label in ('held-83','held-47','remove','malformed'):
            for k in ('exit','reader','reader_sha256','generated'):assert rows[label]['history'][k]==rows[label]['empty'][k]
        summary[arm]=rows
    return {'actual_generator_ELFs':sorted(seenelfs),'runs':18,'arms':summary}

def main(directory):
    out=[]
    for order in ('01','10'):
        n='host-opt-'+order;path=directory/(n+'.zip');m=read((directory/(n+'.json')).read_bytes());archive=path.read_bytes();assert sha(archive)==m['digest'][7:] and len(archive)==m['size_in_bytes'] and m['name']=='strict-host-opt-'+order and m['workflow_run']['head_sha']==HEAD
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            assert z.namelist()==[n+'.tar.gz'] and z.testzip() is None;blobs=unpack(z.read(n+'.tar.gz'))
        res=verify_one(blobs,order);res['artifact_id']=m['id'];res['artifact_sha256']=sha(archive);res['members']=len(blobs);out.append(res)
    assert out[0]['host']!=out[1]['host'] and out[0]['same_generated']==out[1]['same_generated']
    return {'source':SOURCES,'historical_edit':PATCH,'cargo':CARGO,'scope':'2 mirrored pilot pairs, named ordinary command; no population estimate','qualifies_2x_primary_on_both':all(d['whole_instruction_ratios_0_over_1']['first-unchanged']>=2 for d in out),'pairs':out}
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('directory',nargs='?',type=Path,default=D);args=ap.parse_args();print(json.dumps(main(args.directory),sort_keys=True,indent=2))
