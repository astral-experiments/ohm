"""Reopen raw coverage transcripts and profraws, without running any archived binaries."""
import argparse,hashlib,json,os,re,subprocess,sys,tempfile,tomllib,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent
CARGOSHA='abc70d60a6fd89c10d5f65cf85820d9b78d5affe';RUSTSHA='c3aa3a605e56878669c745a9dd3ba09c9ccfa1ef'
MODE=('environment','profile','cargo-rustc');PHASE=('old','upgrade','repeat')
MAIN=b'fn main() {\n    let answer = 29;\n    println!("answer={answer}");\n}\n'
MANIFEST='[package]\nname="coverage_case"\nversion="0.1.0"\nedition="2021"\n[workspace]\n'
PATHMAIN=b'include!(concat!(env!("CARGO_MANIFEST_DIR"), "/src/location.rs"));\nfn main() { println!("{}", declared()); }\n'
LOCATION=b"fn declared() -> &'static str { file!() }\n"
LOCAL=Path(os.environ.get('OHM_LLVM_TOOLS_SYSROOT', Path.home() / '.rustup/toolchains/1.99.0-x86_64-unknown-linux-gnu'))
BIN=LOCAL/'lib/rustlib/x86_64-unknown-linux-gnu/bin'
def sha(b):return hashlib.sha256(b).hexdigest()
def realhash(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def ishash(s):assert re.fullmatch('[0-9a-f]{64}',s),s;return s
def check(v,why):assert v,why
def cmd(read,p):
    d=json.loads(read(p+'.json'));assert set(d)=={'argv','status'}and d['status']==0,p
    return d['argv'],read(p+'.stdout'),read(p+'.stderr')
def inspect_prof(path,env,expected,name):
    p=subprocess.run([BIN/'llvm-profdata','show','--all-functions','--counts',path],env=env,capture_output=True,check=True,timeout=15)
    s=p.stdout.decode();assert not p.stderr and re.findall(r'^    Function count: (\d+)$',s,re.M)==[str(expected)]and '\nTotal functions: 1\n' in s and '\n  '+name+':\n' in s
    h,=re.findall(r'^    Hash: (0x[0-9a-f]+)$',s,re.M);return h
def coverage(tag,mode,good,read,llvm,env,td,results):
    f=lambda n:read(tag+'/'+n)
    meta=json.loads(f('settings.json'));assert meta['mode']==mode
    work=PurePosixPath(meta['project']);assert work.is_absolute()and work.name=='project'
    src=work/'src/main.rs';assert f('main.rs')==MAIN
    mf=f('Cargo.toml');parsed=tomllib.loads(mf.decode());assert parsed['package']['name']=='coverage_case'
    extra=['-C','instrument-coverage']
    assert meta['RUSTFLAGS']==('-Cinstrument-coverage'if mode=='environment'else None)
    if mode=='profile':assert parsed['profile']['dev']['rustflags']==extra and parsed['cargo-features']==['profile-rustflags']
    else:assert mf.decode()==MANIFEST
    comp,out,err=cmd(f,'compile');assert comp==['cargo','+ohm','rustc'if mode=='cargo-rustc'else'build','--bin','coverage_case','--offline','--message-format=json']+(['--',*extra]if mode=='cargo-rustc'else[])
    rows=list(map(json.loads,out.splitlines()));assert rows[-1]=={'reason':'build-finished','success':True}
    unit,=[v for v in rows if v['reason']=='compiler-artifact'];exe=unit['executable'];assert PurePosixPath(exe)==PurePosixPath(meta['target'])/'debug/coverage_case' and unit['target']['kind']==['bin']and unit['target']['src_path']==str(src)and unit['manifest_path']==str(work/'Cargo.toml')and unit['fresh'] is not None
    dest=td/tag;dest.mkdir();claimed=json.loads(f('result.json'));assert claimed['source_sha256']==sha(MAIN)and claimed['manifest_sha256']==sha(mf)and claimed['executable']==exe and claimed['fresh']==unit['fresh']
    export_cmd,export_out,export_err=cmd(f,'export');show_cmd,show_out,show_err=cmd(f,'show')
    assert not export_err and show_cmd[:2]==[llvm['llvm-cov']['path'],'show']and export_cmd[:2]==[llvm['llvm-cov']['path'],'export']and show_cmd[2:]==export_cmd[2:]and show_cmd[2]==exe and len(show_cmd)==4
    exported=json.loads(export_out);assert exported['type']=='llvm.coverage.json.export'
    data,=exported['data'];frame,=data['files'];fn,=data['functions']
    filename=frame['filename'];assert fn['count']==2 and fn['filenames']==[filename]and fn['name'].endswith('4main')
    # Check every nonempty function region and the actual line range against the source.
    assert fn['regions'] and all(segment[4:]==[2,0,0,0]and 1<=segment[0]<=segment[2]<=4 for segment in fn['regions'])
    assert frame['summary']['lines']['percent']==100 and frame['summary']['lines']['count']==frame['summary']['lines']['covered']>0
    assert claimed['filename']==filename and claimed['count']==2 and claimed['lines']==frame['summary']['lines']
    actual=[]
    for i in (1,2):
        role='execution-'+str(i);launch,sout,serr=cmd(f,role)
        assert launch==[exe]and sout==b'answer=29\n'and not serr
        raw=f(role+'.profraw');assert raw and sha(raw)==claimed['raw_sha256'][i-1];p=dest/(role+'.profraw');p.write_bytes(raw);actual.append(p)
    merge,noise,error=cmd(f,'merge');assert not noise and not error and merge[:3]==[llvm['llvm-profdata']['path'],'merge','-sparse']and merge[-2]=='-o' and len(merge)==7
    dist=PurePosixPath(merge[-1]).parent;assert dist.name==tag and merge[3:5]==[str(dist/p.name)for p in actual]and show_cmd[-1]=='-instr-profile='+str(dist/'merged.profdata')
    native=f('merged.profdata');original=dest/'original.profdata';original.write_bytes(native);assert sha(native)==claimed['merged_sha256']
    merged=dest/'independent.profdata'
    proc=subprocess.run([BIN/'llvm-profdata','merge','-sparse',*actual,'-o',merged],env=env,capture_output=True,check=True,timeout=15)
    assert not proc.stderr
    hashes=[inspect_prof(p,env,1,fn['name'])for p in actual]+[inspect_prof(p,env,2,fn['name'])for p in(original,merged)]
    assert len(set(hashes))==1
    expected_lines=[(i+1,2,text)for i,text in enumerate(MAIN.splitlines())]
    rendered=[(int(x),int(n),v)for x,n,v in re.findall(rb'^\s*(\d+)\|\s*(\d+)\|([^\r\n]*)$',show_out,re.M)]
    if good:assert filename==str(src) and not show_err and rendered==expected_lines,(tag,filename,show_err,rendered)
    else:assert not rendered and not show_out.strip() and re.fullmatch(r'/ohm-workspace/v[0-9]+/src/main\.rs',filename)and filename.encode()in show_err and b'No such file or directory'in show_err,(tag,filename,show_err)
    assert claimed['rendered']==good and claimed['annotated_line_counts']==([2]if good else[])
    results[tag]={'source':filename,'rendered_lines':[[line,n,v.decode()]for line,n,v in rendered],'recorded_executable_sha256':ishash(claimed['exe_sha256']),'raw_sha256':claimed['raw_sha256'],'raw_function_counts':[1,1],'merged_function_count':2,'function':fn['name'],'function_hash':hashes[0],'independent_merge_sha256':realhash(merged),'archived_merge_sha256':sha(native),'identical_profdata':merged.read_bytes()==native,'fresh':unit['fresh'],'export_sha256':sha(export_out),'cargo_command':comp}
    return claimed
def remap(tag,expected,good,read,results):
    f=lambda n:read(tag+'/'+n);decl=f('Cargo.toml');records=tomllib.loads(decl.decode())
    assert records['cargo-features']==['profile-rustflags']and records['profile']['dev']['rustflags'][0]=='--remap-path-prefix'
    source,to=records['profile']['dev']['rustflags'][1].split('=',1);assert PurePosixPath(source).is_absolute()and to==expected
    launch,out,err=cmd(f,'run');assert launch==['cargo','+ohm','run','--offline','--quiet']and not err
    actual,=out.decode().splitlines();claimed=json.loads(f('result.json'));expect=expected+'/src/location.rs'
    assert claimed['files']=={'Cargo.toml':sha(decl),'main.rs':sha(PATHMAIN),'location.rs':sha(LOCATION)}and claimed['observed']==actual and claimed['declared']==expect
    if good:assert actual==expect
    else:assert re.fullmatch(r'/ohm-workspace/v[0-9]+/src/location\.rs',actual)and actual!=expect
    results[tag]={'manifest_declared':expect,'actual':actual,'source_dir':source,'recorded_executable_sha256':ishash(claimed['exe_sha256']),'manifest_sha256':sha(decl),'cargo_command':launch}
    return actual
def cases(raw,coverage_files,host):
    results={};llvm=json.loads(raw('tools.json'));assert set(llvm)=={'llvm-cov','llvm-profdata'}
    for name,info in llvm.items():
        p=PurePosixPath(info['path']);ishash(info['sha256']);assert p.name==name and str(p).endswith('/coverage-rustup/toolchains/1.99.0-'+host+'/lib/rustlib/'+host+'/bin/'+name)
        launch,out,err=cmd(raw,name);assert launch==[str(p),'--version']and not err and re.search(rb'LLVM version 23\.1\.',out)
        if host=='x86_64-unknown-linux-gnu':assert realhash(BIN/name)==info['sha256'],(name,info)
    env={k:os.environ[k]for k in ('PATH','HOME','LANG')if k in os.environ};env['LD_LIBRARY_PATH']=str(LOCAL/'lib')
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='decoded-')as work:
        td=Path(work);warm=json.loads(raw('warm-upgrade.json'));assert [p['phase']for p in warm['phases']]==list(PHASE)
        expected=set()
        for good,role in [(False,'signed'),(True,'fixed')]:
            for mode in MODE:
                tag=role+'-'+mode;expected.add(tag);coverage(tag,mode,good,raw,llvm,env,td,results)
            remaps=[]
            for phase in ('first','second'):
                tag=role+'-path-'+phase;expected.add(tag);remaps.append(remap(tag,'/declared-'+phase,good,raw,results))
            assert (remaps[0]!=remaps[1])==good and results[role+'-path-first']['source_dir']==results[role+'-path-second']['source_dir']
        roots=[]
        for phase,entry in zip(PHASE,warm['phases']):
            good=phase!='old';tag='warm-coverage-'+phase;expected.add(tag);v=coverage(tag,'environment',good,raw,llvm,env,td,results);assert entry['coverage']==v
            tag='warm-path-'+phase;expected.add(tag);assert remap(tag,'/declared-warm',good,raw,results)==entry['path']
            launch,out,err=cmd(raw,'warm-sysroot-'+phase);assert launch==['rustc','+ohm','--print','sysroot']and not err;roots.append(out.decode().strip())
        assert len(expected)==16 and {p.split('/')[0]for p in coverage_files if p.endswith('/result.json')}==expected
        assert len(set(roots))==1 and len({results['warm-path-'+p]['source_dir']for p in PHASE})==1
        assert len({json.loads(raw('warm-coverage-'+p+'/settings.json'))['project']for p in PHASE})==1
        assert results['warm-coverage-repeat']['recorded_executable_sha256']==results['warm-coverage-upgrade']['recorded_executable_sha256']
    return {'cases':results,'warm':warm,'LLVM':llvm,'signed_sysroot_through_warm_upgrade':roots[0]}
