"""Read actual Cargo streams, Apple kernel exec rows, ar objects and complete Mach-Os from the native artifact."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
from zipfile import ZipFile

P='2035696c5316079f5b2e4373aee834839aac97e9'
C='444c0273a2e2bc0b161e988d43c882349bc2d7a6'
QA='1c8e729a327b8c1debc40f7c7621d91af425c9a7'
CARGO='505008003127f597cf2bdbd967d2bac9158d706b55a18f8bf17790e9ea3bbac9'
RELEASE='7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8'
PLAN='7ad7c3d3ceb927fe43ccc0f50cd9efdc66ee842feebe7b3aa26bf85a1a12c167'
WORKER='37f9879deeb8b4ee814bbbedc6f2192062ddf6f485fed2ba0b1bbd416b4777ca'
STEPS=[('lower','lower',7),('unchanged-lower','lower',7),('higher-no-rust','higher',7),
 ('higher-rust-edit','higher',11),('malformed-no-rust','malformed',11),
 ('malformed-rust-edit','malformed',13),('repair-before-missing','higher',13),
 ('missing-no-rust','missing',13),('missing-rust-edit','missing',15),
 ('restored-rust-edit','lower',19),('restored-unchanged','lower',19)]
UNWATCHED={'higher-no-rust','malformed-no-rust','repair-before-missing','missing-no-rust'}
LD={'ld','ld64','ld-prime','ld-classic','ld64.lld','ld.lld','rust-lld','wild','wild-ld'}
short=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))
def sha(x):return hashlib.sha256(x).hexdigest()
def filehash(p):
    with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(x,message):
    if not x:raise ValueError(message)
def section(data):
    magic,cpu,_,kind,n,sz,_,_=struct.unpack_from('<8I',data)
    assert (magic,cpu)==(0xfeedfacf,0x0100000c) and kind in (1,2) and 32+sz<=len(data)
    pos=32;texts=[];uuid=[]
    for i in range(n):
        t,s=struct.unpack_from('<II',data,pos)
        assert s>=8 and pos+s<=32+sz
        if t==0x1b:uuid.append(data[pos+8:pos+24].hex())
        if t==0x19:
            count=struct.unpack_from('<I',data,pos+64)[0]
            assert s==72+count*80
            for k in range(count):
                name,seg,_,length,off=struct.unpack_from('<16s16sQQI',data,pos+72+k*80)
                if name.rstrip(b'\0')==b'__text' and seg.rstrip(b'\0')==b'__TEXT':
                    assert 0<length and off+length<=len(data)
                    texts.append(data[off:off+length])
        pos+=s
    assert pos==32+sz and len(texts)==1
    if kind==2:assert len(uuid)==1
    return kind,texts[0],uuid
def archive_objects(data):
    assert data.startswith(b'!<arch>\n')
    i=8;objects=[]
    while i<len(data):
        h=data[i:i+60];assert len(h)==60 and h[-2:]==b'\x60\n'
        n=int(h[48:58]);name=h[:16].strip()
        start=i+60;end=start+n;i=end+n%2;assert i<=len(data)
        if name.startswith(b'#1/'):
            l=int(name[3:]);name=data[start:start+l].rstrip(b'\0');start+=l
        body=data[start:end]
        if name.rstrip(b'/').endswith(b'.o'):objects.append((name,body))
    assert i==len(data)
    return objects
class Reader:
    def __init__(self,archive):
        self.z=ZipFile(archive);self.images={};self.observer=None
        self.providers={};self.markers={};self.src={};self.drivers={}
    def read(self,path):return self.z.read(path)
    def j(self,path):return json.loads(self.read(path))
    def g(self,path):return gzip.decompress(self.read(path))
    def image(self,key):
        if key not in self.images:
            d=self.g('edge-images/'+key+'.macho.gz')
            k,t,u=section(d);assert k==2 and sha(d)==key
            self.images[key]={'raw':key,'bytes':len(d),'text':[len(t),sha(t)],'uuid':u[0]}
        return self.images[key]
    def provider(self):
        allp=self.j('provider-matrix/providers.json')
        for val in (17,29):
            v=allp[str(val)];p='provider-matrix/provider-'+str(val);o=self.read(p+'.o');a=self.read(p+'.a')
            assert v['source']=='int qa_value(void) { return '+str(val)+'; }\n'
            assert sha(o)==v['object'] and sha(a)==v['archive'] and all(t['exit']==0 for t in v['calls'])
            (nm,b),=archive_objects(a)
            assert nm.rstrip(b'/')==b'provider.o' and b.startswith(o) and not b[len(o):].strip(b'\0\n')
            k,t,u=section(o);assert k==1
            # AArch64 MOVZ W0,#imm ; RET, allowing a zero-width archive padding tail.
            assert t==struct.pack('<II',0x52800000 | (val<<5),0xd65f03c0)
            self.providers[str(val)]={k:v[k] for k in ('object','archive','source')}
            self.providers[str(val)]['code_hex']=t.hex()
    def case(self,name):
        base='provider-matrix/'+name;inputs=self.j(base+'/inputs.json');role,placement,policy,mode=name.split('-')
        assert [role,placement,policy,mode=='default']==[inputs[k] for k in ('role','placement','watch','defaults')]
        assert inputs['steps']==[list(t) for t in STEPS]
        src=inputs['source']
        body=src['src/main.rs' if placement=='direct' else 'barrier/src/lib.rs']
        assert sum(v.count('::asm!') for v in src.values())==1
        assert '::asm!("/*{:v}*/", inout(vreg) vector);' in body
        assert '::aarch64::int32x4_t' in body
        assert 'use barrier::barrier;' in src['src/main.rs'] if placement=='library' else '::asm!' in src['src/main.rs']
        assert ('cargo:rerun-if-changed={name}' in src['build.rs'])==(policy=='declared')
        assert all(f in src['build.rs'] for f in ('cargo:rerun-if-changed=build.rs','cargo:rustc-link-search=native=','["early","late"]'))
        assert src['trigger/src/lib.rs']=='#[inline(never)] pub fn value()->i32 {7}\n'
        self.src[name]={k:sha(v.encode()) for k,v in src.items()}
        self.drivers[name]=inputs['driver']
        digest=self.drivers[name]['sha256']
        dyld=self.j('provider-matrix/driver-'+role+'/verified.json')
        assert list(dyld['loaded'].values())[0]['sha256']==digest
        cap=base+'/';rows={};park=self.j(cap+'terminal.json')
        for phase,state,value in STEPS:
            prefix=cap+phase;comp=self.j(prefix+'/compared.json')
            assert comp==park[phase] and (comp['provider'],comp['rust'])==(state,value)
            assert comp['trigger_sha256']==sha(('#[inline(never)] pub fn value()->i32 {'+str(value)+'}\n').encode())
            low=self.providers['17']['archive'];hi=self.providers['29']['archive']
            goals={'lower':(None,low),'higher':(hi,low),'malformed':(sha(b'not a native archive\n'),None),'missing':(None,None)}
            assert tuple(comp['archives'][k] for k in ('early','late'))==goals[state]
            items={}
            for lane in ('warm','empty'):
                e=self.visit(prefix+'/'+lane,mode,policy)
                assert comp[lane]==[e['status'],e['answer'],e['image']]
                items[lane]=e
            a,b=items['warm'],items['empty']
            same = a['image']==b['image'] if a['image'] and b['image'] else None
            same_text = self.images[a['image']]['text']==self.images[b['image']]['text'] if same is not None else None
            assert comp['same_raw']==same and comp['same_text']==same_text
            want=[101,None] if state in ('missing','malformed') else [0,[17 if state=='lower' else 29,value]]
            assert [b['status'],b['answer']]==want
            if b['status']==0:assert len(b['final'])==1
            assert 'qa_owned_test' in b['full']
            rows[phase]={'warm':a,'empty':b,'same_raw':same,'same_text':same_text,'want':want}
        return rows
    def visit(self,p,mode,policy):
        proof=self.j(p+'/verified.json')
        out=self.g(p+'/stdout.gz');err=self.g(p+'/stderr.gz');x=self.g(p+'/exec.json.gz')
        streams={'stdout':sha(out),'stderr':sha(err),'native_events':sha(x)}
        assert streams==proof['streams']
        events=list(map(json.loads,out.splitlines()));proc=json.loads(x)
        argv=['cargo','+ohm']+(['-Zohm-defaults=no'] if mode=='off' else [])+['build','--locked','--offline','-j4','--message-format=json']
        assert proof['argv']==argv and proc[0]['argv']==argv and proc[0]['path'].endswith('/rustup-init')
        status=proof['status'];assert status in (0,101) and events[-1]=={'reason':'build-finished','success':status==0}
        artifacts=[r for r in events if r['reason']=='compiler-artifact']
        key=lambda r:[r['package_id'],r['target']['name'],','.join(r['target']['kind']),r['features'],short(r['profile'])]
        typed=sorted(map(key,artifacts));dirty=sorted(key(r) for r in artifacts if not r['fresh'])
        assert typed==proof['typed'] and dirty==proof['dirty']
        cargo=[r for r in proc if r['path'].endswith('/native/bin/cargo')]
        assert len(cargo)==1 and cargo[0]['argv'][1:]==argv[2:]
        assert all(isinstance(r['seq'],int) and r['pid']>0 for r in proc)
        assert sorted({r['seq'] for r in proc})==[r['seq'] for r in proc]
        rust=[];linkonly=[]
        for r in proc:
            a=r['argv']
            if '--crate-name' not in a or not r['path'].endswith('/native/bin/rustc'):continue
            n=a[a.index('--crate-name')+1]
            if n=='___' and any(s=='--print' or s.startswith('--print=') for s in a):continue
            (linkonly if any('link-only' in s for s in a) else rust).append(n)
        native=proof['native']
        assert sorted(rust)==native['full'] and sorted(linkonly)==native['link_only'] and native['scope']=='kernel-exec'
        lds=[r for r in proc if Path(r['path']).name in LD]
        assert [r['argv'] for r in lds]==[r['argv'] for r in native['linkers']]
        assert all(r['stock'] for r in native['linkers'])
        selection=[]
        for r,link in zip(lds,native['linkers']):
            a=r['argv'];assert Path(r['path']).name in ('ld','ld64','ld-prime','ld-classic')
            if self.observer:assert link['sha']==self.observer
            if '-lqa_owned_external' not in a:continue
            n=a.index('-o');path=a[n+1];roots=[s[2:] if s!='-L' else a[k+1] for k,s in enumerate(a) if s.startswith('-L')]
            early,=[i for i,k in enumerate(roots) if k.endswith('/provider-source/early')]
            late,=[i for i,k in enumerate(roots) if k.endswith('/provider-source/late')]
            assert early<late
            unique,=[t for t in proof['final_links'] if t['pid']==r['pid']]
            assert (unique['output'],unique['parent'],unique['search'],unique['cdhash'],unique['linker'],unique['argv_sha'])==(path,r['ppid'],roots,r['cdhash'],link['sha'],sha(json.dumps(a,separators=(',',':')).encode()))
            if unique.get('retained'):assert proof['image']['raw']==unique['output_sha']
            selection.append({'pid':r['pid'],'ppid':r['ppid'],'argv':unique['argv_sha'],'output_name':Path(path).name,'output_path_sha256':sha(path.encode()),'retained':unique.get('retained'),'same_inode':unique.get('same_inode'),'output_sha':unique.get('output_sha'),'cdhash':r['cdhash'],'linker_sha256':link['sha']})
        assert len(selection)==len(proof['final_links'])<=1
        script_exec=[{'pid':r['pid'],'ppid':r['ppid'],'argv_sha256':sha(json.dumps(r['argv'],separators=(',',':')).encode()),'cdhash':r['cdhash']} for r in proc if Path(r['path']).name.startswith(('build-script-build','build_script_build'))]
        script=[r for r in events if r['reason']=='build-script-executed']
        assert proof['build_script']==[{'linked_paths':r['linked_paths'],'rerun':r['package_id']} for r in script]
        for r in script:
            assert len(r['linked_paths'])==2 and [Path(s).name for s in r['linked_paths']]==['early','late']
        reports=sorted(set(proof['build_script_output'].values()))
        for h in reports:
            raw=self.g('edge-markers/'+h+'.build-output.gz');assert sha(raw)==h
            lines=raw.decode().splitlines()
            want=['cargo:rerun-if-changed=build.rs']+(['cargo:rerun-if-changed=early','cargo:rerun-if-changed=late'] if policy=='declared' else [])
            assert [s for s in lines if s.startswith('cargo:rerun-if-changed=')]==want
            assert [Path(s).name for s in lines if s.startswith('cargo:rustc-link-search=native=')]==['early','late']
        markers=[]
        for a in proof['marker'].values():
            h=a['sha256'];data=self.g('edge-markers/'+h+'.d.gz')
            assert h==sha(data) and a['hard']==(b'ohm-untracked-relink-inputs' in data) and a['recheck']==(b'/dev/null/ohm-recheck-dependent-links' in data)
            markers.append([h,a['hard'],a['recheck']])
        image=proof['image'];answer=None;error=None
        if status==0:
            exe,=[r['executable'] for r in artifacts if r['target']['name']=='qa_owned_test' and r['executable']]
            binary=self.j(p+'/program.json');assert (binary['path'],binary['exit'])==(exe,0) and binary['sha256']==image['raw']
            assert self.image(binary['sha256'])==image and not self.g(p+'/program.stderr.gz')
            stdout=self.g(p+'/program.stdout.gz');assert re.fullmatch(rb'(17|29) (7|11|13|15|19)\n',stdout)
            answer=list(map(int,stdout.split()));assert answer==proof['answer']
        else:
            assert image is None and proof['answer'] is None
            diagnostics=[r['message'].get('rendered','') for r in events if r['reason']=='compiler-message']
            lines=('\n'.join(diagnostics)+'\n'+err.decode(errors='replace')).splitlines()
            hints=[re.sub(r'/(?:[^ ]+/)+[^ ]+', '<native-path>',line.strip()) for line in lines if any(t in line.lower() for t in ('cannot link directly','file format','unknown file type','unexpected file type','not a valid','unhandled file type','library not found for',"library 'qa_owned_external' not found",'undefined symbol','undefined reference','building for')) and len(line)<1500]
            error={'archive':b'qa_owned_external' in (out+err),'symbol':b'qa_value' in (out+err),'diagnostic_lines':hints}
            assert error['archive'] or error['symbol']
            assert proof['error']['named_archive']==error['archive'] and proof['error']['named_symbol']==error['symbol']
        return {'status':status,'answer':answer,'image':image['raw'] if image else None,'full':sorted(rust),'cached':sorted(linkonly),'ld':len(lds),'final':selection,'dirty':[v[1] for v in dirty],'roster':[v[1] for v in typed], 'streams':streams,'marker':sorted(markers),'build_reports':reports,'build_script_exec':script_exec,'build_script_reported_roots':len(script),'error':error}

def summarize(p):
    known=[];declared=[];unexpected=[];raw=[];cross=[];markers={};native={}
    for name,rows in p['cases'].items():
        role,position,policy,mode=name.split('-')
        for phase,state,value in STEPS:
            x=rows[phase];w=x['warm'];e=x['empty']
            actual=[w['status'],w['answer']]
            if actual!=x['want']:
                area=known if policy=='unwatched' and phase in UNWATCHED else unexpected
                area.append([name,phase,actual,x['want']])
            if x['same_raw'] is False:
                raw.append([name,phase,x['same_text'],actual==x['want']])
            if policy=='declared' and phase not in ('lower','unchanged-lower','restored-unchanged'):
                declared.append([name,phase,actual==x['want']])
            if role=='C':
                other='-'.join(['P',position,policy,mode])
                a=p['cases'][other][phase]['warm']
                aa=[a['status'],a['answer']]
                if aa!=actual:cross.append([position,policy,mode,phase,aa,actual])
            if phase=='higher-no-rust':
                native[name]={'full':w['full'],'cached':w['cached'],'linker':len(w['final']),'status':w['status'],'value':w['answer']}
            if phase=='lower':markers[name]=sorted(set((row[1],row[2]) for row in w['marker']))
    compared=sum(len(v) for v in p['cases'].values())
    cmds=[v[l] for v in p['cases'].values() for v in v.values() for l in ('warm','empty')]
    equality={'raw_match':0,'different_matching_verdict_and_text':0,'different_matching_verdict_and_different_text':0,'different_verdict_two_images':0,'only_warm_image':0,'only_empty_image':0,'both_error':0}
    for case in p['cases'].values():
        for row in case.values():
            w,e=row['warm'],row['empty']
            if w['image'] and e['image']:
                q='raw_match' if row['same_raw'] else 'different_verdict_two_images' if w['answer']!=e['answer'] else 'different_matching_verdict_and_text' if row['same_text'] else 'different_matching_verdict_and_different_text'
            else:q='only_warm_image' if w['image'] else 'only_empty_image' if e['image'] else 'both_error'
            equality[q]+=1
    assert sum(equality.values())==compared
    return {'cases':len(p['cases']),'compared':compared,'commands':2*compared,'true_cargo_101':sum(a['status']==101 for a in cmds),'native_programs':sum(a['status']==0 for a in cmds),'actual_full_rustcs':sum(len(a['full']) for a in cmds),'actual_cached_rustcs':sum(len(a['cached']) for a in cmds),'actual_stock_ld':sum(a['ld'] for a in cmds),'actual_provider_ld':sum(len(a['final']) for a in cmds),'actual_build_scripts':sum(len(a['build_script_exec']) for a in cmds),'unique_complete_machos':len(p['images']),'declared_evaluated':len(declared),'declared_failed':[x for x in declared if not x[-1]],'unexpected':unexpected,'unwatched_mismatches':known,'differential':cross,'complete_image_comparisons':equality,'higher_no_rust_native':native,'lower_markers':markers}
def dump(p,body):
    data=(json.dumps(body,sort_keys=True,indent=2)+'\n').encode()
    if p.suffix=='.gz':data=gzip.compress(data,mtime=0)
    if p.exists():require(p.read_bytes()==data,'refusing a changed output '+str(p))
    else:p.write_bytes(data)
def run(archive,part):
    h=Reader(archive);reg=h.j('provider-matrix/registered.json');h.provider()
    assert reg['roles']=={'P':P,'C':C} and reg['plan']==PLAN and reg['worker']==WORKER
    all_cases=['-'.join((r,place,watch,'default' if on else 'off')) for watch in ('unwatched','declared') for place in ('direct','library') for on in (True,False) for r in 'PC']
    selected=all_cases[:2] if part=='first' else all_cases
    actual=sorted(f.split('/')[1] for f in h.z.namelist() if re.fullmatch('provider-matrix/[^/]+/terminal.json',f))
    require(sorted(selected)==actual,'incomplete: completed cases '+str(actual))
    src={'P':P,'C':C}
    if part=='final':
        pair=h.j('pair.json');release=h.j('release.json');ob=h.j('observer.json')
        assert release['archive']==RELEASE and (release['cargo']['sha256'] if isinstance(release['cargo'],dict) else release['cargo'])==CARGO
        h.observer=ob['ld']; assert ob['exit']==29
        A,B=(pair['products'][k] for k in 'PC')
        assert (A['source'],A['tree'],B['source'],B['tree'])==(P,'df84b98ba4deb07dd6f25446632704a1302c23a3',C,'f08c7d8e65d8d06ae7da0d81dafb25cc68124567')
        assert set(A['runtime'])==set(B['runtime']);diff=[k for k in A['runtime'] if A['runtime'][k]!=B['runtime'][k]]
        assert diff==pair['differ'] and len(diff)==1 and diff[0].startswith('lib/librustc_driver')
        assert A['runtime']['bin/cargo']==B['runtime']['bin/cargo']==CARGO
        assert release['cargo']['sha256']==release['packed_cargo']['sha256']==CARGO
        assert 'commit-hash: 2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c' in release['cargo_version']
        assert 'host: aarch64-apple-darwin' in release['cargo_version']
        assert all(h.j('bootstrap-'+role+'-product.json')==pair['products'][role] for role in 'PC')
        for role in 'PC':
            dyl=h.j('provider-matrix/driver-'+role+'/verified.json')
            assert dyl['role']==role and dyl['object']==sha(h.read('provider-matrix/driver-'+role+'/test.o'))
            assert section(h.read('provider-matrix/driver-'+role+'/test.o'))[0]==1
            assert set(dyl['loaded'])==set(diff) and dyl['loaded'][diff[0]]['sha256']==pair['products'][role]['runtime'][diff[0]]
        assert A['rustc']==B['rustc'] and A['stage0_cargo']==B['stage0_cargo'] and A['stage0_rustc']==B['stage0_rustc']
        src.update({'driver':{k:v['runtime'][diff[0]] for k,v in pair['products'].items()},'cargo':CARGO,'archive':RELEASE,'stock_xcode_ld':ob['ld'],'stock_clang':ob['clang'],'identical_runtime':len(A['runtime'])-1,'stage0_rustc':A['stage0_rustc'],'stage0_cargo':A['stage0_cargo'],'rustc_vv':A['rustc']})
    cases={}
    for name in selected:
        try:cases[name]=h.case(name)
        except Exception as ex:raise RuntimeError('while reading '+name) from ex
    if part=='final':
        for key,im in h.drivers.items():assert im['sha256']==src['driver'][key[0]]
    data={'schema':1,'workflow':41060913032,'qa_head':QA,'raw_sha256':filehash(archive),'part':part,'source':src,'protocol':{'worker':WORKER,'plan':PLAN},'provider':h.providers,'driver_ids':h.drivers,'source_digests':h.src,'cases':cases,'images':h.images}
    claim=h.j('provider-matrix/'+('first' if part=='first' else 'terminal')+'.json')
    report=summarize(data)
    assert report['commands']==claim['commands'] and report['cases']==claim['cases']
    assert sorted(report['differential'])==sorted(row[:-1] for row in claim['parent_child_differences'])
    assert sorted(report['unwatched_mismatches'])==sorted([r[0],r[1],r[3],r[4]] for r in claim['unwatched_classification'])
    assert sorted(report['unexpected'])==sorted([r[0],r[1],r[3],r[4]] for r in claim['unexpected_declared_or_Rust_outcomes'])
    return data,report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path);p.add_argument('part',choices=('first','final'))
    p.add_argument('output',type=Path);args=p.parse_args()
    data,report=run(args.archive,args.part)
    args.output.mkdir(exist_ok=True,parents=True)
    dump(args.output/(args.part+'-observation.json.gz'),data)
    dump(args.output/(args.part+'-readback.json'),report)
    print(short({k:v for k,v in report.items() if k in ('commands','native_programs','actual_stock_ld','unexpected','differential','complete_image_comparisons')}))
