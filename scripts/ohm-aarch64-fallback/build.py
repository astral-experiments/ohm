"""Produce a source-attested Linux #293 executable with the original signed -20 Cargo."""
from pathlib import Path
import gzip,hashlib,json,os,shutil,subprocess,sys,tarfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-compact'))
import kit,compare
from compare import rt,sha,save,load
from study import need
from receipt_cargo import materialize,CANDIDATE,TREE,FEATURES
CURRENT='7e591c1d2340f06a72c56893dde67bb52dab9a6ac9715efece486714af8f343f'

def main():
    assert rt.HOST=='x86_64-unknown-linux-gnu';rt.room(True);kit.bind()
    inp=rt.ROOT/'inputs'
    select,roles,_=compare.installable(inp/'sdk.tar.zst',CURRENT,inp/'native',expected_tree=kit.TREE);select('P')
    build_with_selected_sdk()

def build_with_selected_sdk(*, source_date_epoch=None):
    source=rt.ROOT/'exact-cargo-source';entry=materialize(source)
    assert entry['commit']==CANDIDATE and entry['tree']==TREE and entry['entries']==3114
    job=rt.ROOT/'cargo-build';job.mkdir();out=rt.LOG/'cargo-293-source';out.mkdir()
    save(out/'source.json',entry)
    env=rt.environment();env.update(CARGO_HOME=str(job/'registry'),CARGO_TARGET_DIR=str(job/'target'),CARGO_BUILD_BUILD_DIR=str(job/'shared'))
    if source_date_epoch is not None:
        env['SOURCE_DATE_EPOCH']=str(source_date_epoch)
    assert not any((job/n).exists() for n in ('target','registry','shared'))
    compiler=rt.record(['rustc','+ohm','-vV'],out/'compiler',source,env)
    base=rt.record(['cargo','+ohm','-Vv'],out/'builder',source,env)
    assert rt.HOST.encode() in compiler.stdout and rt.CARGO_SOURCE.encode() in base.stdout
    online=dict(env);online.pop('CARGO_NET_OFFLINE')
    args=['cargo','+ohm','-Zohm-defaults=no']
    rt.record([*args,'fetch','--locked','--target',rt.HOST],out/'fetch',source,online)
    call=[*args,'build','--release','--locked','--offline','-p','cargo','--bin','cargo','--features',FEATURES,'-j8','--message-format=json']
    traces=job/'trace';traces.mkdir()
    build=rt.record(['strace','-ff','-q','-s','262144','-e','trace=execve,execveat','-o',traces/'proc',*call],out/'construction',source,env)
    rows=[json.loads(x) for x in build.stdout.splitlines()];assert rows[-1]=={'reason':'build-finished','success':True}
    leaf,=[r for r in rows if r.get('reason')=='compiler-artifact' and r['target']['kind']==['bin'] and r['target']['name']=='cargo']
    product=Path(leaf['executable']);assert product.is_file() and product.samefile(job/'target/release/cargo')
    proc=rt.record([product,'-Vv'],out/'product-version',source,env)
    assert CANDIDATE.encode() in proc.stdout and rt.HOST.encode() in proc.stdout
    import ast,re
    files=[];hits=[]
    for f in sorted(traces.iterdir()):
        wire=f.read_bytes()
        for line in wire.splitlines():
            if not line.startswith(b'execve(') or not line.endswith(b'= 0'):continue
            m=re.match(rb'^execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:0x[^)]*|NULL)\)\s+= 0$',line);assert m,line[:170]
            path,argv=(ast.literal_eval(v.decode()) for v in m.groups())
            if Path(path).name in ('cargo','rustc'):
                files.append({'path':path,'argv':argv,'trace_sha256':hashlib.sha256(wire).hexdigest()})
                if path==str(rt.SDK/'bin/rustc') and '--crate-name' in argv and argv[argv.index('--crate-name')+1]=='cargo':hits.append(argv)
    assert any('--crate-type' in a and a[a.index('--crate-type')+1]=='bin' for a in hits) and any(r['path']==str(rt.SDK/'bin/cargo') for r in files)
    with tarfile.open(out/'native-exec.tar.gz','x:gz',compresslevel=2) as archive:archive.add(traces,arcname='trace')
    rout=rt.ROOT/'product';rout.mkdir()
    new=rout/'cargo';shutil.copy2(product,new);assert sha(new)==sha(product) and 0<new.stat().st_size<160*2**20
    assert subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=source)==b''
    seal={'source':entry,'git':CANDIDATE,'builder':sha(rt.SDK/'bin/cargo'),'SDK_source_driver':kit.BEFORE,'SDK_driver':kit.OLD_IR,'SDK':sha(rt.LOG/'P-sdk.json'),
          'command':call,'tree':TREE,'cargo_sha256':sha(new),'native_trace':sha(out/'native-exec.tar.gz'),'compiler_root_argv':hits,'raw_bytes':new.stat().st_size,
          'native_physical_cargo_rustc_events':len(files),'version':proc.stdout.decode(),'features':FEATURES,'mode':new.stat().st_mode&0o777,
          'source_workflow':os.environ['GITHUB_SHA'],'typed_units':sum(r.get('reason')=='compiler-artifact' for r in rows)}
    save(out/'verified.json',seal);save(rout/'product.json',seal);print(CANDIDATE,sha(new),new.stat().st_size)
if __name__=='__main__':main()