def bind(z,host,results):
    raw=lambda s:json.loads(z.read(s));p=raw('signed.json');c=raw('candidate.json');s=raw('sources.json')
    for record in c,s:assert record['rust']==RUSTSHA and record['cargo']==CARGOSHA
    signed_archives={'aarch64-apple-darwin':'371e7cb6ca778e44b599ee4fbb83c7ca85f6306353825bce1d40f7d692f03a53','x86_64-unknown-linux-gnu':'fc85a2ca6d47711058cd89c790c8e57f1799472e38f0ee0a08b0a51d06c1ee7b'}
    assert p['release']==signed_archives[host]
    manifest=raw('source-manifest-for-qa.json');assert manifest['sources']['rust']['revision']==RUSTSHA and manifest['sources']['cargo']['revision']==CARGOSHA
    assert 'build.profiler=true'in c['rust_command']and '--stage'in c['rust_command']
    binds={'P':p['tools'],'C':c['tools']};driver,=[k for k in p['tools']if 'librustc_driver-'in k];cdriver,=[k for k in c['tools']if 'librustc_driver-'in k]
    for role,ds in binds.items():
        assert len(ds)==4 and {'bin/cargo','bin/rustc','bin/rustdoc'}<=set(ds)
        for x in ds.values():ishash(x)
    assert binds['P']['bin/cargo']!=binds['C']['bin/cargo']and binds['P'][driver]!=binds['C'][cdriver]
    old=results['warm']['unchanged_rust'];assert old['bin/rustc'][2]==binds['P']['bin/rustc']and old[driver][2]==binds['P'][driver]and len(old)==3
    std,=[v for k,v in old.items()if k.startswith('lib/rustlib/'+host+'/lib/libstd-')and k.endswith('.rlib')]
    for dev,ino,h in old.values():assert dev>=0 and ino>0 and ishash(h)
    assert [x['cargo_sha256']for x in results['warm']['phases']]==[binds['P']['bin/cargo'],binds['C']['bin/cargo'],binds['C']['bin/cargo']]
    accepted='accepted-combined.json' in z.namelist()
    if accepted:a=raw('accepted-combined.json');assert a['rust']==RUSTSHA and a['cargo']==CARGOSHA and a['tools']==binds
    return {'sources':s,'candidate':c,'signed':p,'complete_combined_verdict':accepted,'source_manifest_sha256':sha(z.read('source-manifest-for-qa.json')),'pinned_other_sources':{k:v for k,v in manifest['sources'].items()if k not in ('rust','cargo')},'pinned_bundled_tools':manifest['bundled_tools'],'scope':'Compiler and Cargo SHA are independently joined across native build and exercise records. Their executable payloads are excluded by this small-verdict-archive reader.'}
