"""Open the source-qualified stage2 compiler and run the same integer-array safety probe."""
import hashlib,json,os,shutil,subprocess as sp,sys,tempfile,zipfile
from pathlib import Path
import transport
reg=transport.REGISTER;spec=transport.KIT;live=transport.api;require=transport.require
def fetch(role,cache,dest):
    arm=reg['compiler_arms'][role];record=spec[role];role_name=arm['factory_role']
    require(record and (record['run'],record['qa'])==(arm['factory_run'],arm['factory_head']),'missing or unregistered release-recipe transport')
    run=live('actions/runs/'+str(record['run']));job=live('actions/jobs/'+str(record['job']))
    require(run['head_sha']==record['qa'] and run['run_attempt']==1 and run['conclusion']=='success' and job['run_id']==record['run'] and job['conclusion']=='success','wrong release-recipe factory')
    cache.mkdir(parents=True,exist_ok=True);dest.mkdir(parents=True)
    for key in ('qualification','sdk'):
        ident,expect=record[key];meta=live('actions/artifacts/'+str(ident));require(meta['workflow_run']['id']==record['run']and not meta['expired'] and meta['digest']=='sha256:'+expect and meta['size_in_bytes']<900*2**20,'unbound release-recipe original')
        archive=cache/(expect+'.zip')
        if not archive.exists():
            with archive.open('xb')as f:sp.run(['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+str(ident)+'/zip'],stdout=f,check=True)
        require(archive.stat().st_size==meta['size_in_bytes']and transport.sha(archive)==expect,'incorrect original release-recipe SDK')
        with zipfile.ZipFile(archive)as z:
            require(len(z.namelist())==len(set(z.namelist()))and all(not Path(n).is_absolute() and '..'not in Path(n).parts for n in z.namelist()),'invalid ZIP member')
            if key=='qualification':
                for name in ('bootstrap.toml','training.json','source.json','sdk.json','native.json','sdk-sha256'):
                    require(z.getinfo(name).file_size<1<<20,'wrong source/training qualification');(dest/name).write_bytes(z.read(name))
                rd=lambda key:json.loads((dest/(key+'.json')).read_bytes())
                source=rd('source');proof=rd('sdk');trained=rd('training');native=rd('native')
                require(source['source']==arm['source']and source['tree']==arm['tree']and source['role']==role_name and source['factory']==record['qa']and str(source['run'])==str(record['run']),'wrong trained source')
                require(proof['driver']==record['driver'] and proof['role']==role_name and source['source']in proof['versions']['rustc']and reg['cargo']in proof['versions']['cargo'],'wrong trained driver')
                require(proof['release_cargo']==reg['release_members']['bin/cargo']['sha256']and proof['wild']==reg['release_members']['lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd']['sha256'],'changed signed cargo or Wild')
                require(trained['script']==record['script'] and trained['config']==transport.sha(dest/'bootstrap.toml')==record['config'] and set(trained['profiles'])=={'rustc','rustdoc','clippy','rustfmt'}and all(len(v[0])==64 and v[1]>0 for v in trained['profiles'].values()),'missing real trained native compiler profiles')
                cfg=(dest/'bootstrap.toml').read_text();require('lto = "thin"' in cfg and 'codegen-units = 1' in cfg,'wrong compiled release settings')
                require(native['baseline']=='Row(42)' and native['rejected_twice']=='E0308'and (dest/'sdk-sha256').read_text().strip()==record['tar'],'missing native fixture or incorrect SDK')
                transport.jsonfile(dest/'bootstrap.json',{'kind':'stage2-release','config':trained['config'],'build_script':trained['script'],'common_source_distribution_recipe':source['verified_release_coordinator']})
            else:
                require(z.namelist()==['sdk.tar.zst']and z.getinfo('sdk.tar.zst').file_size<900*2**20,'incorrect trained SDK archive')
                packed=cache/(record['tar']+'.tar.zst')
                if not packed.exists():
                    with z.open('sdk.tar.zst')as f,packed.open('xb')as t:shutil.copyfileobj(f,t,1<<20)
                require(transport.sha(packed)==record['tar'],'incorrect trained SDK bytes')
    with tempfile.TemporaryDirectory(dir=cache.parent,prefix="stage2-array-guard-")as root:
        at=Path(root);alias=at/"rustup/toolchains/ohm"
        transport.install(packed,proof,at/"sdk",alias)
        env={k:os.environ[k] for k in ("PATH","HOME","USER","LANG","TZ")if k in os.environ}
        env["RUSTUP_HOME"]=str(alias.parent.parent)
        producer=Path(__file__).with_name("array_probe.py")
        require(transport.sha(producer)==reg["trained"]["array_probe"],"changed array behavior probe")
        sp.run([sys.executable,"-IB",producer,at/"probes",role],env=env,check=True)
        extra=Path(__file__).with_name("aggregate_probe.py")
        require(transport.sha(extra)==reg["sources"]["aggregate_probe.py"]["sha256"],"changed tuple/char probe")
        sp.run([sys.executable,"-IB",extra,at/"aggregate",role],env=env,check=True)
        shutil.copy2(at/"aggregate/verdict.json",dest/"aggregate-verdict.json")
        (dest/"probes").mkdir()
        shutil.copy2(at/"probes/verdict.json",dest/"probes/verdict.json")
    return packed,proof
