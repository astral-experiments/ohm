"""Independently reopen each recorded producer, native invocation, diagnostic and successful full executable."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *
import fixture
from fixture import APP,LIB

def verify(root):
    root=Path(root);report=read(root/'complete.json');sdk=read(root/'release.json')
    require(report['host']==sdk['rust']['host'] and report['kit']==sdk['kit_sha256'] and sdk['rust']['commit']==RUST and sdk['rust']['tree']==RTREE,'SDK binding')
    target=report['host'];kinds=['zmij'] if target==GNU else ['zmij','objc2'];require(target in (GNU,APPLE),'unknown platform')
    require(set(report['cases'])=={k+'-'+h for h in ('baseline','fixed','migration') for k in kinds},'incomplete case family')
    sys.path.insert(0,str(seed('marker-reader')/'scripts/ohm-musl-ast-pair/v2'))
    import evidence
    n=0;observed={};whole=set()
    def cas(word):
        data=gzip.decompress((root/'cas'/(word+'.gz')).read_bytes());require(hashlib.sha256(data).hexdigest()==word,'CAS body');return data
    def digest(path,data):
        require(hashlib.sha256(data).hexdigest()==path,'bad raw bytes')
    for k in kinds:
        for h in ('baseline','fixed','migration'):
            name=k+'-'+h;case=root/name;terminal=read(case/'complete.json');require(terminal['history']==h and terminal['producer']==k,name)
            source=read(case/'source.json');require(source['ruff']==RUFF and source['registry'][k]['archive']==LOCKED[k][1],'not exact locked registry')
            proof=read(case/'providers.json')
            for num in (17,29,41):
                obj=(case/(str(num)+'-member.o')).read_bytes();archive=(case/(str(num)+'-role-'+str(num)+'.a')).read_bytes()
                require(archive.startswith(b'!<arch>\n') and archive.count(obj)==1 and f'OHM_RC22_SELECTED_NATIVE_IMAGE_{num}'.encode() in obj,'provider body')
                digest(proof['bodies'][str(num)]['object_sha256'],obj);digest(proof['bodies'][str(num)]['archive_sha256'],archive)
            phases=dict((label,(state,v)) for label,state,v in fixture.STEPS)
            if h=='migration':
                phases={'old-lower':('low',17),'old-higher':('high29',29),'upgrade':('high29',29),**dict(list(phases.items())[2:])}
            else:phases['repeat-lower']=('low',17)
            require(set(phases)==set(terminal['phases']),'missing transitions')
            selected={}
            for phase,(state,val) in phases.items():
                folder=case/phase;comp=read(folder/'comparison.json')
                require(terminal['phases'][phase]==comp and comp['state']==state and comp['expected']==val,'inconsistent phase')
                role=comp['reader'];require(role==('fourfix' if h=='fixed' or h=='migration' and not phase.startswith('old-') else 'pinned'),'foreign reader')
                if phase=='upgrade':
                    migration=read(folder/'same-path.json');ward=json.loads(gzip.decompress((folder/'unmodified-state.json.gz').read_bytes()))
                    require(len(ward)==migration['entries'] and migration['old']['path']==migration['new']['path'] and migration['old']['sha256']==sdk['cargos']['pinned']['sha256'] and migration['new']['sha256']==sdk['cargos']['fourfix']['sha256'],'source switch identity')
                    for record in ('old_raw','old_translated'):
                        held=migration[record];require(ward[held['path']][-1]==held['sha256']==held['cas'],'original active records not preserved')
                if phase in ('same-stat','malformed','repair'):
                    before,after=(comp['provider']['early'][x] for x in ('before','after'))
                    require(all(before[t]==after[t] for t in ('dev','ino','bytes','mtime_ns')) and before['sha256']!=after['sha256'],'same-stat negative')
                data={}
                for lane in ('warm','force','empty'):
                    d=folder/lane;j=read(d/'observed.json');es=read(d/'exec.json')
                    typed=[json.loads(x) for x in gzip.decompress((d/'stdout.gz').read_bytes()).splitlines()]
                    stderr=gzip.decompress((d/'stderr.gz').read_bytes());require(typed[-1]=={'reason':'build-finished','success':j['code']==0},'Cargo status')
                    codes=[x['message']['code']['code'] for x in typed if x['reason']=='compiler-message' and x['message'].get('code')]
                    require(codes==j['diagnostic_codes'],'Rust diagnostic substitution')
                    want=evidence.V1 if k=='zmij' else evidence.V2;enc=None if k=='zmij' and role=='pinned' else want
                    meta=j['registry'][k];raw=meta['raw'];record=meta['record']
                    require(raw['cas']==raw['sha256'] and evidence.raw_rule(Path(raw['path']),cas(raw['cas']))==[want],'wrong raw producer')
                    require(record['cas']==record['sha256'],'translated record hash')
                    q=evidence.encoded(cas(record['cas']));require((q['LNK1'],q['markers'])==(enc,[enc] if enc else []),'incorrect authenticated Cargo decision')
                    require(meta['source']['sha256']==source['registry'][k]['sources']['src/lib.rs'] and meta['package'].endswith('#'+k+'@'+LOCKED[k][0]),'substituted producer')
                    for other,tab in j['registry'].items():
                        if other!=k:require(evidence.raw_rule(Path(tab['raw']['path']),cas(tab['raw']['cas']))==[],'competing producer marker')
                    require(j['raw_mark']==want and j['translated_mark']==enc and j['role']==role,'collector declaration differs')
                    final=j['final']
                    if final:
                        matches=[r for r in es if r['argv']==final['argv'] and r['pid']==final['pid']]
                        require(len(matches)==1 and final['image_sha256']==sdk['native_linkers'][0]['sha256'],'different physical linker')
                        if target==GNU:require(matches[0]['image']['sha256']==WILD,'not stock Wild')
                        else:require(Path(matches[0]['path']).name in ('ld','ld-classic','ld-prime','ld64') and matches[0].get('cdhash') is not None,'not Xcode ld')
                        require(any(LIB in a for a in final['argv']) and '-o' in final['argv'],'link did not concern provider')
                    if j['image']:
                        body=cas(j['image']);whole.add(j['image']);v=j['value'];answer=read(d/'runtime.json')
                        require(j['code']==0 and v in (17,29,41) and answer=={'exit':0,'sha256':j['image'],'stdout':f'{v} OHM_RC22_SELECTED_NATIVE_IMAGE_{v}\n'},'invalid native runtime')
                        require(body[:4]==(b'\x7fELF' if target==GNU else bytes.fromhex('cffaedfe')) and all((f'OHM_RC22_SELECTED_NATIVE_IMAGE_{x}'.encode()+b'\0' in body)==(v==x) for x in (17,29,41)),'foreign complete native product')
                    else:require(j['code']==101 and j['value'] is None,'failure with product')
                    data[lane]=j;n+=1
                forced,empty=data['force'],data['empty'];warm=data['warm']
                def equivalent(a,b):
                    if a['code'] or b['code']:return a['code']==b['code'] and a['value']==b['value']==None
                    if target==GNU:return a['image']==b['image'] and a['value']==b['value']
                    pa,pb=a['xcode_cgu'],b['xcode_cgu']
                    return a['value']==b['value'] and pa['raw']==a['image'] and pb['raw']==b['image'] and all(pa[x]==pb[x] for x in ('same_path_image','output','modules'))
                require(equivalent(forced,empty) and equivalent(warm,empty)==comp['warm_equals_empty'],'incorrect reference comparison')
                for row in (forced,empty):
                    if state=='source-invalid':require(row['code']==101 and 'E0308' in row['diagnostic_codes'] and not row['final'],'invalid Rust control')
                    elif val is None:require(row['code']==101 and row['native_error'] and row['final'],'missing native error')
                    else:require(row['code']==0 and row['value']==val and row['final'],'wrong provider reference')
                if role=='fourfix' or k=='objc2':require(equivalent(warm,empty),'corrected/versioned warm failure')
                if role=='pinned' and k=='zmij' and phase in ('appearance','old-higher','same-stat','malformed'):
                    require(not equivalent(warm,empty) and warm['value']==17 and not warm['final'],'missing historical red')
                selected[phase]=[role,warm['code'],warm['value'],int(bool(warm['final'])),empty['code'],empty['value']]
            observed[name]=selected
    require(n==report['ordinary_commands'] and len(whole)>=3,'incomplete real cohort')
    return {'schema':1,'commands':n,'complete_executables':len(whole),'rust':RUST,'roles':ROLES,'kit_sha256':report['kit'],'cases':observed}
if __name__=='__main__':
    d=Path(sys.argv[1]).resolve();proof=verify(d);save(d/'verified.json',proof);print(json.dumps({k:v for k,v in proof.items() if k!='cases'},sort_keys=True))
