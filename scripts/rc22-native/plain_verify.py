"""Reopen the original no-tracer raw files and check behavior, native inputs, complete output and migration."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tomllib

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *
import fixture
import observe

def verify(root,reference):
    root=Path(root);index=read(root/'complete.json');source=read(root/'source-release.json')
    require(read(root/'original.json')==reference and source['qa']['GITHUB_SHA']==reference['head'] and source['qa']['GITHUB_RUN_ID']==str(reference['run']) and source['kit_sha256']==reference['kit'],'unbound source kit')
    require(source['rust']['commit']==RUST and source['rust']['tree']==RTREE and all((source['cargos'][s]['commit'],source['cargos'][s]['tree'])==r for s,r in ROLES.items()),'foreign compiler or Cargo')
    target=source['rust']['host'];all_kinds=['zmij'] if target==GNU else ['zmij','objc2']
    require(target in (GNU,APPLE) and index['host']==target and index['native_launch_count'] is None,'collector scope')
    linker=read(root/'host-linker-before.json');published,=source['native_linkers']
    require(linker==read(root/'host-linker-after.json') and linker['kind']==published['kind'] and linker['image']['sha256']==published['sha256'],'different host native linker')
    if target==GNU:require(published['sha256']==WILD and linker['version']==published['version'] and linker['image']['path'].endswith('/sdk/'+published['path']),'uncertified GNU Wild')
    else:require(linker['image']['path']==published['path'] and linker['version']==published['toolchain'],'uncertified Apple ld')

    sys.path.insert(0,str(seed('marker-reader')/'scripts/ohm-musl-ast-pair/v2'));import evidence
    cas={}
    for p in (root/'cas').glob('*.gz'):
        data=gzip.decompress(p.read_bytes());require(hashlib.sha256(data).hexdigest()==p.stem,'raw CAS digest')
        cas[p.stem]=data
    cases={};bodies=set();seen=0;roster={};apple_ids={}
    for k in all_kinds:
        for history in ('baseline','fixed','migration'):
            d=root/(k+'-'+history);subject=read(d/'source.json');terminal=read(d/'complete.json')
            cover=[fixture.STEPS[0],('repeat-lower','low',17),*fixture.STEPS[1:]]
            if history=='migration':cover=[('old-lower','low',17),('old-higher','high29',29),('upgrade','high29',29),*fixture.STEPS[2:]]
            require(terminal['visits']==3*len(cover) and set(terminal['phases'])=={x[0] for x in cover} and subject['ruff_revision']==RUFF and subject['registry'][k]['archive']==LOCKED[k][1],'wrong source or phase set')
            require(subject['sdk']['driver']['sha256']==source['rust']['driver_sha256'] and subject['sdk']['rustc']['sha256']==source['rust']['rustc_sha256'],'wrong physical compiler')
            provider=read(d/'providers.json')
            for v in (17,29,41):
                obj=(d/(str(v)+'-member.o')).read_bytes();arc=(d/(str(v)+'-role-'+str(v)+'.a')).read_bytes();p=provider['bodies'][str(v)]
                require(hashlib.sha256(arc).hexdigest()==p['archive_sha256'] and hashlib.sha256(obj).hexdigest()==p['object_sha256'] and bytes(f'OHM_RC22_SELECTED_NATIVE_IMAGE_{v}','ascii') in obj,'native input differs')
                require(fixture.provider_archive(arc,'member.o',obj,target==APPLE)==p['members'],'native archive roster')
            cases[d.name]={};previous=None
            for phase,state,value in cover:
                out=d/phase;comp=read(out/'comparison.json')
                require(comp==terminal['phases'][phase] and comp['expected']==value,'phase declaration')
                role='fourfix' if history=='fixed' or (history=='migration' and not phase.startswith('old-')) else 'pinned'
                require(comp['reader']==role,'reader identity');visits={}
                for lane in ('warm','force','empty'):
                    a=out/lane;row=read(a/'observed.json');raw=gzip.decompress((a/'stdout.gz').read_bytes());err=gzip.decompress((a/'stderr.gz').read_bytes());typed=[json.loads(x) for x in raw.splitlines() if x.strip()]
                    require(row['command']==index['literal_command']==['cargo','+ohm','build','--locked','--offline','-j4','--message-format=json'] and row['mode']=='ordinary-no-process-instrumentation' and row['code'] in (0,101) and typed[-1]=={'reason':'build-finished','success':row['code']==0},'not ordinary Cargo')
                    require(all(row[s]==comp['visits'][lane][s] for s in ('code','value','image','app_fresh','diagnostics')),'collector/summary mismatch')
                    codes=[x['message']['code']['code'] for x in typed if x['reason']=='compiler-message' and x['message'].get('code')]
                    require(codes==row['diagnostics'],'diagnostics altered')
                    directives=cas[row['watch_stdout']].decode().splitlines();require(len(directives)==3 and directives[0].startswith('cargo:rustc-link-search=native=') and directives[0].endswith('/native/early') and directives[1]==directives[0][:-5]+'late' and directives[2]=='cargo:rerun-if-changed=build.rs','build script declares a provider mutation')
                    scripts=[x for x in typed if x['reason']=='build-script-executed' and x['package_id'].endswith('#'+fixture.APP+'@0.1.0')]
                    require(len(scripts)==1 and not scripts[0]['linked_libs'] and scripts[0]['linked_paths']==[x.split('=',1)[1] for x in directives[:2]],'different Cargo link graph')
                    primary=row['units'][k]
                    reg={x['target']['name']:x for x in typed if x['reason']=='compiler-artifact' and x['package_id'].startswith('registry+') and x['target']['kind']==['lib']}
                    require(set(reg)==set(row['units'])==({k} if k=='zmij' else {k,'objc2_encode'}),'unexpected dependency graph')
                    for n,unit in row['units'].items():
                        real=reg[n];suffix=Path(unit['rlib']['path'])
                        require(real['fresh']==unit['fresh'] and real['package_id']==unit['package'] and unit['rlib']['path'] in real['filenames'] and str(real['target']['src_path'])==unit['source']['path'],'wrong producer file or freshness')
                        src=unit['source'];decl=subject['registry'][n.replace('_','-')]
                        require(src['sha256']==decl['sources']['src/lib.rs'] and real['package_id'].endswith('#'+n.replace('_','-')+'@'+decl['version']),'producer does not match authentic crate')
                        flags=[] if n!=k else [evidence.V1 if k=='zmij' else evidence.V2]
                        mark=flags[0] if flags and (role=='fourfix' or k=='objc2') else None
                        require(unit['raw_path']==str(suffix.with_name(suffix.name[3:-5]+'.d')) and unit['record_path']==str(suffix.parent.parent/'fingerprint'/('dep-lib-'+n)),'different unit record')
                        require(evidence.raw_rule(Path(unit['raw_path']),cas[unit['raw']])==unit['rules']==flags,'wrong raw rules')
                        binary=evidence.encoded(cas[unit['translated']])
                        require(binary['LNK1']==unit['LNK1']==mark and binary['markers']==unit['markers']==([mark] if mark else []),'wrong authenticated translation')
                    leaf=[x for x in typed if x['reason']=='compiler-artifact' and x['target']['name']==fixture.APP and x['target']['kind']==['bin']]
                    if row['code']==0:
                        v=row['value'];image=row['image'];program=cas[image];bodies.add(image)
                        require(len(leaf)==1 and leaf[0]['fresh']==row['app_fresh'] and leaf[0]['executable'],'different terminal Cargo leaf')
                        require(v in (17,29,41) and program[:4]==(b'\x7fELF' if target==GNU else bytes.fromhex('cffaedfe')) and all((f'OHM_RC22_SELECTED_NATIVE_IMAGE_{j}'.encode()+b'\0' in program)==(j==v) for j in (17,29,41)),'foreign complete program')
                        if target==APPLE:
                            import apple_plain
                            promotion=read(a/'promotion.json');pub,private=promotion['published'],promotion['private'];script_out=Path(scripts[0]['out_dir'])
                            require(promotion['typed_script_out']==str(script_out) and pub['path']==leaf[0]['executable'] and private['path']==row['apple_proof']['output'] and Path(private['path']).parent.parent.parent==script_out.parent.parent,'different active Cargo unit')
                            require(pub['sha256']==private['sha256']==image and pub['bytes']==private['bytes']==len(program) and promotion['same_inode']==((pub['dev'],pub['ino'])==(private['dev'],private['ino'])),'unverified Apple promotion')
                            require(read(a/'cgu-proof.json')==row['apple_proof'],'different native recipe witness')
                            apple_ids[image]=apple_plain.reopen(root,program,row['apple_proof'])
                        runtime=read(a/'runtime.json');require(runtime=={'code':0,'elf':image,'stdout':f'{v} OHM_RC22_SELECTED_NATIVE_IMAGE_{v}\n'},'native behavior differs')
                    else:require(not leaf and row['value'] is None and row['image'] is None,'failed build recorded as a program')
                    if lane!='warm' or role=='fourfix' or k=='objc2' or phase in ('lower','old-lower','repeat-lower','rust-error','rust-repair'):
                        if state=='source-invalid':require(row['code']==101 and 'E0308' in codes,'missing type error')
                        elif value is None:require(row['code']==101 and row['native_error'] and (fixture.LIB.encode() in raw+err or b'qa_rc22_value' in raw+err),'not a native failure')
                        else:require(row['code']==0 and row['value']==value,'wrong native value')
                    if lane!='warm' and row['code']==0:require(row['app_fresh'] is False,'force/empty skipped terminal unit')
                    visits[lane]=row;seen+=1
                def verdict(r):
                    return (r['code'],r['value'],apple_ids.get(r['image'],r['image']),tuple(r['diagnostics']))
                warm=visits['warm'];force=visits['force'];empty=visits['empty']
                require(verdict(force)==verdict(empty) and comp['warm_equals_empty']==(verdict(warm)==verdict(empty)),'wrong full-output comparison')
                if role=='fourfix' or k=='objc2':require(comp['warm_equals_empty'],'corrected path diverges')
                if role=='pinned' and k=='zmij' and phase in ('appearance','old-higher','same-stat','malformed'):
                    require(not comp['warm_equals_empty'] and warm['value']==17 and warm['app_fresh'] is True,'baseline failed to reproduce')
                if phase=='upgrade':
                    txn=read(out/'same-path.json');snap=json.loads(gzip.decompress((out/'pre-existing-tree.json.gz').read_bytes()));u=previous['units'][k]
                    require(len(snap)==txn['entries'] and txn['old']['path']==txn['new']['path'] and [txn[n]['sha256'] for n in ('old','new')]==[source['cargos'][n]['sha256'] for n in ('pinned','fourfix')],'wrong migration')
                    require(txn['previous_unit']==u and txn['old_image']==previous['image'] and snap[u['raw_path']][-1]==u['raw'] and snap[u['record_path']][-1]==u['translated'] and not warm['units'][k]['fresh'],'historical record not witnessed')
                info=comp['provider']
                for n in ('early','late'):
                    if state in ('high41','bad') and n=='early':
                        old,new=info[n]['before'],info[n]['after'];require(all(old[x]==new[x] for x in ('dev','ino','bytes','mtime_ns')) and old['sha256']!=new['sha256'],'not the same-stat native transition')
                cases[d.name][phase]=[role,warm['code'],warm['value'],empty['code'],empty['value'],comp['warm_equals_empty']]
                previous=warm
            roster[d.name]=len(cover)*3
    require(index['cases']==roster and index['visits']==seen and len(bodies)>=3,'command count')
    return {'qa':'untraced complete source-built release validation','visits':seen,'observed_exec_counts':None,'program_bodies':len(bodies),'raw_byte_blobs':len(cas),'platform':target,'source':reference,'cases':cases}
if __name__=='__main__':
    base=Path(sys.argv[1]);value=verify(base,read(sys.argv[2]));save(Path(sys.argv[3]),value);print({k:v for k,v in value.items() if k not in ('source','cases')})
