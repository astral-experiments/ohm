"""One focused native history per preexisting Cargo. The signed Rust and Wild stay identical."""
import gzip, hashlib, json, os, re, runpy, struct, subprocess, sys
from pathlib import Path
import e2e_reason as e
w,c,slot,root,out=e.w,e.c,e.slot,e.root,e.out
def read(p):return json.loads(p.read_bytes())
def file_identity(p):return {'path':str(p),'sha256':e.sha(p),'stat':e.stat(p)}
def hosted_credential(fn):
    token=os.environ.pop('QUALIFICATION_TOKEN')
    os.environ['GH_TOKEN']=token
    try:return fn()
    finally:os.environ.pop('GH_TOKEN',None)
def sections(p):
    with p.open('rb') as f:
        header=f.read(64);assert header[:6]==b'\x7fELF\x02\x01'
        off=struct.unpack_from('<Q',header,40)[0];size,count,strings=struct.unpack_from('<HHH',header,58)
        assert size==64 and 0<strings<count
        f.seek(off);tbl=[struct.unpack('<IIQQQQIIQQ',f.read(64)) for _ in range(count)]
        start,length=tbl[strings][4:6];f.seek(start);names=f.read(length);rows=[]
        for i,(n,typ,fl,addr,pos,length,lnk,info,align,item) in enumerate(tbl):
            name=names[n:names.index(b'\0',n)].decode();f.seek(pos)
            data=f.read(length) if typ!=8 else b'';assert typ==8 or len(data)==length
            rows.append([name,typ,fl,addr,pos,length,lnk,info,align,item,e.digest(data)])
        return rows
def snapshot_elf(label):
    row=read(out/label/'observed.json');p=Path(row['e2e']);assert e.sha(p)==row['e2e_sha256']
    e.save(out/label/'elf-sections.json',{'file':file_identity(p),'sections':sections(p)})
    return row
