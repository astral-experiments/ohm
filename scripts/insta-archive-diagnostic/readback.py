"""Read the native original in RAM and produce a compact independent projection."""
from __future__ import annotations
import ast,collections,gzip,hashlib,io,json,os,re,struct,subprocess,sys,time,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROLES={'shipped':'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','strict-293':'735e1528ed741015c57676dccf05dbdc0ff7bed1'}
GH='/home/dev-user/.local/bin/gh-auto'
REPO='astral-experiments/ohm'
CMD=['cargo','+ohm','test','-p','ty_server','--test','e2e','--no-run','--locked','--offline','-j8','--message-format=json','--features=insta/default,insta/redactions,insta/ron']
EVENT=re.compile(r'^execve\(("(?:[^"\\]|\\.)*"),\s*(\[.*\]),\s*(?:0x[\da-f]+|NULL).*?\)\s+= 0$')
def h(b):return hashlib.sha256(b).hexdigest()
def plain(x):return (json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()
def api(s):return json.loads(subprocess.check_output([GH,'api','repos/'+REPO+'/actions/'+s],cwd=HERE))
def adj(tool,lit):
    exact=tool['physical']
    return lit==exact or (lit.endswith('/rustup-21/toolchains/ohm/bin/rustc') and exact.endswith('/sdk-21/bin/rustc')) or (lit.endswith('/rustup-21/toolchains/ohm/bin/cargo') and exact.endswith('/sdk-21/bin/cargo'))
def event(s):
    m=EVENT.fullmatch(s);assert m,s[:150]
    p,argv=map(ast.literal_eval,m.groups());assert isinstance(p,str) and isinstance(argv,list) and all(isinstance(x,str) for x in argv)
    return p,argv
def section_hashes(b):
    assert b[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',b,18)[0]==62
    off=struct.unpack_from('<Q',b,40)[0];step,n,si=struct.unpack_from('<HHH',b,58);assert step==64 and 0<si<n
    table=[struct.unpack_from('<IIQQQQIIQQ',b,off+i*step) for i in range(n)]
    s=table[si];names=b[s[4]:s[4]+s[5]];output=[]
    for row in table:
        index,typ,flags,addr,pos,length,link,info,align,entsize=row
        name=names[index:names.index(b'\0',index)].decode()
        body=b[pos:pos+length] if typ!=8 else b''
        assert typ==8 or len(body)==length
        output.append([name,typ,flags,addr,pos,length,link,info,align,entsize,h(body)])
    assert '.text' in {x[0] for x in output}
    return output
def ar_members(archive):
    buf=io.BytesIO(archive);assert buf.read(8)==b'!<arch>\n';table=b'';items={}
    while header:=buf.read(60):
        assert len(header)==60 and header[-2:]==b'`\n'
        raw=header[:16].decode().rstrip();n=int(header[48:58]);body=buf.read(n);assert len(body)==n
        if n%2:assert buf.read(1)==b'\n'
        if raw=='//':table=body;continue
        if raw in ('/','/SYM64/'):continue
        if raw.startswith('/'):
            idx=int(raw[1:]);name=table[idx:table.index(b'/\n',idx)].decode()
        else:name=raw.rstrip('/')
        assert name not in items;items[name]=h(body)
    return items
def projection(z,role,head):
    names=z.namelist();assert len(names)==len(set(names)) and all(not n.startswith('/') and '..' not in Path(n).parts for n in names)
    J=lambda p:json.loads(z.read(p)); G=lambda p:gzip.decompress(z.read(p))
    t=J('tools.json');last=J('terminal.json');ins=J('enrollment.json');native=J('native-provider.json')
    assert t['qa']==head and last['role']==t['role']==role and ROLES[role] in t['actual']['cargo']
    assert t['actual']['rustc']==t['original']['versions']['rustc'] and t['actual']['sysroot']==t['original']['versions']['sysroot']
    assert 'c79998a5cd143c445a4b2528f20953b176a65c5d' in t['actual']['rustc'] and t['source']=='93526150df078af7dd8fc4226cdcc469539d2001' and t['history']=='83a3afc3156d73ae4296f3fa74ede28e4c72bfcd'
    assert t['original_qa']=='f40b16cdb9c041c941a5e339f816111a80a84bdf' and t['lock']=='c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf'
    roster=ins['all_aliases'];assert ins['direct'] in roster and ins['cargo_product'] in roster and len(roster)==ins['original']['stat'][2]
    archived=G('reference.rlib.gz');assert h(archived)==ins['original']['sha256']==ins['reference']['sha256']
    assert ar_members(archived)==ins['members'] and len(ins['members'])==18
    assert h(G('provider.o.gz'))==native['object']['sha256'] and native['controls']==[83,0] and native['earlier']==ins['native'] and native['earlier'].endswith('/out/libgcc_s.so')
    cal=J('calibration.json');assert [r[4] for r in cal]==[False,True,False,False,False] and cal[-1][3] is False
    images={};rows={};lists={}
    for ni in names:
        if ni.startswith('elf/') and ni.endswith('.gz'):
            data=G(ni);digest=h(data);assert ni=='elf/'+digest+'.gz'
            images[digest]=[len(data),section_hashes(data)]
    for label in last['visits']:
        p=label+'/';o=J(p+'record.json');assert h(z.read(p+'record.json'))==last['records'][label]
        kernel=J(p+'raw-syscalls.json');assert all(kernel[k]==o[k] for k in kernel)
        custody=J(p+'input-custody.json');assert custody['command']==o['command']==CMD
        execs=json.loads(G(p+'native-exec.json.gz'));pids=[];r=[];links=[];input_records=[]
        for pid,stamp,line in execs:
            exe,argv=event(line)
            if adj(t['tools']['cargo'],exe) and argv[1:]==CMD[2:]:pids.append(pid)
            if adj(t['tools']['rustc'],exe) and '--crate-name' in argv and '--out-dir' in argv and not any(x.startswith('--print') for x in argv):
                crate=argv[argv.index('--crate-name')+1];mode='link-only' if any(x in ('-Zlink-only','link-only') for x in argv) else 'full';r.append([pid,crate,mode])
                if crate=='e2e':
                    refs={a.split('=',1)[1] for k,a in zip(argv,argv[1:]) if k=='--extern' and a.startswith('insta=') and a.endswith('.rlib')}
                    if mode=='full':assert refs=={ins['direct']}
                    input_records.append([pid,h(line.encode()),sorted(refs)])
            if adj(t['tools']['wild'],exe) and '-o' in argv:links.append([pid,argv[argv.index('-o')+1]])
        assert pids==[o['physical_cargo']] and r==o['rust'] and links==o['wild'],(label,pids,len(r),len(links),len(o['wild']))
        stdout=G(p+'stdout.gz');stderr=G(p+'stderr.gz');outputs=[json.loads(s) for s in stdout.splitlines()]
        arts=[a for a in outputs if a['reason']=='compiler-artifact']
        assert outputs[-1]=={'reason':'build-finished','success':o['cargo']==0} and len(arts)==o['typed']
        listed=None;im=None
        if o['cargo']==0:
            assert len(arts)==309
            ret,=[a for a in arts if a.get('executable')];assert ret['executable']==ins['e2e']==o['file']['path']
            im=o['file']['sha256'];assert images[im][0]==o['file']['stat'][3]
            listing=G(p+'list.gz');runtime=G(p+'case-out.gz')
            listed=len([s for s in listing.splitlines() if s.endswith(b': test')])
            assert [listed,h(listing)]==o['listing'][1:]
            if o['case']==0:
                assert o['listing'][0]==0 and listed==200 and b'pull_diagnostics::on_did_open: test' in listing and b'1 passed' in runtime
                lists[h(listing)]=listed
            if o['case']==83:assert o['listing'][0]==83 and listed==0
        audit=[s.split('\t') for s in z.read(p+'audit.tsv').decode().splitlines()]
        assert audit==o['audit'];ts=o['timestamp_syscalls'];remaining=list(ts)
        if o['mode']:
            pre,post=custody['before'],custody['after'];assert o['watch_before']==pre and o['watch_after']==post
            assert pre['sha256']==post['sha256']==ins['original']['sha256'] and pre['stat'][:2]==post['stat'][:2]==ins['original']['stat'][:2]
            assert o['aliases']==roster
            for a in audit:
                pid,tid,fd=map(int,a[:3]);assert pid==pids[0] and a[3]==o['mode'] and a[4:6]==['1','1'] and a[-1] in roster
                assert [int(q) for q in a[7:9]]==pre['stat'][:2] and a[-2]=='0'
                hold=(o['mode']=='hold');assert int(a[6])==hold
                row=next(i for i in remaining if i[0]==tid and f'utimensat({fd}<{a[-1]}>, NULL' in i[2] and i[2].endswith('= 0'));remaining.remove(row)
                assert (a[9:11]==a[11:13])==hold and row[2].count('UTIME_OMIT')==1+hold and (not hold or a[17:19]==a[19:21])
            assert not remaining
        parents={int(k):v for k,v in o['spawn_edges'].items()};wild_pids={i[0] for i in links};opens=[]
        for pid,stamp,ln,parent in o['provider_opens']:
            owner=pid;seen=set()
            while owner not in wild_pids and owner in parents:
                assert owner not in seen;seen.add(owner);owner=parents[owner]
            assert (owner if owner in wild_pids else None)==parent
            if parent and re.search(r'= [0-9]+(?:<[^>]*>)?$',ln) and native['earlier'] in ln:opens.append([pid,parent,ln])
        failure=b'UNRECOGNIZED_E2E_PRIVATE_LINK_SCRIPT' in stdout+stderr and b'libgcc_s.so' in stdout+stderr
        rust_invalid=b'INSTA_ARCHIVE_DIAGNOSTIC_EARLY_STOP' in stdout+stderr
        rows[label]={'full':sum(q[2]=='full' for q in r),'link_only':sum(q[2]=='link-only' for q in r),'wild':len(links),
            'root_rust':[[q[1],q[2]] for q in r if q[1] in ('ron','insta','e2e')],'root_wild':sum(Path(q[1]).name==Path(ins['e2e']).name for q in links),
            'cargo':o['cargo'],'case':o['case'],'image':im,'tests':listed,'typed':len(arts),'kernel_sha':h(z.read(p+'native-exec.json.gz')),
            'touches':ts,'audit':audit,'source':o['source'],'provider':o['provider'],'wild_opens':opens,'cutoff':o['cutoff_lines'],
            'expected_malformed_diagnostic':failure,'expected_rust_diagnostic':rust_invalid,'archive_before':o['watch_before'],'archive_after':o['watch_after'],
            'fingerprints':[v for v in stderr.decode(errors='replace').splitlines() if
                ('early cutoff check for ty_server' in v and '/e2e-' in v) or 'early cutoff check for insta v' in v or
                'early_cutoff: unit UnitIndex(97) CAN skip' in v or 'stale: missing' in v and 'ohm-foreign-span-bytes' in v],
            'direct_externs':input_records}
    assert len(lists)==1
    return {'tools':t,'enrolled':ins,'native':native,'calibration':cal,'images':images,'rows':rows,
            'member_count':len(names),'terminal_sha':h(z.read('terminal.json')),'inventory':lists}
def compare(p):
    r=p['rows']; calibration=p['calibration']
    assert [x[4] for x in calibration]==[False,True,False,False,False]
    assert len(r)==33 and r['cold']['cargo']==0 and r['cold']['case']==0
    old=r['cold']['image'];new=r['empty-edited']['image'];native=r['empty-valid']['image']
    assert len({old,new,native})==3 and all(x in p['images'] for x in (old,new,native))
    assert (r['empty-valid']['cargo'],r['empty-valid']['case'])==(0,83) and r['empty-valid']['wild_opens'] and r['empty-valid']['root_wild']==1
    assert (r['empty-malformed']['cargo'],r['empty-malformed']['case'])==(101,None) and r['empty-malformed']['expected_malformed_diagnostic'] and r['empty-malformed']['wild_opens'] and r['empty-malformed']['root_wild']==1
    assert r['empty-edited']['case']==0 and r['empty-edited']['root_wild']==1
    assert r['unwrapped-repeat']['image']==r['unwrapped-cold']['image'] and not r['unwrapped-repeat']['audit'] and r['unwrapped-repeat']['touches']
    assert r['unarmed-hook-repeat']['image']==old and not r['unarmed-hook-repeat']['audit'] and r['unarmed-hook-repeat']['touches']
    assert (r['hold-invalid-rust']['cargo'],r['hold-invalid-rust']['case'])==(101,None) and r['hold-invalid-rust']['expected_rust_diagnostic']
    assert r['hold-repaired-rust']['case']==0 and r['hold-repaired-rust']['image']==old
    result={'old':old,'new':new,'valid':native,'disagreements':[]}
    for pol in ('allow','hold'):
        for key,dig in [('edited',new),('restored',old)]:
            b=r[pol+'-'+key]
            assert b['image']==dig and b['case']==0 and b['root_wild']==1 and b['audit']
        for k in ('1','2'):
            q=r[pol+'-repeat-'+k]
            assert q['audit'] and q['cutoff'] and q['image']==old and ['ron','full'] in q['root_rust'] and not any(i[0]=='insta' for i in q['root_rust'])
        for tag,expected in [('valid',(0,83,native)),('malformed',(101,None,None))]:
            for extra in ('','-force'):
                k=pol+'-'+tag+extra;q=r[k];actual=(q['cargo'],q['case'],q['image'])
                if pol=='allow' or extra=='-force':
                    assert actual==expected and q['root_wild']==1 and q['wild_opens'],(k,actual,expected,q['root_wild'],q['wild_opens'])
                    if tag=='malformed':assert q['expected_malformed_diagnostic']
                elif actual!=expected:result['disagreements'].append({'visit':k,'got':actual,'expected':expected})
            for extra in ('','-force'):
                k=pol+'-removed-'+tag+extra;q=r[k]
                if pol=='allow' or extra=='-force':
                    assert q['image']==old and q['case']==0 and q['root_wild']==1,(k,q['case'],q['image'])
                elif (q['image'],q['case'])!=(old,0):result['disagreements'].append({'visit':k,'got':[q['cargo'],q['case'],q['image']],'expected':[0,0,old]})
    return result

def strict_no_touch(z,head):
    names=z.namelist();assert len(names)==len(set(names)) and not any(n.startswith('hold-') for n in names)
    meta=json.loads(z.read('tools.json'));assert meta['qa']==head and meta['role']=='strict-293' and ROLES['strict-293'] in meta['actual']['cargo']
    rows={}
    for ph in ('unwrapped-cold','unwrapped-repeat'):
        rec=json.loads(z.read(ph+'/record.json'));st=json.loads(z.read(ph+'/raw-syscalls.json'))
        assert st['timestamp_syscalls']==rec['timestamp_syscalls']==[] and not z.read(ph+'/audit.tsv')
        assert rec['raw'] and rec['mode'] is None and (rec['cargo'],rec['case'],rec['typed'])==(0,0,309)
        ro=[];ws=[];cargos=[]
        for pid,ts,line in json.loads(gzip.decompress(z.read(ph+'/native-exec.json.gz'))):
            name,args=event(line)
            if adj(meta['tools']['cargo'],name) and args[1:]==CMD[2:]:cargos.append(pid)
            if adj(meta['tools']['rustc'],name) and '--crate-name' in args and '--out-dir' in args and not any(q.startswith('--print') for q in args):
                ro.append([pid,args[args.index('--crate-name')+1],'link-only' if any(q in ('-Zlink-only','link-only') for q in args) else 'full'])
            if adj(meta['tools']['wild'],name) and '-o' in args:ws.append([pid,args[args.index('-o')+1]])
        assert cargos==[rec['physical_cargo']] and ro==rec['rust'] and ws==rec['wild']
        listed=gzip.decompress(z.read(ph+'/list.gz'));inv=h(listed)
        assert [0,sum(q.endswith(b': test') for q in listed.splitlines()),inv]==rec['listing']==[0,200,inv]
        assert b'1 passed' in gzip.decompress(z.read(ph+'/case-out.gz'))
        digest=rec['file']['sha256'];image=gzip.decompress(z.read('elf/'+digest+'.gz'))
        assert len(image)==rec['file']['stat'][3] and h(image)==digest;sec=section_hashes(image)
        rows[ph]={'image':digest,'image_bytes':len(image),'image_sections':sec,'listing':inv,
            'full':sum(v[2]=='full' for v in ro),'link_only':sum(v[2]=='link-only' for v in ro),'wild':len(ws),
            'rust':ro if ph.endswith('repeat') else [],'wild_roots':ws if ph.endswith('repeat') else [],
            'timestamp_syscalls':[],'cutoff':rec['cutoff_lines'],'cargo':0,'case':0,'typed':309}
    a,b=rows.values();assert a['image']==b['image'] and a['listing']==b['listing'] and b['cutoff']
    assert sorted((v[1],v[2]) for v in b['rust'])==[('build_script_build','full'),('e2e','link-only'),('ron','full'),('unicode_names2','full')]
    assert b['wild']==2 and sum(Path(x[1]).name.startswith('e2e-') for x in b['wild_roots'])==1
    return {'role':'strict-293','status':'no eligible timestamp syscall in native unwrapped repeat','tools':meta,'rows':rows,'member_count':len(names)}

def extract(out,run,head):
    details=api('runs/'+str(run));assert details['head_sha']==head and details['status']=='completed'
    items=api('runs/'+str(run)+'/artifacts')['artifacts']
    assert len(items)==2 and all(not a['expired'] and a['workflow_run']['id']==run and a['workflow_run']['head_sha']==head for a in items)
    report={}
    for a in items:
        role,=[r for r in ROLES if a['name']=='insta-archive-'+r+'-published-21-ty-server-e2e']
        avail=int(re.search(r'^MemAvailable:\s*(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])*1024
        assert avail>6*2**30+a['size_in_bytes'] and a['size_in_bytes']<2**30
        with os.fdopen(os.memfd_create('private-native-archive'), 'w+b') as f:
            for attempt in range(3):
                f.seek(0);f.truncate()
                v=subprocess.run([GH,'api','repos/'+REPO+'/actions/artifacts/'+str(a['id'])+'/zip'],cwd=HERE,stdout=f,stderr=subprocess.PIPE)
                if v.returncode==0:break
                assert attempt<2 and any(s in v.stderr for s in (b'502',b'503',b'504')),v.stderr
                time.sleep(2+attempt)
            assert f.tell()==a['size_in_bytes'];f.seek(0);digest=hashlib.file_digest(f,'sha256').hexdigest()
            assert 'sha256:'+digest==a['digest'];f.seek(0)
            with zipfile.ZipFile(f) as z:
                if 'terminal.json' not in z.namelist() and role=='strict-293' and 'unwrapped-repeat/record.json' in z.namelist():
                    proj=strict_no_touch(z,head)
                    proj['upstream_archive']={'id':a['id'],'bytes':a['size_in_bytes'],'zip_sha256':digest,'run':run,'head':head}
                    report[role]=proj
                    dest=out/(role+'.json.gz');encoded=gzip.compress(plain(proj),mtime=0)
                    if dest.exists():assert dest.read_bytes()==encoded
                    else:dest.write_bytes(encoded)
                    print(role,proj['status'],flush=True);continue
                if 'terminal.json' not in z.namelist():
                    print('incomplete',role,len(z.namelist()),z.namelist()[-16:])
                    for n in z.namelist():
                        if n.endswith('raw-syscalls.json') or n.endswith('record.json'):
                            q=json.loads(z.read(n));print(n, q.get('cargo'),len(q['rust']),len(q['wild']),q['timestamp_syscalls'][:3])
                    continue
                proj=projection(z,role,head)
                for phase in ('empty-edited','empty-valid','empty-malformed'):
                    st=json.loads(z.read(phase+'-starting-files.json'))
                    assert st==([] if phase=='empty-edited' else [proj['enrolled']['native']])
                proj['controls']=compare(proj)
                proj['upstream_archive']={'id':a['id'],'bytes':a['size_in_bytes'],'zip_sha256':digest,'run':run,'head':head}
                report[role]=proj
                dest=out/(role+'.json.gz');encoded=gzip.compress(plain(proj),mtime=0)
                if dest.exists():assert dest.read_bytes()==encoded
                else:dest.write_bytes(encoded)
        if role in report:
            print(role, {k:[r['full'],r['link_only'],r['wild'],r['cargo'],r['case']] for k,r in proj['rows'].items()},flush=True)
    if len(report)==2:
        a,b=report.values()
        assert a['tools']['original']['physical_driver']['sha256']==b['tools']['original']['physical_driver']['sha256']
        assert all(a['tools']['tools'][k]['sha256']==b['tools']['tools'][k]['sha256'] for k in ('rustc','wild','system_ld'))
        print('Retained',[(name,report[name]['upstream_archive']['zip_sha256']) for name in sorted(report)],flush=True)
        return
    raise ValueError('Missing terminal native evidence')
if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=int,required=True);ap.add_argument('--head',required=True);ap.add_argument('--out',required=True,type=Path)
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True);extract(a.out,a.run,a.head)
