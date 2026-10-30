#!/usr/bin/env python3
"""Check the normalized comparison, optionally rebuilding each observation from the seven original ZIPs."""
import argparse
import collections
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parent
def digest(b):
    return hashlib.sha256(b).hexdigest()
def load(n):
    return json.loads(gzip.decompress((ROOT/n).read_bytes()))
def read_raw(record,folder,rid,role,kind):
    arc=record['archive'];zpath=folder/rid/(arc['name']+'.zip')
    with zpath.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==arc['sha256']
    assert zpath.stat().st_size==arc['size']
    mod=ROOT/('raw_immediate.py' if kind=='immediate-compilers' else 'raw_attribution.py')
    spec=importlib.util.spec_from_file_location('selector_'+role,mod);impl=importlib.util.module_from_spec(spec);spec.loader.exec_module(impl)
    with zipfile.ZipFile(zpath) as z:
        files={obj.filename:digest(z.read(obj)) for obj in z.infolist() if not obj.is_dir()}
        assert len(files)==arc['members']
        assert digest(''.join(hash_+'  '+name+'\n' for name,hash_ in sorted(files.items())).encode())==arc['inner_manifest_sha256']
        derived=impl.inspect(z,role)
        for key,stream in record['streams'].items():
            data=z.read(key+'/result.json');assert digest(data)==stream['result_sha256'];r=json.loads(data)
            assert (r['kernel_tar'],r['stdout'],r['stderr'])==(stream['kernel_tar_sha256'],stream['stdout'],stream['stderr'])
            assert (r['rustc'],r['cross_linker_pids'])==(stream['compiled'],stream['cross_linker_pids'])
            assert stream['typed']==[[t[0],t[1],t[2]] for t in r['typed']]
            assert stream['rlibs']=={k:v['sha256'] for k,v in r['libs'].items()}
    assert derived==record['independent'],role
def verdicts(case):
    return {phase:(p['code'],p['value'],p['embedded_B']) for phase,p in case['phases'].items()}
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,help='directory containing RUN-ID/ARTIFACT-NAME.zip')
    args=parser.parse_args()
    for line in (ROOT/'SHA256SUMS').read_text().splitlines():
        h,n=line.split('  ',1);assert '/' not in n and digest((ROOT/n).read_bytes())==h,n
    d=load('commands.json.gz');allroles={};visits=0;raw=0
    for rid,run in d['runs'].items():
        assert run['terminal']['conclusion']=='success' and run['terminal']['head_sha']==run['source']
        name,aggregate=run['original_aggregate'];assert digest(gzip.decompress((ROOT/(name+'.gz')).read_bytes()))==aggregate
        for role,entry in run['roles'].items():
            act=entry['independent'];assert act['role']==role and act['terminal']
            assert digest((json.dumps(act,sort_keys=True,indent=2)+'\n').encode())==entry['independent_sha256']
            assert entry['source_manifest'] in d['sdk_table']
            cases={(c['kind'],c['mutation']):c for c in act['cases']};allroles[role]=cases
            assert len(entry['streams'])==len(cases)*9==act['visits']
            for (kind,mut),c in cases.items():
                p=c['phases'];want=29 if mut in ['normal-replacement','replace-same-mtime','higher-priority'] else None
                assert c['expected']==want and c['complete'] and c['phases']['05-forced-rebundle']['value']==c['phases']['06-independent-empty']['value']==want
                assert p['00-empty-original']['value']==p['01-settled-original']['value']==p['08-clean-repair']['value']==17
                for phase,out in p.items():
                    bound=entry['streams'][f'{kind}/{mut}/{phase}'];assert len(bound['cross_linker_pids'])==out['linkers']
                    assert [kind+':'+str(crate) for _,kind,crate in bound['compiled']]==out['crates']
                    assert all(re.fullmatch('[0-9a-f]{64}',bound[n]) for n in ('result_sha256','kernel_tar_sha256','stdout','stderr'))
            if args.raw:
                read_raw(entry,args.raw,rid,role,run['scope']);raw+=1
            print(f'{role:10s} {len(cases):2d} histories  {act["visits"]:3d} commands  {len(act["divergences_from_empty"]):2d} divergent ordinary or repair verdicts')
            visits+=act['visits']
    for a,b in [('P','C'),('upstream','signed-off'),('strict-P','strict-C')]:
        get=lambda role:{k:verdicts(c) for k,c in allroles[role].items()}
        assert get(a)==get(b),(a,b)
    compare=load('comparison.json.gz');assert len(compare['both_diverge'])==12 and not compare['new_on_candidate'] and not compare['only_on_parent']
    for role in allroles:
        b='bundled' if role in ('P','C') else 'bundled-unwatched'
        for m in ['higher-priority','replace-same-mtime','malformed','removed','malformed-higher']:
            p=allroles[role][b,m]['phases']
            assert [p[n]['value'] for n in ('02-ordinary','03-ordinary-repeat','04-forced-root')]==[17,17,17]
            assert p['02-ordinary']['embedded_B']==['17']
            assert p['07-repair']['value']==(29 if m in ('higher-priority','replace-same-mtime') else 17)
    for role in ['upstream','signed-off']:
        c=allroles[role]
        for key,val in {('bundled-both-directories','higher-priority'):29,('bundled-both-directories','normal-replacement'):29,('bundled-both-directories','replace-same-mtime'):17,('bundled-selected-file','higher-priority'):17,('bundled-selected-file','normal-replacement'):29,('bundled-selected-file','replace-same-mtime'):17,('bundled-all-files','higher-priority'):29}.items():
            assert c[key]['phases']['02-ordinary']['value']==val
        assert 'full:qa_plain' in c['bundled-all-files','higher-priority']['phases']['01-settled-original']['crates']
    assert visits==630 and len(allroles)==7
    print(f'{visits} native Cargo commands. All 7 roles share the five unwatched bundled misses. Full ZIPs reopened: {raw}.')
if __name__=='__main__':main()