def provider(repo,env,tools,observed):
    # An earlier ordinary search root already passed to the actual e2e Wild.
    rows=json.loads(gzip.decompress((out/'cold/kernel.json.gz').read_bytes()))
    cold=read(out/'cold/observed.json');ep=Path(cold['e2e'])
    calls=[c.event(line.encode()) for _,_,line in rows]
    wild,=[args for exe,args in calls if Path(exe).resolve()==Path(tools['wild']['physical']) and '-o' in args and Path(args[args.index('-o')+1]).name==ep.name]
    dirs=[Path(a[2:]) for a in wild if a.startswith('-L') and len(a)>2]+[Path(v) for k,v in zip(wild,wild[1:]) if k=='-L']
    psm,={v for v in dirs if '/psm/' in str(v) and v.name=='out'}
    assert psm.resolve().is_relative_to(slot) and psm.is_dir() and '-lgcc_s' in wild
    earlier=psm/'libgcc_s.so';assert not os.path.lexists(earlier)
    cp=root/'native-shadow';cp.mkdir();src=cp/'selected.c';obj=cp/'selected.o';src.write_text(
        '#include <unistd.h>\nstatic void init(int ac,char**av,char**env){if(ac<1||!av||!av[0])return;'
        'const char*b=av[0];for(const char*p=b;*p;p++)if(*p==47)b=p+1;'
        "if(b[0]=='e'&&b[1]=='2'&&b[2]=='e'&&b[3]=='-')_exit(83);}\n"
        '__attribute__((used,section(".preinit_array"))) static void(*slot)(int,char**,char**)=init;\n')
    system=Path(subprocess.check_output(['gcc','-print-file-name=libgcc_s.so'],text=True).strip()).resolve(strict=True)
    subprocess.run(['gcc','-fPIE','-O1','-c',src,'-o',obj],check=True)
    # Confirm conditional preinit works before touching the scored test's private -L.
    guard=cp/'e2e-private-control';ordinary=cp/'other-program';main=cp/'main.c';main.write_text('int main(void){return 0;}\n')
    subprocess.run(['gcc',main,obj,'-o',guard],check=True);os.link(guard,ordinary)
    assert [subprocess.run([p]).returncode for p in (guard,ordinary)]==[83,0]
    valid=f'INPUT ( "{obj}" "{system}" )\n'.encode()
    bad=b'UNRECOGNIZED_E2E_PRIVATE_LINK_SCRIPT\n'
    e.save(out/'native-provider-sources.json',{'c':src.read_text(),'object':file_identity(obj),'valid':valid.decode(),'invalid':bad.decode(),'system':file_identity(system),'earlier':str(earlier),'control_exit':[83,0]})
    e.gz(out/'native-provider-object.gz',obj.read_bytes())
    records={}
    for name,contents,force in [('valid',valid,False),('valid-force',valid,True),('malformed',bad,False),('malformed-force',bad,True),('removed',None,False)]:
        d=out/('provider-'+name);d.mkdir()
        if name=='valid':earlier.write_bytes(contents)
        elif name=='malformed':earlier.write_bytes(contents)
        elif name=='removed':earlier.unlink()
        if force and ep.exists():ep.unlink()
        before=file_identity(earlier) if earlier.exists() else None
        tr=cp/name;tr.mkdir()
        args=['strace','-ff','-q','-s','262144','-e','trace=execve,execveat,openat,clone,clone3,exit_group','-o',str(tr/'kernel'),*e.CMD]
        with (tr/'cargo-out').open('wb') as so,(tr/'cargo-err').open('wb') as se:
            v=subprocess.run(args,cwd=repo,env=env,stdout=so,stderr=se,timeout=300)
        rr=[];wild_roots=set();spawn={};lookups=[]
        for f in sorted(tr.glob('kernel.*')):
            pid=int(f.suffix[1:])
            for line in f.read_bytes().splitlines():
                if line.startswith(b'execve(') and line.endswith(b'= 0'):
                    exe,argv=c.event(line);rr.append([pid,line.decode()])
                    if Path(exe).resolve()==Path(tools['wild']['physical']):wild_roots.add(pid)
                if line.startswith((b'clone(',b'clone3(')) and b'CLONE_THREAD' in line:
                    kid=re.search(rb'= (\d+)$',line)
                    if kid:spawn[int(kid[1])]=pid
                if line.startswith(b'openat(') and os.fsencode(earlier) in line:lookups.append([pid,line.decode()])
        def native_threads(pid):
            while pid not in wild_roots and pid in spawn:pid=spawn[pid]
            return pid in wild_roots
        opened=[entry for entry in lookups if native_threads(entry[0])]
        e.save(d/'origin.json',{'wild_pids':sorted(wild_roots),'thread_edges':spawn,'all_candidate_lookups':lookups})
        e.gz(d/'kernel.json.gz',json.dumps(rr,separators=(',',':')).encode());e.save(d/'opens.json',opened)
        for k in ('out','err'):e.gz(d/('cargo-'+k+'.gz'),(tr/('cargo-'+k)).read_bytes())
        check=None;elf=None
        if v.returncode==0:
            art,=[j for j in map(json.loads,(tr/'cargo-out').read_bytes().splitlines()) if j.get('executable') and j['target']['name']=='e2e']
            assert Path(art['executable'])==ep
            test=subprocess.run([ep,c.RUN_CASE,'--exact'],cwd=repo,env=env|{'INSTA_WORKSPACE_ROOT':str(repo),'INSTA_UPDATE':'no'},capture_output=True,timeout=120)
            check=test.returncode;elf=file_identity(ep);e.gz(d/'test-out.gz',test.stdout);e.gz(d/'test-err.gz',test.stderr)
        rec={'cargo':v.returncode,'case':check,'ep':elf,'candidate':before,'forced_missing_private_output':force,'wild_positive_opens':opened}
        e.save(d/'result.json',rec);records[name]=rec
    e.save(out/'provider-summary.json',records)
