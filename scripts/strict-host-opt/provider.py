"""Unscored real Cargo builds on an isolated signed SDK and same-inode runtime/loader changes."""
from pathlib import Path
import json,shutil,subprocess

def check(m,loader,repo,env,profile,wild):
    root=m.R/'host-unicode-wild-dir-v1';root.mkdir();w=root/'work.active';out=m.O/'native-provider';out.mkdir();side=wild.with_name('libutil.so');assert not side.exists() and side.parent.is_relative_to(m.R) and not side.parent.is_symlink()
    native=root/'native';native.mkdir();donor=repo/'scripts/linux-294-parent';source=donor/'provider.c';shutil.copy2(source,out/'provider.c')
    for role,v in [('83','0053'),('47','002F')]:
        so=native/('observe-'+role+'.so');m.run(['cc','-shared','-fPIC','-O2','-DREPLACE_CODE="'+v+'"',source,'-Wl,-soname,'+str(side),'-ldl','-o',so]);shutil.copy2(so,out/so.name)
    proxies=Path(shutil.which('rustup')).absolute().parent;cargo=m.R/'sdk-21/bin/cargo'
    config={'private_state':str(root),'ruff':str(m.src),'proxy':str(proxies),'effective_home':env['HOME'],'signed_sdk':str(m.R/'sdk-21'),'registry_home':env['CARGO_HOME'],'roles':{x:{'binary':str(cargo),'head':'761ea115605c34f11a1cd29afd68812c1e1359dd','sha256':m.sha(cargo)} for x in ('parent','signed','matched294','combined','defaults-off','stock-cargo')},'qa':m.get(['git','-C',repo,'rev-parse','HEAD']).decode().strip()}
    f=root/'fixture.json';m.save(f,config);c=loader(donor/'capture.py',[f,'unused']);c.SIDE=side;c.rec=out;c.SDK=m.R/'sdk-21';c.CARGO=[str(proxies/'cargo'),'+ohm','build','-p','ruff_unicode_names2','--locked','--offline','-j4','--message-format=json']
    # capture.phase uses an explicitly frozen default env in run, so bind it on every call, including rustc and the returned reader.
    run0=c.run;records={};objects=out/'generators';objects.mkdir()
    def one(where,label,mode,keep):
        before=c.side(mode,keep);r=c.phase(where,label);m.save(where/label/'provider.json',before)
        assert r['physical']['ld'] and all(Path(q[1]).samefile(wild) for q in r['physical']['ld']),r['physical']['ld']
        if mode!='bad':
            assert r['status']==0 and r['generate_code']=={'absent':'0000','83':'0053','47':'002F'}[mode]
            entries=r['physical']['generator'];assert len(entries)==1,entries;prog=Path(entries[0][1]);ident=c.observed.identity(prog);m.save(where/label/'generator.json',ident)
            obj=objects/(ident['sha256']+'.gz');data=prog.read_bytes();assert data[:4]==b'\x7fELF' and m.h(data)==ident['sha256']
            if not obj.exists():m.gz(obj,data)
            if mode!='absent':
                opens=[q for q in r['search']['probes'] if q['kind']=='higher' and q['result']>=0 and q['call'].startswith('open')];assert any(Path(q['exe']).samefile(wild) for q in opens if q['exe']) and any(Path(q['exe']).samefile(prog) for q in opens if q['exe'] and 'build_script_build' in q['exe']),opens
        else:
            assert r['status']==101 and r['search']['probes'] and any(q['kind']=='higher' and q['call'].startswith('open') and q['result']>=0 for q in r['search']['probes'])
        return r
    try:
        for arm in ('0','1'):
            active=profile(env,arm)|{'CARGO_TARGET_DIR':str(w/'target'),'CARGO_BUILD_BUILD_DIR':str(w/'shared')};c.run=lambda *args,**kw:run0(*args,**(kw|{'env':active}));d=out/('opt'+arm);d.mkdir();hist=d/'history';hist.mkdir();clean=d/'empty';clean.mkdir();rows={};refs={}
            with c.installation():
                for label,v,keep in [('absent','absent',False),('held-83','83',False),('held-47','47',True),('malformed','bad',True),('remove','absent',False)]:rows[label]=one(hist,label,v,keep)
            for label,v in [('held-83','83'),('held-47','47'),('malformed','bad'),('remove','absent')]:
                with c.installation():refs[label]=one(clean,label,v,False)
            for label,q in refs.items():
                r=rows[label];assert q['status']==r['status']
                if not q['status']:assert q['generated']==r['generated'] and q['reader']==r['reader'] and q['reader_sha256']==r['reader_sha256']
            records[arm]={label:{k:r.get(k) for k in ('status','generated','reader','reader_sha256')} for label,r in rows.items()}
        for label in records['0']:
            for k in ('status','generated','reader'):assert records['0'][label][k]==records['1'][label][k]
        m.save(out/'verified.json',records)
    finally:c.side('absent')
