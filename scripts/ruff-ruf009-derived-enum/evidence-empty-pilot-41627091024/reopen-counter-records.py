"""Reread independent native counters, literal executed owners and full external data from the original ZIP."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import tempfile
import zipfile

PARSER = argparse.ArgumentParser()
PARSER.add_argument("original", type=Path)
PARSER.add_argument("expected_digest")
PARSER.add_argument("output", type=Path)
args = PARSER.parse_args()
sha=lambda raw: hashlib.sha256(raw).hexdigest()
with args.original.open("rb") as f:
    assert hashlib.file_digest(f, "sha256").hexdigest() == args.expected_digest
z=zipfile.ZipFile(args.original)
committed={n:(length,h) for n,length,h in json.loads((Path(__file__).resolve().parent/'original-member-commitments.json').read_bytes())}
members=set(z.namelist())
assert len(members)==len(z.infolist())
load=lambda member: json.loads(z.read(member))
worker=load("worker.json")
assert worker['order'] in ('PC','CP') and worker['phase']in('pilot','confirmation')
true_roles={}
for role in worker['order']:
    kit=load(role+"/kit.json")
    sdk=Path(kit['active'])
    assert sdk==Path(kit['sysroot'])
    driver,=[sdk/n for n,d in kit['config']['files'].items()if n.startswith('lib/librustc_driver') and d==kit['driver']]
    alias={str(sdk/'bin/rustc'),str(sdk.parent/'rustup/toolchains/ohm/bin/rustc')}
    counters={}
    for stage in ('buggy-cold','buggy-idle1','buggy-idle2','edited','fixed-idle1','fixed-idle2'):
        path=role+'/ordinary-'+stage
        hw=load(path+'/hardware.json')
        assert hw['status']==0 and hw['enabled']==hw['running']>0 and hw['instructions']>0 and hw['pid']>0
        cmd=load(path+'/command.json')
        assert cmd['exit']==0 and cmd['argv'][3:]==worker['source']['cargo_check']
        checked=load(path+'/check.json')
        assert checked['instructions']==hw['instructions'] and checked['method']=='pmu'
        counters[stage]=dict(**hw,record_sha256=sha(z.read(path+'/hardware.json')))
    stages={}
    for stage in ('kernel-buggy-return','kernel-edited','kernel-buggy-idle1','kernel-buggy-idle2','kernel-fixed-idle1','kernel-fixed-idle2','reverse','restore-fixed','invalid','repair'):
        path=role+'/'+stage
        if path+'/check.json' not in members:continue
        if load(path+'/check.json')['method']!='trace':continue
        src=path+'-observer/'
        owners={}
        for name in members:
            if not (m:=re.fullmatch(re.escape(src)+r'trace\.(\d+)\.gz',name)):continue
            text=gzip.decompress(z.read(name)).decode().splitlines()
            hits=[]
            for s in text:
                if not (s.startswith('execve("') and s.rstrip().endswith(') = 0')):continue
                binary,raw=s[8:].split('", [',1)
                if binary not in alias:continue
                argv,end=json.JSONDecoder().raw_decode('['+raw)
                if '--crate-name'not in argv or '--out-dir'not in argv:continue
                assert '--emit=dep-info,metadata'in argv
                if argv[argv.index('--crate-name')+1]=='ruff_linter' and argv[argv.index('--crate-type')+1] in ('lib','rlib'):
                    negotiated=set(argv)&{'-Zohm-checked-private-derives','-Zohm-checked-private-derives-v2'}
                    assert negotiated==({'-Zohm-checked-private-derives-v2'} if role=='C' else set())
                    assert any('checksum-hash-algorithm=blake3' in a for a in argv)

                mapped=[line for line in text if line.startswith('mmap(')and 'PROT_EXEC' in line and '<'+str(driver)+'>'in line and re.search(r' = 0x[0-9a-f]+$',line)]
                assert mapped
                hits.append((argv[argv.index('--crate-name')+1],argv[argv.index('--crate-type')+1],sha(json.dumps(argv,separators=(',',':')).encode())))
            if hits:
                hit,=hits
                owners[int(m[1])]=hit
        typed=load(src+'native-execs.json')['actual']
        assert set(owners)==set(map(int,typed)) and all(data[0]==typed[str(pid)]['crate'] for pid,data in owners.items())
        physical=sorted([v[0],v[1]]for v in owners.values())
        checked=load(path+'/check.json')
        assert physical==checked['physical']
        cmd=load(path+'/command.json')
        if stage=='invalid':
            assert cmd['exit']==101
            diag=[json.loads(line) for line in z.read(path+'/stdout').splitlines() if line]
            problems=[r['message'] for r in diag if r['reason']=='compiler-message' and r['message']['level']=='error']
            problem,=problems
            assert problem['code']['code']=='E0308' and any(s['is_primary'] and 'OHM_INVALID_CHECK_SENTINEL'in str(s)for s in problem['spans'])
        else:assert cmd['exit']==0
        stages[stage]={'actual':dict(sorted(owners.items())),'roster':physical,'nominal':checked['dirty'],'status':cmd['exit']}
    native={}
    for phase in ('native-buggy','native-edited','native-reverse','native-repair','native-empty-edit','native-fully-empty-fixed'):
        if role+'/'+phase+'/native.json'not in members:continue
        n=load(role+'/'+phase+'/native.json')
        compressed='members/'+n['sha256']+'.elf.zst'
        # Independently open and hash the archived compressed ELF once per command. The hosted
        # separate reader additionally decompresses it and compares all loadable/debug bytes.
        assert compressed not in members and committed[compressed][1]==n['compressed']
        distinct={}
        for name,probe in n['probes'].items():
            diag=json.loads(probe['stdout']);codes=[d['code']for d in diag]
            assert probe['stderr']==''and codes in ([],['RUF009']) and bool(probe['code'])==bool(diag)
            distinct[name]=[probe['code'],codes]
        assert len(distinct)==4
        native[phase]={'elf':n['sha256'],'bytes':n['bytes'],'archive_member':n['compressed'],'verdicts':distinct}
    true_roles[role]={'driver':kit['driver'],'cargo':kit['cargo'],'physical_rustc':kit['rustc'],'counters':counters,'traced':stages,'native':native}
p,c=[true_roles[k]for k in 'PC'];primary={k:true_roles[k]['counters']['edited']['instructions']for k in 'PC'}
out={'run':worker['run'],'boot':worker['boot'],'head':worker['sha'],'scope':worker['phase'],'order':worker['order'],'recipe':worker['recipe'],'block':worker['block'],'zip_sha256':args.expected_digest,'zip_bytes':args.original.stat().st_size,'original_roles':true_roles,'edited_instructions':primary,'edited_reduction_fraction':1-primary['C']/primary['P']}
out['native_compressed_members_verified_against']='original ZIP member manifest; the original reader separately reopened the four physical archived ELFs'
args.output.write_text(json.dumps(out,sort_keys=True,indent=1)+'\n')
print(primary,[len(true_roles[k]['traced']['kernel-edited']['actual'])for k in 'PC'],out['edited_reduction_fraction'])
