"""Build two private Linux diagnostics from exact stock 0.11; leave the signed linker intact."""
from pathlib import Path
import json,os,shutil,subprocess as sp
TAG='e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11'
def build(w,base,proof):
    src=Path(os.environ['GITHUB_WORKSPACE'])/'wild-source'
    def git(*a):return sp.check_output(['git','-C',src,*a],text=True).strip()
    assert git('rev-parse','HEAD')==TAG and not git('status','--porcelain')
    kit=w.root/'source-wild';kit.mkdir();log=proof/'source-wild';log.mkdir()
    env=dict(base,CARGO_HOME=str(kit/'cargo-home'),CARGO_TARGET_DIR=str(kit/'target'),CARGO_BUILD_BUILD_DIR=str(kit/'shared'))
    command=['cargo','+ohm','-Zohm-defaults=no','build','--release','--locked','-p','wild-linker','--bin','wild','-j4']
    patch=Path(__file__).with_name('lookup-diagnostic.patch')
    record={'revision':TAG,'tree':git('rev-parse','HEAD^{tree}'),'lock':w.hf(src/'Cargo.lock'),'patch':w.hf(patch),'source_arms':{}}
    network=dict(env);network.pop('CARGO_NET_OFFLINE',None)
    sp.run(['cargo','+ohm','fetch','--locked'],cwd=src,env=network,check=True,timeout=900)
    for arm in ('stock','observer'):
        w.guard()
        if arm=='observer':
            sp.run(['git','-C',src,'apply','--check',patch],check=True);sp.run(['git','-C',src,'apply',patch],check=True)
            assert git('diff','--name-only').splitlines()==['libwild/src/fs.rs','libwild/src/input_data.rs']
        with(log/(arm+'.stdout')).open('wb')as so,(log/(arm+'.stderr')).open('wb')as se:
            proc=sp.run(command,cwd=src,env=env,stdout=so,stderr=se,timeout=30*60)
        assert proc.returncode==0,(arm,(log/(arm+'.stderr')).read_text()[-2500:])
        p=kit/arm;shutil.copy2(kit/'target/release/wild',p)
        info=sp.run([p,'--version'],capture_output=True,check=True)
        record['source_arms'][arm]={'path':str(p),'bytes':p.stat().st_size,'sha256':w.hf(p),'version':info.stdout.decode(),'argv':command,'source_sha256':{k:w.hf(src/k)for k in ('libwild/src/fs.rs','libwild/src/input_data.rs')}}
        (log/'identities.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    assert record['source_arms']['stock']['sha256']!=record['source_arms']['observer']['sha256']
    return kit
