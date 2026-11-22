"""Exercise incremental cache transitions with both Linux SDKs in isolated targets."""
import hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path

# Fixtures from the rustc regression tests in the candidate.
SOURCES = {
    'mono': '#![feature(rustc_attrs)]\n\nfn edited() -> usize {\n    1\n}\n\n#[inline(never)]\nfn shared<T>() -> usize {\n    std::mem::size_of::<T>()\n}\n\n#[rustc_clean(cfg = "partition_hit", loaded_from_disk = "incremental_mono_item_partitions")]\nfn main() {\n    println!("{}", edited() + shared::<u8>());\n}\n',
    'integer': '//@ revisions: bpass1 bpass2 bfail3 bfail4\n//@ compile-flags: -Zquery-dep-graph -Zthreads=1\n#![crate_type = "rlib"]\n#![feature(rustc_attrs)]\n#![allow(internal_features)]\n\npub struct Other;\n\n#[cfg(not(bpass1))]\nimpl std::ops::Add<Other> for u32 {\n    type Output = bool;\n    fn add(self, _: Other) -> bool {\n        true\n    }\n}\n\n#[cfg(not(bfail3))]\ntype Right = u32;\n#[cfg(bfail3)]\ntype Right = Other;\n#[cfg(not(bfail4))]\ntype Flag = bool;\n#[cfg(bfail4)]\ntype Flag = usize;\n\n// Both a known integer and an integer literal probe Add before the RHS has\n// been checked. An impl for a different RHS leaves the answers unchanged.\n#[rustc_clean(cfg = "bpass2", loaded_from_disk = "typeck_root")]\npub fn sum<const F: Flag>(left: u32, right: Right) -> u32 {\n    if F {\n        //[bfail4]~^ ERROR mismatched types\n        left + right\n        //[bfail3]~^ ERROR mismatched types\n    } else {\n        0 + left\n    }\n}\n',
    'dropck': '//@ revisions: bpass1 bpass2 bfail3\n//@ compile-flags: -Zquery-dep-graph -Zincremental-ignore-spans -Zthreads=1\n\n#![crate_type = "lib"]\n#![feature(rustc_attrs)]\n#![allow(internal_features, dead_code)]\n\nstruct Own<T>(T);\n\nimpl<T> Drop for Own<T> {\n    fn drop(&mut self) {}\n}\n\nstruct Bag<\'a> {\n    marker: &\'a str,\n    old: Own<u8>,\n    #[cfg(bpass2)]\n    owned: Own<String>,\n    #[cfg(bfail3)]\n    owned: Own<&\'a str>,\n}\n\n// Keep the field list of the type returned by `make` unchanged.\nstruct Outer<\'a>(Bag<\'a>);\n\nfn make(text: &str) -> Outer<\'_> {\n    Outer(Bag {\n        marker: text,\n        old: Own(0),\n        #[cfg(bpass2)]\n        owned: Own(String::new()),\n        #[cfg(bfail3)]\n        owned: Own(text),\n    })\n}\n\npub fn first<T>() {\n    // Recompute the drop-check goal in the same parameter environment as\n    // `second`. Only the second revision needs MIR for its instantiation.\n    let text = String::new();\n    let _bag = make(&text);\n    #[cfg(bpass2)]\n    second::<T>();\n}\n\n// Adding a field with an owned String should leave the drop-check result\n// unchanged. Replacing it with a borrow must make `text` live until drop.\n#[rustc_clean(cfg = "bpass2", loaded_from_disk = "mir_borrowck")]\nfn second<T>() {\n    let text = String::new();\n    let _bag = make(&text);\n    drop(text);\n    //[bfail3]~^ ERROR cannot move out of `text` because it is borrowed\n}\n',
    'borrow': '//@ revisions: nll legacy next\n//@ [nll] compile-flags: -Zpolonius=off\n//@ [legacy] compile-flags: -Zpolonius=legacy\n//@ [next] compile-flags: -Zpolonius=next\n//@ ignore-compare-mode-polonius (explicit revisions)\n\n// When many loans on one local have expired, still report the first live conflict.\nfn main() {\n    let mut pair = (0, 0);\n    let mut value = 0;\n    let other = &mut value;\n\n    macro_rules! write {\n        ($($n:literal)*) => { $(*(&mut pair.0) = $n;)* };\n    }\n    write!(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16);\n    write!(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16);\n\n    let first = &pair.0;\n    let second = &pair.0;\n    pair.1 = *other;\n    pair.0 = *other; //~ ERROR cannot assign to `pair.0` because it is borrowed\n    let _sum = first + second + pair.1;\n\n    // Also find a conflict after several live loans on another local.\n    let others = [&value, &value, &value, &value, &value, &value, &value, &value];\n    let last = &pair.0;\n    pair.0 = 1; //~ ERROR cannot assign to `pair.0` because it is borrowed\n    let _sum = last + others[0];\n}\n',
    'drops': 'use std::cell::RefCell;\n\nstruct Mark<\'a>(&\'a RefCell<String>, char);\n\nimpl Drop for Mark<\'_> {\n    fn drop(&mut self) {\n        self.0.borrow_mut().push(self.1);\n    }\n}\n\npub fn choose(out: &RefCell<String>, early: bool) {\n    let _outer = Mark(out, \'a\');\n    let (_left, _right) = (Mark(out, \'b\'), Mark(out, \'c\'));\n    {\n        let (_left, _right) = (Mark(out, \'d\'), Mark(out, \'e\'));\n        if early {\n            return;\n        }\n    } // inner\n    out.borrow_mut().push(\'!\');\n} // outer\n\nfn main() {\n    let out = RefCell::new(String::new());\n    choose(&out, false);\n    choose(&out, true);\n    assert_eq!(&*out.borrow(), "ed!cbaedcba");\n}\n',
    'table': 'extern crate table;\n\nuse table::TABLE;\n\nconst LAST: &str = TABLE[TABLE.len() - 1].1[1];\n\nfn main() {\n    assert_eq!(TABLE[0], (&["key"][..], &["value"][..]));\n    assert!(TABLE.last().unwrap().0.is_empty());\n    assert_eq!(TABLE.last().unwrap().1, &["", LAST]);\n    println!("{} {LAST}", TABLE.len());\n}\n',
}

