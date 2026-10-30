"""Read all 35 saved genuine Cargo, rustc, fingerprint and archive witnesses independently."""
import ast,gzip,hashlib,json,re,subprocess,sys
from pathlib import Path
def h(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_bytes())
def ar(path,*args):return subprocess.check_output(['ar',*args[:1],path,*args[1:]])
def machine(o):
    if o[:7]==bytes.fromhex('7f454c46020101'):return 'x86-64 ELF' if int.from_bytes(o[18:20],'little')==62 else ('AArch64 ELF' if int.from_bytes(o[18:20],'little')==183 else None)
    return 'arm64 Mach-O' if o[:8]==bytes.fromhex('cffaedfe0c000001') else None
phase=['cold301','repeat301','upgrade302','repeat302','downgrade301','settle301','empty302']
roles=['301','301','302','302','301','301','302']
expected={'host':('x86-64 ELF',None),'native':('x86-64 ELF','x86_64-unknown-linux-gnu'),'gnu':('AArch64 ELF','aarch64-unknown-linux-gnu'),'apple':('arm64 Mach-O','aarch64-apple-darwin'),'json':('arm64 Mach-O','aarch64-apple-darwin.json')}
def go(d,pre):
    before=read(d/'inputs.json');rr={};records=[];native=0
    assert read(d/'terminal.json')['observation_sha256']==h((d/'all-observations.json').read_bytes())
    for case,(filetype,target) in expected.items():
        configs={r:set() for r in roles};archs=[];listings=[];seen=[];crates=[];metas=[]
        for i,ph in enumerate(phase):
            q=d/case/ph; attrs=read(q/'visit.json')
            assert attrs['phase']==ph and attrs['role']==roles[i]
            raw=gzip.decompress((q/'kernel.gz').read_bytes()).decode()
            ex=[]
            for line in raw.splitlines():
                m=re.search(r'^\s*(\d+)\s+execve\("([^"]+)", (\[.*?\]), .*\)\s+= 0$',line)
                if m:
                    pid,im,arg=m.groups();ex.append((int(pid),im,ast.literal_eval(arg)))
            # rustup and its native child can share PID; select the verified SDK, not a proxy.
            cg=[row for row in ex if row[1].endswith('/toolchains/ohm/bin/cargo')];assert len(cg)==1
            assert cg[0][2][1:]==attrs['cargo_argv'][2:]
            rg=[row for row in ex if row[1].endswith('/toolchains/ohm/bin/rustc') and '--crate-name' in row[2] and '--out-dir' in row[2]]
            assert all(args[args.index('--crate-name')+1]=='selector_probe' and '-Zohm-check-relink-inputs' in args for _,_,args in rg)
            for _,_,args in rg:
                actual=args[args.index('--target')+1] if '--target' in args else None
                assert (actual is not None and actual.startswith('/') and actual.endswith('/'+target)) if case=='json' else actual==target
            assert not any(p.endswith(('/ld','/ld.lld','/ld.bfd','/ld64','/wild','/cc','/collect2')) for _,p,_ in ex)
            src=[json.loads(l) for l in (q/'stdout').read_text().splitlines() if l]
            leaf,=[x for x in src if x['reason']=='compiler-artifact']
            assert leaf['target']['name']=='selector_probe' and src[-1]=={'reason':'build-finished','success':True}
            assert bool(rg)==(not leaf['fresh']) and len(rg)==attrs['kernel_rustcs']<=1
            cnt=len(rg);seen.append(cnt);native+=cnt
            assert len(attrs['fingerprints'])==1
            cfg=attrs['fingerprints'][0][1]['config'];configs[roles[i]].add(cfg)
            p=d/'blobs'/(attrs['rlib']+'.rlib');bb=p.read_bytes();assert h(bb)==attrs['rlib']
            members=ar(p,'t').decode().splitlines();objname,=[s for s in members if s.endswith('.o')]
            obj=ar(p,'p',objname);assert h(obj)==attrs['object'] and (d/'blobs'/(h(obj)+'.o')).read_bytes()==obj
            assert machine(obj)==filetype and b'selected_word' in obj
            val=bytes.fromhex('b811000000c3') if filetype=='x86-64 ELF' else bytes.fromhex('20028052c0035fd6')
            assert val in obj
            name=re.search(r'\.([a-z0-9]{7})\.rcgu\.o$',objname)
            nonce=name[1].encode() if name else None
            meta=ar(p,'p','lib.rmeta')
            archs.append((h(bb),nonce));metas.append(h(meta));crates.append(h(obj))
            listings.append(members)
            records.append((case,ph,roles[i],cnt,cfg,h(bb),h(obj),h(meta),h(raw.encode())))
        delta=case=='apple' and not pre
        assert seen==[1,0,int(delta),0,int(delta),0,1],(case,seen)
        assert len(configs['301'])==len(configs['302'])==1 and (configs['301']!=configs['302'])==delta
        assert len(set(crates))==len(set(metas))==1,(case,crates,metas)
        assert len({hsh for hsh,_ in archs[:6]})==1
        if archs[0][0]!=archs[-1][0]:
            aa,bb=[(d/'blobs'/(v+'.rlib')).read_bytes() for v,_ in (archs[0],archs[-1])]
            na,nb=archs[0][1],archs[-1][1]
            assert na is not None and nb is not None and na!=nb and aa.count(na)==bb.count(nb)==2 and aa.replace(na,nb)==bb
        rr[case]={'machine':filetype,'rustcs':seen,'config':{k:next(iter(v)) for k,v in configs.items()},'code_sha256':crates[0],'rmeta_sha256':metas[0],'empty_rlib_exact':archs[0][0]==archs[-1][0],'warm_rlib_sha256':archs[0][0],'empty_rlib_sha256':archs[-1][0]}
    return {'product_sources':{'301':'c18e91b514b2c4e4966c9ab03232c804af3e1b57','302':'c18e91b514b2c4e4966c9ab03232c804af3e1b57' if pre else '9a102b4519b40f9034aa40533d92c83583dcb289'},'product_elf':{r:s['sha256'] for r,s in before['roles'].items()},'rustc':before['vv'],'rustc_sha256':before['rustc']['sha256'],'driver_sha256':before['driver']['sha256'],'phases':phase,'raw':h(json.dumps(records,separators=(',',':')).encode()),'cases':rr,'commands':len(records),'physical_selected_rustcs':native,'preflight':pre}
if __name__=='__main__':
    D=Path(sys.argv[1]);print(json.dumps(go(D,sys.argv[2]=='preflight'),sort_keys=True,indent=2))
