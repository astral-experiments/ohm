"""Test signed-input preservation and native checked custom-build work in two immutable Cargos."""
import argparse
import gzip
import json
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parent))
import fixed_crc
import relay_fixture
import relay_source
from execs import ExecTrace
from measure import select
from native_inputs import run_archive_check
from prepare import role_files
from study import check_host,env_for,load,need,physical,save,sdk_id,sha
from zlib_study import installation

def switch(root,arm):
    sdk=select(root,'C');dst=sdk/'bin/cargo'
    if arm=='experimental':
        p=load(root/'receipts/cargo-experiment/product.json')
        need(p['source']['commit']==relay_source.CHILD and p['source']['patch_sha256']==relay_source.PATCH
             and sha(root/'cargo-experiment')==p['binary']['sha256'] and dst.samefile(root/'cargo-293'),'wrong initial Cargo')
        temp=dst.with_name('qa-relay.next');os.link(root/'cargo-experiment',temp);os.replace(temp,dst)
        save(root/'receipts/experimental-cargo-selected.json',{'commit':relay_source.CHILD,'binary':physical(dst),'build':sha(root/'receipts/cargo-experiment/product.json')})
    expected=load(root/'receipts/pair.json')['products']['C']
    ident=sdk_id(sdk,env_for(root/'relay-selection',sdk));files=role_files(sdk)
    need(files==dict(expected['runtime'],**{'bin/cargo':ident['cargo']['sha256']})
         and expected['source']=='82911b516fb35608fd70ada4deb6f8429277f410','changed common Rust compiler or SDK')
    return {'sdk':ident,'source':expected['source'],'driver_ctime':next((sdk/'lib').glob('librustc_driver*.dylib')).stat().st_ctime_ns,
            'files':files,'cargo':relay_source.CHILD if arm=='experimental' else relay_source.BASE}

def trace_arm(root,out,arm,bodies):
    trace=ExecTrace();state={}
    def check(name,work):
        try:state[name]=work()
        except Exception:
            state[name]={'error':traceback.format_exc()}
            print('QA control failed',arm,name,state[name]['error'],flush=True)
    try:
        trace.ready()
        if bodies:
            def fixture():return {'passed':relay_fixture.run_case(root,out/'build-script-inputs',arm,trace,bodies)}
            check('build-script-inputs',fixture)
        def bundled():
            run_archive_check(root,'C',trace,label=arm)
            rows=load(root/'receipts/native-input'/arm/'terminal.json')
            return {'passed':True,'statuses':{k:r['cargo_exit'] for k,r in rows.items()}}
        check('archive',bundled)
        def ruff():
            refs,rows=installation(root,'C',out/'ruff',trace)
            st={}
            for phase,q in rows.items():
                evidence=out/'ruff/visits'/phase
                stream=json.loads(gzip.decompress((evidence/'exec.json.gz').read_bytes()))
                msgs=list(map(json.loads,gzip.decompress((evidence/'stdout.gz').read_bytes()).splitlines()))
                script=[f for m in msgs if m['reason']=='compiler-artifact' and str(m['target']['src_path']).endswith('/crates/ty_vendored/build.rs') for f in m['filenames']]
                script_runs=[e for e in stream if e['path'] in script]
                n=q['native'];st[phase]={'full':n['full'],'link_only':n['link_only'],'ld':len(n['linkers']),'root_ld':len(q['root_link_argv']),
                     'file_script_events':[{'pid':e['pid'],'cdhash':e['cdhash']} for e in script_runs],
                     'script_links':sum(Path(b).name=='build_script_build' for d in n['linkers'] for a,b in zip(d['argv'],d['argv'][1:]) if a=='-o'),
                     'program':q['product'],'code':q['code']}
            return {'passed':True,'rows':st,'clean':{rev:q['product'] for rev,q in refs.items()}}
        check('ruff',ruff)
    finally:trace.close()
    return state

def run_arm(root,arm):
    check_host(root,8);dest=root/'receipts/relay-experiment'/arm;dest.mkdir(parents=True)
    if arm=='baseline':
        save(root/'receipts/relay-registration.json',{'cargo':[relay_source.BASE,relay_source.CHILD],'tree':relay_source.TREE,
            'rust':'82911b516fb35608fd70ada4deb6f8429277f410','patch':relay_source.PATCH,'steps':relay_fixture.STEPS,
            'plan_sha256':sha(root/'receipts/registration.md'),'counts_only':True})
    installed=switch(root,arm);save(dest/'installation.json',installed)
    result={};bodies=None
    try:
        fixed_crc.providers(root,'C');verdict=load(root/'receipts/provider-matrix/terminal.json')
        need(verdict['commands']==196,'incomplete original provider matrix')
        result['providers']={'passed':verdict['passed'],'off_unwatched':len(verdict['off_unwatched_comparisons'])}
        bodies={n:(root/'receipts/provider-matrix'/f'provider-{n}.a').read_bytes() for n in (17,29)}
    except Exception:
        result['providers']={'error':traceback.format_exc()}
        print('original provider matrices',result['providers'],flush=True)
    for n in ('provider-matrix','edge-images','edge-markers'):
        p=root/'receipts'/n
        if p.exists():p.rename(dest/n)
    result.update(trace_arm(root,dest,arm,bodies))
    # Archives, compiler products, original streams and fixture sources stay in receipts.
    # Park each warm directory separately in the QA runner so the next installation starts empty.
    retired=root/('finished-relay-'+arm);retired.mkdir()
    for n in ('provider-build','provider-source','provider-factory','relay-fixture-source','relay-fixture-work','native-input-work','crc-work'):
        p=root/n
        if p.exists():p.rename(retired/n)
    now=sdk_id(root/'native',env_for(root/'relay-selection',root/'native'))
    need(now==installed['sdk'],'compiler installation changed')
    save(dest/'terminal.json',result);return result

if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('arm',choices=['baseline','experimental']);cli.add_argument('root',type=Path);a=cli.parse_args()
    result=run_arm(a.root.resolve(),a.arm)
    need(set(result)=={'providers','build-script-inputs','archive','ruff'} and all(r.get('passed') is True for r in result.values()),'one or more native correctness controls failed')