def run(arm, kit):
    candidate = arm == 6
    rustc = [kit/'bin/rustc']
    env = dict(os.environ, RUSTC_BOOTSTRAP='1', LD_LIBRARY_PATH=str(kit/'lib'), PATH=str(kit/'bin')+':'+os.environ['PATH'])
    env.pop('OHM_RETAIN_MONO_QUERY_VALUES', None)
    observations = {}
    arm_report = report[str(arm)] = dict(version=subprocess.check_output([*rustc,'-vV'], env=env, text=True), checks={})
    def compare(case, revision, source, options, *, mode='metadata', hit=None, fail=None, execute=None, state=None, **extra):
        key = case+'-'+str(revision)
        print(arm, key, flush=True)
        row = arm_report['checks'][key] = {}
        Path('main.rs').write_text(source)
        samples=[]
        for fresh in (False, True):
            incr = Path('fresh-'+key if fresh else case)
            cmd = [*rustc, 'main.rs', '--emit='+mode, '-Cincremental='+str(incr), '-Zincremental-verify-ich', *options]
            if hit and not fresh: cmd += ['--cfg', hit]
            if state: cmd += ['-Zassert-incr-state='+('not-loaded' if fresh else state)]
            p = subprocess.run(cmd, env=env|extra, text=True, capture_output=True)
            if fail:
                assert p.returncode==1 and 'error['+fail+']' in p.stderr, (key,p.stderr)
            else:
                assert p.returncode==0, (key,p.stderr)
            lines = p.stderr.splitlines()
            messages = [x for x in lines if 'ohm_module_syntax' not in x and not x.startswith('ohm-mono-')]
            if not fresh:
                row['diagnostics']='\n'.join(messages)
                if extra.get('RUSTC_LOG'): row['syntax_reused']='reused parsed module' in p.stderr
                if not fail:
                    cache = max(incr.glob('*/s-*/query-cache.bin'))
                    data = cache.read_bytes()
                    assert data[:4]==b'RSIC'
                    row.update(bytes=len(data), header=int.from_bytes(data[4:6],'little'))
                for line in lines:
                    if line.startswith('ohm-mono-graph: crate=retained_mono '):
                        row.update({k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)})
            output = None
            if not fail and execute is not None:
                output = subprocess.check_output(['./main'], env=env, text=True)
                assert output==execute,(key,output,execute)
                row['stdout']=output
            payload = None
            if not fail and 'metadata' in mode:
                payload = hashlib.sha256(Path('libmain.rmeta').read_bytes()).hexdigest()
                row['rmeta']=payload
            if 'mir' in mode:
                payload = Path('main.mir').read_text()
                for marker in ('// inner','// outer'):
                    lineno=next(i for i,l in enumerate(source.splitlines(),1) if l.endswith(marker))
                    assert sum(l.lstrip().startswith('drop(') and f' at main.rs:{lineno}:' in l for l in payload.splitlines())>=2
            samples.append((messages,output,payload))
        assert samples[0]==samples[1], (key, str(samples)[:1800])
        observations[key]=samples[0][:2]  # Metadata encodes the compiler version.
        if not fail: return row,cache,data

    lib = ['--crate-type=rlib']
    constants = 'pub const LABEL: &str = "shared allocation";\n'+''.join(
        f'pub const C{i}: (&str,u32) = (LABEL,{i});\n' for i in range(64))
    for i in range(5):
        source=constants+f'pub const EDITED: (&str,u32) = (LABEL,{i});\n'
        row,cache,data=compare('generation',i,source,lib)
        if i==0: base=data
        row['retains_seed']=data.startswith(base)
        if candidate: assert row['retains_seed']
    old_header=report['5']['checks']['generation-0']['header'] if candidate else row['header']-1
    assert old_header!=row['header']
    for cache in Path('generation').glob('*/s-*/query-cache.bin'):
        data=cache.read_bytes()
        cache.unlink()
        cache.write_bytes(data[:4]+old_header.to_bytes(2,'little')+data[6:])
    for state in ('not-loaded','loaded'):
        compare('generation',state,source,lib,state=state)

    for i in range(5):
        marker='SYNTAX_REVISION_'+str(i)
        Path('child.rs').write_text((' '*2048 if i!=2 else '')+f'#[cfg(any())] const {marker}: () = ();\npub const VALUE: u32 = {i};')
        _,_,data=compare('syntax',i,constants+'pub mod child;',lib+['-Zohm-shared-stages'])
        if candidate: assert re.findall(rb'SYNTAX_REVISION_\d',data)==([] if i==2 else [marker.encode()])

    dense='#[allow(path_statements)] pub fn '+'d'*255+'(a:u32) {'+'a;'*1200+'}'
    deep='#[cfg(any())] fn unused() { 0'+'.method()'*1024+'; }'
    for variant,child in [('dense',dense), ('deep',deep)]:
        Path('child.rs').write_text(child)
        for i in range(2):
            row,_,_=compare(variant,i,f'pub mod child; pub const N:u8={i};',
                            lib+['-Zohm-shared-stages'],RUSTC_LOG='ohm_module_syntax=info')
        if candidate: assert row['syntax_reused']==(variant=='dense'),row

    flags=['--crate-name','retained_mono','-o','main','-Zohm-incremental-mono-partitions','-Zpublic-api-hash=no','-Zquery-dep-graph']
    for i,(v,bits) in enumerate(((1,8),(2,8),(2,16),(3,16),(3,16),(3,32)),1):
        src=SOURCES['mono'].replace('    1\n',f'    {v}\n').replace('::<u8>()',f'::<u{bits}>()')
        row,_,_=compare('mono',i,src,flags,mode='link',hit='partition_hit' if i in (2,5) else None,
                        execute=f'{v+bits//8}\n',OHM_MONO_GRAPH_TRACE='1')
        if i==2: assert row['retained_items']>0
        if candidate and i==4:
            assert row['retained']==0 and all(row['compacted_'+x]>0 for x in ('items','sizes','symbols')),row
            saved=row['compacted_items']
        if candidate and i==5: assert row['retained_items']>=saved,row

    for case,code,extra in [('integer','E0308',[]),('dropck','E0505',['-Zincremental-ignore-spans'])]:
        src=SOURCES[case].replace('rustc_clean(cfg = "bpass2"', 'rustc_clean(cfg = "hit"')
        for rev in ['bpass1','bpass2','bfail3']+(['bfail4'] if case=='integer' else []):
            compare(case,rev,src,['--cfg',rev,'-Zquery-dep-graph','-Zthreads=1']+extra,
                    hit='hit' if candidate and rev=='bpass2' else None,mode='link',
                    fail=code if rev.startswith('bfail') else None)
    for mode in ('off','next','legacy'):
        compare('borrow',mode,SOURCES['borrow'],['-Zpolonius='+mode],fail='E0506')
    for i in (0,2):
        compare('mir',i,'\n'*i+SOURCES['drops'],['--edition=2024','-Zmir-include-spans=yes'],mode='mir,link',execute='')
    for i,(rows,last) in enumerate(((63,'λ'),(64,'λ'),(64,'π'),(64,'λ'))):
        src='pub const TABLE: &[(&[&str], &[&str])] = &['+'(&["key"], &["value"]), '*(rows-1)+f'(&[], &["", "{last}"])];'
        compare('table',i,src+'\n'+SOURCES['table'].split('use table::TABLE;')[1],[],mode='link',execute=f'{rows} {last}\n')
    src=src.replace('"λ"','panic!("invalid row")')
    compare('table','invalid',src+SOURCES['table'].split('use table::TABLE;')[1],[],mode='link',fail='E0080')
    return observations

if __name__ == '__main__':
    pair, kit5, kit6, counts = sys.argv[1:]
    report={'passed':False}
    out=Path(counts).resolve()/f'cache6-{pair}.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    def test(arm,kit):
        with tempfile.TemporaryDirectory() as here:
            os.chdir(here)
            try: return run(arm,Path(kit))
            finally: os.chdir(out.parent)
    try:
        old,new=test(5,kit5),test(6,kit6)
        assert old==new,{k:(old[k],new[k]) for k in old if old[k]!=new[k]}
        report['passed']=True
    finally:
        out.write_text(json.dumps(report,indent=2)+'\n')
