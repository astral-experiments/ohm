"""Check a real Unicode edit and its upstream compiler exports on the locked Ruff source."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

WORK = Path(os.environ['RUNNER_TEMP']) / 'literal-scout'
SRC = Path(os.environ['GITHUB_WORKSPACE']) / 'ruff'
SDK = WORK.parent / 'signed-sdk'
LOG = WORK / 'records'
STATE = WORK / 'state'
OLD = '47fdae55e8daf3f39e670e592fe0ce9457dab8d6'
NEW = 'a7b52a15654cd991d7a2e212ee0cd579cd714450'
LOCK = '21fec14636f2cc62da2dc779b6d6b9da93c492dcc0de534fc4c2277c95ef776b'
FILES = ['crates/ruff_python_literal/src/char.rs','crates/ruff_python_literal/src/escape.rs',
         'crates/ty_python_core/src/ast_node_ref.rs','crates/ty_python_semantic/resources/mdtest/literal/string.md']
CASES = {
    'mixed': ('é\u212b', r'"\xe9\u212b"', r'"é\u212b"'),
    'blank': ('\u2800', '"\u2800"', r'"\u2800"'),
    'angstrom': ('\u212b', r'"\u212b"', r'"\u212b"'),
    'nfc': ('Å','"Å"','"Å"'),
    'ascii': ('ordinary','"ordinary"','"ordinary"'),
}
CALLER = '''use ruff_python_ast::str::{Quote, TripleQuotes};
use ruff_python_literal::escape::UnicodeEscape;

fn main() {
    let source = std::env::args().nth(1).unwrap();
    let escaped = UnicodeEscape::with_preferred_quote(&source, Quote::Double).escape_for_display();
    print!("{}", escaped.str_repr(TripleQuotes::No));
}
'''
def sha(p):
    with p.open('rb') as fp: return hashlib.file_digest(fp, 'sha256').hexdigest()
def dump(path, payload):
    path.write_text(json.dumps(payload,sort_keys=True,indent=2)+'\n')
def git(*args):
    return subprocess.check_output(['git','-C',str(SRC),*args]).decode().strip()
def observe(arm, name, args, env):
    assert shutil.disk_usage(WORK).free>8<<30
    p=subprocess.run(args,cwd=SRC,env=env,capture_output=True,timeout=360)
    (arm/(name+'.stdout.gz')).write_bytes(gzip.compress(p.stdout,compresslevel=4,mtime=0))
    (arm/(name+'.stderr.gz')).write_bytes(gzip.compress(p.stderr,compresslevel=4,mtime=0))
    if p.returncode: raise RuntimeError((name,p.returncode,p.stderr.decode(errors='replace')[-3000:]))
    return p.stdout

def main():
    assert os.environ['GITHUB_REF']=='refs/heads/charlie/qa-ruff-literal-29206-20261102'
    assert git('rev-parse',NEW+'^')==OLD and git('diff','--name-only',OLD,NEW).splitlines()==FILES and not git('status','--porcelain')
    LOG.mkdir(parents=True)
    driver,=(SDK/'lib').glob('librustc_driver-*.so')
    tools={'bin/rustc':'7e35096dab1b661924cb3c31982c870dd99c7c00a7fba28aa958f451e7c9474e',
           'bin/cargo':'3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871',
           str(driver.relative_to(SDK)):'4c8ccf0072e8f382a3a3756fd60e46936a2bd206996201c55caffe58d29725db',
           'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd':'0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'}
    for name,want in tools.items(): assert sha(SDK/name)==want,(name,sha(SDK/name))
    assert (SDK/'bin/rustdoc').is_file()
    rustup=WORK/'rustup';(rustup/'toolchains').mkdir(parents=True);(rustup/'toolchains/ohm').symlink_to(SDK)
    (rustup/'settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    proxies=WORK/'proxies';proxies.mkdir()
    for name in ('rustc','rustdoc','cargo'): (proxies/name).symlink_to(Path(shutil.which('rustup')).resolve(strict=True))
    home=WORK/'cargo-home';home.mkdir()
    env={'HOME':str(WORK/'home'),'PATH':str(proxies)+':/usr/bin:/bin','RUSTUP_HOME':str(rustup),'RUSTUP_AUTO_INSTALL':'0',
         'CARGO_HOME':str(home),'CARGO_TARGET_DIR':str(STATE/'target'),'CARGO_BUILD_BUILD_DIR':str(STATE/'build'),
         'CARGO_TERM_COLOR':'never','LC_ALL':'C','RUST_BACKTRACE':'0','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never'}
    (WORK/'caller.rs').write_text(CALLER)
    dump(LOG/'enrollment.json',dict(head=os.environ['GITHUB_SHA'],tools=tools,asset=(WORK.parent/'ohm-asset.tsv').read_text().strip(),source=[OLD,NEW],paths=FILES,lock=LOCK))
    proof={}
    for label,rev in [('old',OLD),('edit',NEW),('clean',NEW)]:
        arm=LOG/label;arm.mkdir()
        git('checkout','--quiet','--detach',rev)
        assert not git('status','--porcelain') and sha(SRC/'Cargo.lock')==LOCK
        if label=='clean': STATE.rename(WORK/'prior-state')
        if label!='old':env['CARGO_NET_OFFLINE']='true'
        args=['cargo','+ohm','build','--lib','-p','ruff_python_literal','--locked','-j2','--message-format=json']
        output=observe(arm,'cargo',args,env);rows=[json.loads(l) for l in output.splitlines()]
        assert rows[-1]=={'reason':'build-finished','success':True}
        products=[r for r in rows if r['reason']=='compiler-artifact']
        fresh=sum(r['fresh'] for r in products)
        assert 0 < fresh < len(products) if label=='edit' else fresh==0
        ffi={r['target']['name']:Path(f) for r in products for f in r['filenames'] if f.endswith('.rlib')}
        locks={(p['name'],p['version']):p.get('checksum') for p in tomllib.loads((SRC/'Cargo.lock').read_text())['package']}
        archives={}
        for r in products:
            if not r['package_id'].startswith('registry+'):continue
            name,ver=r['package_id'].rsplit('#',1)[1].rsplit('@',1)
            if (name,ver) in archives:continue
            [file]=(home/'registry/cache').glob('*/'+name+'-'+ver+'.crate')
            archives[name,ver]=sha(file);assert archives[name,ver]==locks[name,ver]
        assert all((k,'2.3.0') in archives for k in ('icu_normalizer','icu_properties'))
        save_dep={k+'@'+v:h for (k,v),h in archives.items()}
        dirs=sorted({str(Path(f).parent) for r in products for f in r['filenames'] if f.endswith(('.rlib','.rmeta','.so'))})
        caller=['rustc','+ohm','--edition=2024',WORK/'caller.rs','--extern','ruff_python_ast='+str(ffi['ruff_python_ast']),
                '--extern','ruff_python_literal='+str(ffi['ruff_python_literal'])]
        for d in dirs: caller+=['-L','dependency='+d]
        binary=WORK/'reader'
        observe(arm,'compile-reader',[*caller,'-o',binary],env)
        verdicts={}
        for k,(value,old,new) in CASES.items():
            verdicts[k]=observe(arm,k,[binary,value],env).decode()
        rosters=sorted([r['package_id'],r['target']['name'],r['target']['kind'],r['features'],r['profile']['test']] for r in products)
        leaf=ffi['ruff_python_literal']
        observe(arm,'nm',['nm','--defined-only','--extern-only','-C',leaf],env)
        observe(arm,'raw-nm',['nm','--defined-only','--extern-only','--no-demangle',leaf],env)
        for p in [leaf,binary]:
            (arm/(p.name+'.gz')).write_bytes(gzip.compress(p.read_bytes(),compresslevel=2,mtime=0))
        record=dict(source=rev,verdicts=verdicts,ffi={n:sha(ffi[n]) for n in ('ruff_python_literal','ruff_python_ast','icu_normalizer','icu_properties')},
                    binary=sha(binary),locked_archives=save_dep,roster=rosters,dirty=sum(not r['fresh'] for r in products))
        dump(arm/'record.json',record);proof[label]=record
        assert all(verdicts[k]==row[1 if label=='old' else 2] for k,row in CASES.items()),verdicts
        # Preserve the ordinary artifacts first. Collect the separate diagnostic after the edit and fresh builds.
        if label in ('old','clean'):
            mono=['cargo','+ohm','rustc','--offline','--locked','--lib','-p','ruff_python_literal','-j2','--','-Zprint-mono-items']
            separate=dict(env,CARGO_TARGET_DIR=str(WORK/('diag-'+label)/'target'),CARGO_BUILD_BUILD_DIR=str(WORK/('diag-'+label)/'build'))
            text=observe(arm,'mono',mono,separate);assert b'MONO_ITEM ' in text
    a,e,c=(proof[x] for x in ('old','edit','clean'))
    assert a['locked_archives']==e['locked_archives']==c['locked_archives'] and a['roster']==e['roster']==c['roster']
    assert e['verdicts']==c['verdicts'] and {k for k in CASES if a['verdicts'][k]!=e['verdicts'][k]}=={'mixed','blank'}
    assert e['binary']==c['binary'] and a['binary']!=c['binary']
    for k in ('icu_normalizer','icu_properties','ruff_python_ast'):assert a['ffi'][k]==e['ffi'][k]
    dump(LOG/'accepted.json',{'head':os.environ['GITHUB_SHA'],'base':OLD,'edit':NEW,'revisions':{k:{n:x[n] for n in ('source','binary','dirty','verdicts','ffi')}for k,x in proof.items()}})
if __name__=='__main__':main()