def actual(path,rec,host):
    assert realhash(path)==rec['digest'].split(':')[1]and path.stat().st_size==rec['size_in_bytes']and path.stat().st_size<260*2**20
    with zipfile.ZipFile(path)as z:
        ns=z.namelist();assert len(ns)==len(set(ns))and z.testzip()is None
        if 'coverage-failure.txt'in ns:raise AssertionError(z.read('coverage-failure.txt').decode())
        prefix='coverage-source/';fs={f.removeprefix(prefix)for f in ns if f.startswith(prefix)}
        if not fs:raise AssertionError('No coverage receipts: '+', '.join(sorted(ns)[:25]))
        result=cases(lambda f:z.read(prefix+f),fs,host);result['source_tool_binding']=bind(z,host,result);result['github_original']=rec
        return result
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--fixture',type=Path);parser.add_argument('--zip',type=Path);parser.add_argument('--artifact',type=Path);parser.add_argument('--host',required=True);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    if args.fixture:
        result=cases(lambda f:(args.fixture/f).read_bytes(),{str(f.relative_to(args.fixture))for f in args.fixture.rglob('*')if f.is_file()},args.host)
    else:result=actual(args.zip,json.loads(args.artifact.read_bytes()),args.host)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(args.host,len(result['cases']),'semantic cases, same signed Rust on warm upgrade',realhash(args.output))