def main():
    role=os.environ['FOCUSED_CARGO']
    assert role in ('shipped','strict-293') and not root.exists();root.mkdir();out.mkdir();w.room(root,65)
    eligible_src=Path(sys.argv[2]).resolve();assert e.sha(eligible_src)=='84d094bc06fe4d65efc869259e7760530d813d515f47237da1744c6791fe61a0'
    def acquire():
        e.prepare(root,'21')
        if role=='strict-293':runpy.run_path(str(eligible_src))['acquire']('gh',out/'cargo-293-source.json',root/'materialized-classic')
    hosted_credential(acquire)
    repo=root/'source';subprocess.run(['git','init','-q',repo],check=True)
    for n,r in [(1,c.RUFF),(2,c.HISTORY)]:w.git(repo,'fetch','-q','--no-tags','--depth='+str(n),'https://github.com/astral-sh/ruff.git',r)
    w.git(repo,'switch','-q','--detach',c.RUFF);assert w.git(repo,'rev-parse','HEAD^{tree}').decode().strip()==c.TREE
    assert w.git(repo,'diff','--binary','--abbrev=10',c.HISTORY+'^',c.HISTORY)==(c.FIX/'historical.patch').read_bytes()
    w.replace(repo,'original');slot.mkdir();env=w.environment(root,'21',slot)
    tools=w.tools(root,'21',env);physical=root/'sdk-21/bin/cargo';src=read(root/'receipts/21/tools.json')
    if role=='strict-293':
        physical.rename(root/'shipped-cargo');(root/'materialized-classic/cargo').rename(physical)
        assert e.sha(physical)=='869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'
    tools['cargo']=w.fx(physical)
    actual={n:subprocess.check_output(cmd,env=env,text=True).strip() for n,cmd in
            [('cargo',['cargo','+ohm','-Vv']),('rustc',['rustc','+ohm','-vV']),('sysroot',['rustc','+ohm','--print','sysroot'])]}
    assert actual['rustc']==src['versions']['rustc'] and actual['sysroot']==src['versions']['sysroot']
    assert ('735e1528ed741015c57676dccf05dbdc0ff7bed1' if role=='strict-293' else '2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c') in actual['cargo']
    e.save(out/'subjects.json',{'role':role,'sdk':read(root/'receipts/21/custody.json'),'tools':tools,'actual':actual,'signed_physical':src,'source':c.RUFF,'tree':c.TREE,'lock':e.sha(repo/'Cargo.lock'),'original_qa':w.git(e.orig,'rev-parse','HEAD').decode().strip(),'history':c.HISTORY})
    fetch={k:v for k,v in env.items() if k!='CARGO_NET_OFFLINE'};subprocess.run(['cargo','+ohm','fetch','--locked'],cwd=repo,env=fetch,check=True)
    e.CMD.append('--features=insta/default,insta/redactions,insta/ron')
    prev='original';rows={}
    for lab,state,log in [('cold','original',False),('unchanged','original',False),('explain-unchanged','original',True),
                          ('edited','reversed',True),('restored','original',True),('final-unchanged','original',False)]:
        if state!=prev:w.replace(repo,state)
        e.phase(repo,env,tools,lab,state,log);rows[lab]=snapshot_elf(lab);prev=state
    provider(repo,env,tools,rows)
    # Preserve original generation. Clean edited trial sees the literal same paths, same compiler and immutable checkout.
    parked=root/'retained-trained';parked.mkdir()
    for part in ('shared','target'):(slot/part).rename(parked/part)
    assert all(not (slot/n).exists() for n in ('shared','target'))
    w.replace(repo,'reversed');e.phase(repo,env,tools,'clean-edited','reversed',False);rows['clean-edited']=snapshot_elf('clean-edited')
    tests={r['inventory_sha256'] for r in rows.values()};assert len(tests)==1 and all(r['case_exit']==0 for r in rows.values())
    e.save(out/'terminal.json',{'phase_files':{p.parent.name:e.sha(p) for p in sorted(out.glob('*/observed.json'))},'role':role,
        'cold_restored_equal':rows['cold']['e2e_sha256']==rows['restored']['e2e_sha256'],
        'edited_empty_equal':rows['edited']['e2e_sha256']==rows['clean-edited']['e2e_sha256'],
        'real_historical_edit':c.HISTORY,'scope':'single original e2e, authentic Ron feature; observed absolute timings under process trace only'})
if __name__=='__main__':main()
