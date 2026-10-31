"""Record scheduling state when only the fixture's 15-second test barrier remains."""
import concurrent.futures as cf
import gzip
import json
import os
from pathlib import Path
import signal
import subprocess
import time

def instrument(src):
    test=src/'tests/testsuite/ohm_ready_tests.rs';before=test.read_text();s=before
    old='let status = Command::new(program).args(args).status().unwrap();'
    new='''let is_build_script = args.windows(2).any(|a| a[0] == "--crate-name" && a[1] == "build_script_build");
                let status = Command::new(program).args(args).status().unwrap();
                if is_build_script && env::var("READY_MODE").as_deref() == Ok("runtime") {
                    if let Ok(ms) = env::var("QA_READY_DELAY_MS") { thread::sleep(Duration::from_millis(ms.parse().unwrap())); }
                }'''
    assert s.count(old)==1;s=s.replace(old,new)
    old='    cmd\n}\n\nfn seed('
    new='''    if mode == "runtime" {
        if std::env::var_os("QA_READY_LOG").is_some() {
            cmd.env("CARGO_LOG", "cargo::compiler::job_queue=trace,cargo::compiler::fingerprint=trace,cargo::compiler::build_runner=debug");
            cmd.arg("-vv");
        }
        if let Ok(ms) = std::env::var("QA_READY_DELAY_MS") { cmd.env("QA_READY_DELAY_MS", ms); }
    }
    cmd
}

fn seed('''
    assert s.count(old)==1;s=s.replace(old,new)
    test.write_text(s)
    return before.encode(),s.encode()

def fixture_snapshot(fixture):
    foo=fixture/'foo';paths=[foo/x for x in ('a/build.rs','a/src/main.rs','z/src/lib.rs','a/src/lib.rs','a/tests/runtime.rs')]
    p=foo/'target/debug'
    paths.extend(x for x in p.glob('build/a-*/*') if x.is_file())
    paths.extend(x for x in p.glob('build/a-*/out/value') if x.is_file())
    paths.extend(x for x in p.glob('.fingerprint/a-*/*') if x.is_file())
    paths.extend(x for x in p.glob('.fingerprint/z-*/*') if x.is_file())
    out={}
    for f in paths:
        try:
            t=f.stat();data=f.read_bytes() if t.st_size<25000 else None
            out[str(f.relative_to(fixture))]={'size':t.st_size,'mtime_ns':t.st_mtime_ns,'data':data.hex() if data is not None else None}
        except FileNotFoundError:pass
    return out

def stacks(directory,rows,fixture):
    tasks=[i for i,r in rows.items() if ('cargo test --workspace --lib -j2' in r[2] or 'ready-wrapper rustc' in r[2] or 'rustc --crate-name' in r[2] or 'build-script-build' in r[2])]
    assert len(tasks)<15
    def one(pid):
        p=directory/f'sample-{pid}.txt'
        res=subprocess.run(['/usr/bin/sample',str(pid),'1','5','-file',str(p)],capture_output=True,timeout=7)
        if p.exists():
            data=p.read_bytes()
            with gzip.open(directory/(p.name+'.gz'),'xb') as g:g.write(data)
            p.unlink()
        return [pid,res.returncode,res.stderr.decode(errors='replace')[-250:]]
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        matched=list(pool.map(one,tasks))
    return {'targets':matched,'processes':rows,'snapshot':fixture_snapshot(fixture)}
