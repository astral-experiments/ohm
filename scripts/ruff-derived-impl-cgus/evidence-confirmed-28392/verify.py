"""Reopen all twelve real Cargo counters, library process counters, object ledgers and native bodies."""
from pathlib import Path
import hashlib,io,json,statistics,subprocess,sys,zipfile
here=Path(__file__).resolve().parent;sys.path.insert(0,str(here.parent));from reopen import lifetimes,roster
file=here/'original-readback.zip';assert hashlib.file_digest(file.open('rb'),'sha256').hexdigest()=='97ba4240cee0efe91a7d0145b43b5ca2f7aa16fb642f5a93ddf14d1adfa962f7'
z=zipfile.ZipFile(file);raw=zipfile.ZipFile(io.BytesIO(z.read('raw-hardware-and-controls.zip')));rd=lambda archive,n:json.loads(archive.read(n));decision=rd(z,'decision.json');rows=[];boots=set();bodies=set();sources=['f5a51d8cc3e76236c2d0f17d495d59ebb03306e4','025c787a77f5d887ba9bf860ef69b7756b59fe57']
for i,order in enumerate(('PC','CP','CP','PC','PC','CP')):
    prefix=str(i)+'/';x=rd(z,str(i)+'.json');bind=rd(z,str(i)+'-binding.json');native=rd(z,str(i)+'-changed-object-bindings.json');conf=rd(raw,prefix+'confirmation.json');reg=rd(raw,prefix+'registration.json')
    assert conf['slot']==i and conf['recorded_receipt']=='d8596b7fafd31b4f959c7561a921d56705513956'and conf['real_driver_sources']==sources and x['sha256']==bind['sha256']
    assert bind['run']==41741619584 and x['order']==reg['order']==order and x['boot']==reg['boot'] and x['boot']not in boots
    boots.add(x['boot']);out=[]
    for k in 'PC':
        arm=x['roles'][k];r=prefix+k+'/';h=rd(raw,r+'edit/hardware.json');assert h['instructions']==arm['ordinary']['edit']and h['instructions']>0 and h['enabled']==h['running']>0 and h['status']==0
        task=lifetimes(raw,r+'observed-edit/kernel-execs');lib,=[n for name,ty,n in task['rustcs']if name=='ruff'and ty=='lib'];assert lib==arm['lifetime']['lib']and task['wild']
        for stage in ('old-unchanged','edited-unchanged'):
            idle=lifetimes(raw,r+stage+'/kernel-execs');assert not idle['rustcs']and not idle['wild']
        evidence={};physical={}
        for stage in ('cold-old','edit','empty-new'):
            actual,ar,_=roster(raw,r+stage);physical[stage]=actual
            for name,size,digest in native[k+'/'+stage]:
                assert actual['lib'][name][4:]==[size,digest];body='changed-object-originals/'+digest+'.o.zst'
                if body not in bodies:
                    data=subprocess.check_output(['zstd','-qdc'],input=z.read(body));assert len(data)==size and data.startswith(b'\x7fELF')and hashlib.sha256(data).hexdigest()==digest;bodies.add(body)
            evidence[stage]=rd(raw,r+stage+'/products.json')
        for unit in ('lib','bin'):
            a,b=(physical[ph][unit]for ph in ('cold-old','edit'));identical=sum(v==a.get(n)for n,v in b.items());assert identical==arm['transitions'][unit]['physical_donors']
            fresh=physical['empty-new'][unit];assert {n:v[4:] for n,v in b.items()}=={n:v[4:]for n,v in fresh.items()}
        assert evidence['edit']['elf']==evidence['empty-new']['elf']and evidence['edit']['verdict']==evidence['empty-new']['verdict']
        assert b'--config "lint.line-length = 100"'in raw.read(r+'cold-old/help.stdout')and b'--config "line-length = 100"'in raw.read(r+'edit/help.stdout')
        out.append((h['instructions'],lib))
    rows.append(out)
for i,key in enumerate(('whole_instructions_percent_fewer','secondary_affected_lib_rustc_percent_fewer')):
    p=[100*(1-c[i]/a[i])for a,c in rows];v=decision[key]['edit']if i==0 else decision[key];assert(v['minimum'],v['median'],v['maximum'])==(min(p),statistics.median(p),max(p))
    print(key,statistics.median(p),[min(p),max(p)])
assert len(boots)==6 and len(bodies)==12 and decision['six_boot_threshold']and decision['nonparametric_median_interval_confidence']==1-2*0.5**6
print('six source-bound Linux boots, twelve normal Cargo invocations, twelve distinct edited object bodies')
