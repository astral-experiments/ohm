"""Reopen actual SDKs, physical Xcode and rustc jobs, initial/changed/error and same-inode native archive behavior."""
import argparse,gzip,hashlib,json,sys
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native import Dataset,sha,P,C,R,S,SIGNED,PACK,TREE,compact,pretty,write,digestfile

STEPS=('lower','unchanged-lower','higher-no-rust','higher-rust-edit','malformed-no-rust','malformed-rust-edit','repair-before-missing','missing-no-rust','missing-rust-edit','restored-rust-edit','restored-unchanged')
STAMP=('original-higher','repeat-higher','overwrite-same-stamp','repeat-replacement','restore-same-stamp')
NO={'higher-no-rust','malformed-no-rust','missing-no-rust','repair-before-missing'}

def sources(v):
    from counter_scope import scope
    calibration=scope(v)
    prod=v.js('cargo293/product.json');pin=v.js('fixed-cargo-293.json');root=v.js('293-runtime/pair.json');pair=v.js('pair.json');signed=v.js('release.json')
    assert sha(v.raw('cargo293/product.json'))==pin['build_receipt'] and prod['source']==v.js('cargo293/source.json')
    assert prod['source']['commit']==R and prod['source']['tree']==TREE and prod['source']['source_pack']==PACK and prod['source']['entries']==3114
    assert prod['build_stdout']==sha(v.raw('cargo293/build.stdout')) and prod['build_stderr']==sha(v.raw('cargo293/build.stderr'))
    assert json.loads(v.raw('cargo293/build.stdout').splitlines()[-1])=={'reason':'build-finished','success':True} and v.js('cargo293/filesystem.json')['FilesystemType'].lower()=='apfs'
    assert signed['archive']==SIGNED and signed['cargo']['sha256']==prod['builder_cargo']['sha256']==pin['signed_reference'] and S in prod['builder']
    assert pin['commit']==R and pin['binary']['sha256']==prod['binary']['sha256'] and {'all-static','ohm-defaults'}<=set(prod['features']) and R in prod['version']
    assert set(root)=={'P','C'} and root['P']['cargo_ctime_ns']==root['C']['cargo_ctime_ns'] and len(pair['differ'])==1
    assert sha(v.raw('registration.md'))=='ae6cf3861a3494db849a57b1b00b71f15a05d55e6d67c0963ba0a90228b786d5'
    transport=v.js('crc-source-transport.json');assert [transport['parent'],transport['child']]==[P,C]
    runmake=v.js('run-make.json');rm_log=v.raw('run-make.log')
    assert runmake=={'source':C,'log':sha(rm_log)} and b'test result: ok. 1 passed; 0 failed' in rm_log
    assert b'suite=run-make mode=run-make (aarch64-apple-darwin)' in rm_log
    for role in 'PC':
        phys=pair['products'][role];assert v.js('bootstrap-'+role+'-product.json')==phys and sha(v.raw('bootstrap-'+role+'.log'))==phys['build_log']
        assert phys['build_argv'][-6:]==['build','--stage','1','-j4','compiler/rustc','library']
        assert phys['library_tree']==pair['products']['P']['library_tree'] and phys['stage0_cargo']==pair['products']['P']['stage0_cargo'] and phys['stage0_rustc']==pair['products']['P']['stage0_rustc']
        for phase in ('producer','consumer','run'):
            key=f'proc-macro/{role}/{phase}/';exec_proof=v.js(key+'command.json')
            assert exec_proof['exit']==0 and (exec_proof['argv']==['./reader'] if phase=='run' else exec_proof['argv'][:2]==['rustc','+ohm'])
            assert {l:sha(v.gz(key+l+'.gz')) for l in ('stdout','stderr')}==exec_proof['streams']
            if phase=='run':assert v.gz(key+'stdout.gz')==b'3\n'
    obs=v.js('observer.json');assert obs['exit']==29 and obs['ld']=='2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443'
    driver,=pair['differ'];assert driver.startswith('lib/librustc_driver')
    result={}
    for r,source in [('P',P),('C',C)]:
        cfg=root[r];prior=pair['products'][r];images=cfg['members'];assert prior['source']==source and images==dict(prior['runtime'],**{'bin/cargo':pin['binary']['sha256']})
        assert R in cfg['sdk']['cargo_version'] and cfg['sdk']['cargo']==pin['binary'] and cfg['sdk']['driver']['sha256']==images[driver]
        assert v.js('293-runtime/'+r+'/dyld/verified.json')['loaded'][driver]['sha256']==images[driver]
        result[r]={'source':source,'driver':images[driver],'members':len(images)}
    assert root['P']['sdk']['std']==root['C']['sdk']['std'] and root['P']['sdk']['rustc']==root['C']['sdk']['rustc'] and {k for k in root['P']['members'] if root['P']['members'][k]!=root['C']['members'][k]}=={driver}
    return {'rust':result,'cargo_source':R,'cargo_sha256':pin['binary']['sha256'],'cargo_ctime_ns':root['C']['cargo_ctime_ns'],'frontend':root['C']['sdk']['rustc']['sha256'],'std':root['C']['sdk']['std'],'distribution_cargo':signed['cargo']['sha256'],'child_run_make_log':runmake['log'],'target':'aarch64-apple-darwin','observer_ld_sha256':obs['ld'],'calibration':calibration,'time_instruction_scope':calibration['retired']}

