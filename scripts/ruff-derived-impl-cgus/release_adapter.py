"""Run the frozen normal Cargo receiver on the independently trained release-recipe pair."""
import hashlib,json,os,shutil,subprocess as sp,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
FROZEN=Path(os.environ['GITHUB_WORKSPACE'])/'original-receiver'
receiver=FROZEN/'scripts/ruff-derived-impl-cgus'
assert sp.check_output(['git','-C',FROZEN,'rev-parse','HEAD'],text=True).strip()=='2672756eb5b9d4e890b678d439dc6c40a29a4008'
assert hashlib.sha256((receiver/'paired.py').read_bytes()).hexdigest()=='7bd682c175e5813268c3ca209f9e93761cf9a3d59da6580e826e39b78242a5aa'
sys.path.insert(0,str(receiver));import transport,paired
spec=json.loads((HERE/'release-transports.json').read_bytes());reg=transport.REGISTER;live=transport.api;require=transport.require
assert __debug__ and set(spec)=={'P','C'}
def fetch(role,cache,dest):
    record=spec[role];role_name={'P':'parent','C':'candidate'}[role]
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
                require(source['source']==reg[role_name]and source['tree']==reg[role_name+'_tree']and source['role']==role_name and source['factory']==record['qa']and str(source['run'])==str(record['run']),'wrong trained source')
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
    return packed,proof
transport.KIT=spec;transport.fetch=fetch
if __name__=='__main__':paired.main()
