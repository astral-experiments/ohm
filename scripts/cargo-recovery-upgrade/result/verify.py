"""Verify source-built Cargo, signed rustc, each native process and its actual Ruff diagnostics."""
import ast
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from archive import read,sha
from upgrade_evidence import verify as reopen_upgrade
from matched_evidence import reopen as reopen_matched
PARENT='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
FIX='58f94004f2cf0790be76db99a49f725a3611e5a6'
SIGN='c79998a5cd143c445a4b2528f20953b176a65c5d'
SOURCE='crates/ty_project/src/lib.rs'
BAD={'invalid','bad-again','different-bad','unchanged-different-bad','warning-bad'}
OLD_ERROR={'repair-json','idle-human','idle-json','cache-reads','warning-repair','warning-settled'}
PHASES=('train-original','edit','repeat','invalid','repair-json','idle-human','idle-json','cache-reads','bad-again','different-bad',
        'unchanged-different-bad','different-repair','final-repair','empty-json','empty-human','warning-edit','warning-repeat','warning-human',
        'warning-bad','warning-repair','warning-settled')
FRONT=['check','-p','ty_project','--tests','--locked','--offline','-j8']
def reopen(data):
    j=lambda name:json.loads(data[name])
    spec=j('fix-terminal.json')
    assert spec['product']['head']==FIX and spec['product']['parent']==PARENT
    subject=j('subjects.json')
    assert subject['source']=='93526150df078af7dd8fc4226cdcc469539d2001' and subject['history']=='32c5cd5daba51d9c3da691c5b43afa6a7a4bb731'
    assert subject['qa']==spec['source_workflow']=='b59a9023a608e1191e61c697dbe3e6e5c008aa8a'
    assert subject['kit']['bytes']==359657153 and subject['kit']['archive_sha256']=='6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4'
    assert subject['kit']['provenance']['sources']['rust']['revision']==SIGN and subject['kit']['provenance']['sources']['cargo']['revision']==PARENT
    assert subject['tools']['cargo']['sha256']=='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
    assert subject['tools']['rustc']['sha256']=='f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9'
    builds={}
    summary={}
    for role,arm,commit in [('parent','P',PARENT),('fixed','C',FIX)]:
        fixed=role=='fixed'
        build=j('buildkit/'+arm+'/built.json');builds[arm]=build
        assert build['source']['commit']==commit and build['source']['files']==3108
        assert 'commit-hash: '+commit in build['version'] and 'commit-hash: '+SIGN in build['rustc_version']
        assert build['cargo']['sha256']==build['compiled']['sha256']
        cmd=j('buildkit/'+arm+'/compile/result.json')
        assert cmd['exit']==0 and cmd['command'][:4]==['cargo','+ohm','-Zohm-defaults=no','build'] and 'ohm-defaults,all-static' in cmd['command']
        js=[json.loads(l) for l in data['buildkit/'+arm+'/compile/stdout.gz'].splitlines()]
        leaf,=[o for o in js if o['reason']=='compiler-artifact' and o['target']['name']=='cargo' and o['target']['kind']==['bin']]
        assert not leaf['fresh'] and leaf['executable']==build['compiled']['path'] and {'ohm-defaults','all-static'}<=set(leaf['features'])
        assert js[-1]=={'reason':'build-finished','success':True} and build['compiler']['ino']==subject['tools']['rustc']['dev_ino']
        assert build['compiler']['sha256']==subject['tools']['rustc']['sha256'] and build['driver']['sha256']==subject['versions']['physical_driver']['sha256']
        hist=[]
        for phase in PHASES:
            p=role+'/'+phase+'/'
            rec=j(p+'receipt.json');before=rec['before'];after=rec['after']
            assert rec['role']==role and rec['label']==phase and before['source']==after['source']
            assert ('RUSTC_WRAPPER' not in j(role+'/environment.json') and 'CI' not in j(role+'/environment.json'))
            stdout,stderr=data[p+'stdout.gz'],data[p+'stderr.gz'];assert sha(stdout)==rec['stdout'] and sha(stderr)==rec['stderr']
            src=before['source'][SOURCE]
            assert [v for v in before['source'] if v!=SOURCE]==[subject['changed']]
            assert before['source'][subject['changed']]['sha']==subject['original_blob' if phase=='train-original' else 'historical_parent_blob']
            own_bad=phase in BAD;stale=not fixed and phase in OLD_ERROR
            if not phase.startswith('warning'):
                expected_src=('0aa431793a70' if phase in ('invalid','bad-again') else 'a2b65c1d295e' if phase in ('different-bad','unchanged-different-bad') else
                              'c4a6e67ee65a' if phase=='different-repair' else 'd560695aa852')
                assert src['sha'].startswith(expected_src)
            assert bool(src['bad'])==own_bad
            assert rec['exit']==(101 if own_bad else 0)
            owners=[]
            regular=rec['observer']=='physical'
            if regular:
                origins=[]
                for n,l in enumerate(data[p+'trace/exec.tsv'].decode().splitlines(),1):
                    seq,pid,dev,ino,hit,image=l.split('\t');assert n==int(seq)
                    argv=data[p+f'trace/args-{n:04d}'];assert argv[-1:]==b'\0';args=[a.decode() for a in argv[:-1].split(b'\0')]
                    mode=[int(dev),int(ino)]
                    flags=FRONT+(['--message-format=json'] if rec['style']=='json' else [])
                    if mode==build['cargo']['ino']:
                        assert args[1:]==flags and image==build['cargo']['actual'];origins.append(int(pid))
                    elif mode==build['compiler']['ino']:
                        assert image==build['compiler']['actual'] and '--emit=dep-info,metadata' in args
                        name=args[args.index('--crate-name')+1];assert name in ('ron','ty_project') and int(hit)==(name=='ron')
                        assert (name=='ty_project')==any('incremental=' in a for a in args)
                        owners.append(name)
                    else:assert Path(image).name=='rustup' and args[1:]==['+ohm',*flags]
                assert len(origins)==1 and [v[0] for v in rec['physical_cargo']]==origins and [v[1] for v in rec['physical_rustcs']]==owners
                rebuild=own_bad or phase in ('edit','different-repair','final-repair','warning-edit') or fixed and phase in ('repair-json','warning-repair')
                assert owners==(['ron','ty_project'] if rebuild else ['ron']),(role,phase,owners)
            caches={}
            for when in ('before','after'):
                for path,info in rec[when]['cache'].items():
                    body=data['diag-content/'+info['sha']+'.gz'];assert sha(body)==info['sha'] and len(body)==info['size']
                    if Path(path).name in ('test-lib-ty_project','output-test-lib-ty_project'):caches[when,Path(path).name]=(path,body)
            after_short=caches['after','test-lib-ty_project'][1]
            if own_bad:assert after_short==b''
            else:assert re.fullmatch(rb'[0-9a-f]{16}',after_short)
            if phase in ('repair-json','warning-repair'):
                assert caches['before','test-lib-ty_project'][1]==b''
                assert (b'PreviousBuildIncomplete' in stderr)==fixed
                assert (b'early cutoff: skipping compilation of ty_project' in stderr)!=fixed
            if phase in ('repeat','idle-json','warning-repeat','warning-settled'):
                assert b'early cutoff: skipping compilation of ty_project' in stderr
            cache=caches.get(('after','output-test-lib-ty_project'))
            has_warning=False
            if rec['style']=='json':
                msgs=[json.loads(line) for line in stdout.splitlines()]
                assert msgs[-1]=={'reason':'build-finished','success':not own_bad}
                arts=[k for k in msgs if k['reason']=='compiler-artifact'];assert len(arts)==(302 if own_bad else 303)
                shown=[k['message'] for k in msgs if k['reason']=='compiler-message']
                errors=[a for a in shown if a['level']=='error']
                assert len(errors)==int(own_bad or stale)
                if errors:
                    m=errors[0];assert m['code']['code']=='E0308'
                    site,=[v for v in m['spans'] if v['is_primary']]
                    assert site['file_name']==SOURCE and ('OHM_RON_SECOND_BAD_TYPE' if 'different-bad' in phase else 'OHM_RON_CHECK_BAD_TYPE') in site['text'][0]['text']
                has_warning=any((a['code'] or {}).get('code')=='deprecated' and 'OHM_QA_PRESERVED_WARNING' in a['message'] for a in shown)
                if shown:
                    assert cache
                    native=[json.loads(l) for l in cache[1].splitlines()]
                    keep=[a for a in native if not a['message'].startswith(('aborting due to ','1 warning emitted','2 warnings emitted'))]
                    for a in keep:
                        if a['rendered'] is not None:a['rendered']=re.sub(r'\x1b\[[\d;]*m','',a['rendered'])
                    assert keep==shown,(role,phase,[(a['level'],a['message']) for a in keep],[(a['level'],a['message']) for a in shown])
                else:assert not cache
                assert sum(a['target']['name']=='ty_project' for a in arts)==(0 if own_bad else 1)
            else:
                assert stdout==b'' and b'Finished' in stderr and (b'error[E0308]' in stderr)==(own_bad or stale)
                has_warning=b'OHM_QA_PRESERVED_WARNING' in stderr
            if phase.startswith('warning') and (fixed or phase not in ('warning-repair','warning-settled')) and not own_bad:assert has_warning
            if not phase.startswith('warning'):assert not has_warning
            if phase=='cache-reads' and not fixed:
                reads=data[p+'open-and-read.tsv.gz'].decode().splitlines()
                path,body=cache
                match,=[re.search(r'^(\d+)<cargo> .* read\(\d+<'+re.escape(path)+r'>, (".*"), 8192\) = 2866$',l) for l in reads if l.endswith('= 2866')]
                assert len(body)==2866 and ast.literal_eval('b'+match[2])==body
            hist.append([phase,rec['exit'],owners if regular else None,own_bad or stale,has_warning])
        summary[role]=hist
    assert builds['C']['cargo']['sha256']!=builds['P']['cargo']['sha256']
    assert builds['P']['driver']['sha256']==builds['C']['driver']['sha256'] and builds['P']['driver']['ino']==builds['C']['driver']['ino']
    return {'Ruff':summary,'source':{k:{'cargo_sha256':v['cargo']['sha256'],'tree':v['source']['tree'],'commit':v['source']['commit']} for k,v in builds.items()},
            'driver':builds['P']['driver']['sha256']}