def main(archive,dest):
    with ZipFile(archive) as z:
        v=Dataset(z);subj=sources(v);providers=v.providers();reg=v.js('provider-matrix/registration.json');assert reg['cargo']==R and reg['rust']=={'P':P,'C':C} and 'crc32w' in reg['barrier'];terminal=v.js('provider-matrix/terminal.json');assert terminal['commands']==392
        names=sorted(n.split('/')[-2] for n in v.names if n.startswith('provider-matrix/') and n.count('/')==2 and n.endswith('/terminal.json'));assert len(names)==20
        cases={};issues={};work={};cargos=set();genuine_hit=0
        for name in names:
            role,place,policy,mode=name.split('-');rows=v.case(name);cases[name]=rows
            assert v.js('provider-matrix/'+name+'/inputs.json')['driver']['sha256']==subj['rust'][role[0]]['driver']
            stages=STAMP if 'stamp' in role else STEPS;assert set(rows)==set(stages);off=[];wrong=[];prev=None;work[name]={}
            for s in stages:
                row=rows[s];w=row['warm'];cargos.update((w['cargo_cdhash'],row['empty']['cargo_cdhash']))
                if not row['same_verdict'] or row['same_checked_image'] is False:
                    critical=mode=='default' or policy=='declared' or s not in NO
                    (wrong if critical else off).append(s)
                hit=bool(prev and w['status']==0 and w['driver_processes'] and w['ld']==0 and w['raw'] in w['receipt_products'] and set(w['seals'])&set(prev['seals']));genuine_hit+=hit
                work[name][s]={'verdict':w['answer'] if not w['status'] else w['status'],'full':w['full'],'link_only':w['link_only'],'final_ld':w['final'],'driver':w['driver_processes'],'reports':w['dependency_info'],'existing_seal_hit':hit,'checked_equals_empty':row['same_checked_image'],'raw_equals_empty':row['same_raw'],'raw':w['raw']};prev=w
            assert sorted(wrong)==sorted(terminal['wrong_or_image_mismatch'][name]);issues[name]={'default_declared_or_rust':wrong,'off_unwatched':off}
        assert (not any(x['default_declared_or_rust'] for x in issues.values()))==terminal['passed'] and len(cargos)==1
        subj['kernel_cargo_cdhash']=next(iter(cargos));output={'run':41082182665,'sha256':digestfile(archive),'sources':subj,'providers':providers,'physical_objects':v.image_proofs.objs,'recipe_count':len(v.image_proofs.recipes),'stock_Xcode':sorted(v.lds),'cases':20,'commands':392,'native_images':len(v.images),'eligible':terminal['passed'],'hits':genuine_hit,'issues':issues,'work':work}
        dest.mkdir(parents=True,exist_ok=True);write(dest/'provider.json',pretty(output));write(dest/'provider-observations.json.gz',gzip.compress(compact(cases).encode(),mtime=0));print(json.dumps({k:output[k] for k in ('commands','native_images','eligible','hits','stock_Xcode','sha256')},sort_keys=True))
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('archive',type=Path);ap.add_argument('dest',type=Path);args=ap.parse_args();main(args.archive,args.dest)