def reopen_tests(data,ruff):
    j=lambda name:json.loads(data[name]);subjects=j('subjects.json');terminal=j('terminal.json')
    expected=(
        'freshness::early_cutoff_rechecks_a_repaired_test_after_failure',
        'freshness::early_cutoff_skips_check_dependents',
        'freshness::early_cutoff_skips_check_test_dependents',
        'freshness::ohm_defaults_enable_check_early_cutoff')
    assert list(expected)==subjects['tests'] and subjects['suite']['sha256']==terminal['matched_suite']['sha256']
    assert all((name+': test').encode() in data['list.gz'].splitlines() for name in expected)
    cases=[]
    for role,source in [('parent',ruff['source']['P']),('fixed',ruff['source']['C'])]:
        assert subjects['candidate' if role=='fixed' else 'parent']['sha256']==source['cargo_sha256']
        for i,name in enumerate(expected):
            red=(role=='parent' and i==0);code=101 if red else 0
            p=role+'/'+name.split('::')[-1]+'/'
            r=j(p+'result.json');out,err,trace=[data[p+f] for f in ('stdout.gz','stderr.gz','exec.log.gz')]
            assert r['role']==role and r['name']==name and r['exit']==code and r['cargo']['sha256']==source['cargo_sha256']
            assert [sha(b) for b in (out,err,trace)]==[r[k] for k in ('stdout_sha256','stderr_sha256','trace_sha256')]
            assert name.encode() in out+err and (b'1 failed' if red else b'1 passed; 0 failed') in out+err
            if red:assert b'E0308' in out+err
            absolute=r['cargo']['path']
            execs=[]
            for line in trace.decode().splitlines():
                mat=re.match(r'^(\d+)\s+[0-9.]+\s+execve\("'+re.escape(absolute)+r'",\s*\[(.*?)\],',line)
                if mat:execs.append([int(mat[1]),absolute,mat[2]])
            assert execs==r['native_argv'] and execs and all('check' in argv or '-v' in argv or '-V' in argv for pid,path,argv in execs)
            cases.append([role,name,code,len(execs)])
    assert [row[:3] for row in cases]==terminal['test_results']
    torn=terminal['torn_unit'];assert torn['exit']==0 and torn['fully_qualified'].endswith('::a_short_fingerprint_from_another_build_cannot_authorize_early_cutoff')
    assert (torn['fully_qualified']+': test').encode() in data['unit-list.gz'].splitlines()
    assert b'1 passed; 0 failed' in data['unit-stdout.gz'] and torn['fully_qualified'].encode() in data['unit-stdout.gz']
    native_unit=j('lib-compile/result.json');assert native_unit['exit']==0 and '--lib' in native_unit['command'] and '--release' in native_unit['command']
    return {'candidate_test_runner_sha256':subjects['suite']['sha256'],'cases':cases,'torn_short_json':torn['fully_qualified']}

def main():
    catalog=json.loads((HERE/'custody.json').read_bytes())
    original_files=sys.argv[1:]
    if len(original_files) not in (0,3):raise SystemExit("Pass all three original artifact ZIPs (Ruff, in-tree, matched) or no arguments")
    def payload(name,index):
        row=catalog[name]
        if original_files:return read(Path(original_files[index]),row['sha256'])
        retained=HERE/(name+'.tar.xz')
        assert retained.stat().st_size==row['retained_bytes'] and sha(retained.read_bytes())==row['retained_sha256']
        return read(retained,row['sha256'])
    raw=payload('ruff',0);d=reopen(raw)
    print(json.dumps({'ruff':d,'upgrade':reopen_upgrade(raw),'tests':reopen_tests(payload('tests',1),d),'matched':reopen_matched(payload('matched',2),raw)},indent=2,sort_keys=True))

if __name__=='__main__':main()
