"""Observe real custom-build executable linking, execution and generated Rust on Apple."""
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import provider_edges as edges
from fixed_crc import evidence
from measure import capture, native_rows, select
from study import check_host, compress_bytes, env_for, need, run, save, sha

STEPS = (
    ('lower','lower',7,1,(2,)), ('unchanged','lower',7,1,(2,)),
    ('higher','higher',7,1,(2,)), ('unchanged-higher','higher',7,1,(2,)),
    ('environment','higher',7,3,(2,)), ('directory-add','higher',7,3,(2,5)),
    ('directory-replace','higher',7,3,(4,5)), ('directory-remove','higher',7,3,(4,)),
    ('edit-build-script','higher',11,3,(4,)), ('invalid-build-script','higher',None,3,(4,)),
    ('repair-build-script','higher',13,3,(4,)),
    ('malformed','malformed',13,3,(4,)), ('repair-native','higher',13,3,(4,)),
    ('missing','missing',13,3,(4,)), ('restored','lower',19,3,(4,)),
    ('restored-unchanged','lower',19,3,(4,)),
)
COMPILER = '[package]\nname="{}"\nversion="0.0.1"\nedition="2021"\n'
BUILD_RS = '''use std::{fs,io::Write,path::PathBuf};
#[link(name="qa_owned_external",kind="static")]
unsafe extern "C" { fn qa_value()->i32; }
fn main() {
  println!("cargo:rerun-if-changed=build.rs");
  println!("cargo:rerun-if-changed=watched");
  println!("cargo:rerun-if-env-changed=QA_RELAY_TUNE");
  let dir=PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
  let inputs:i32=fs::read_dir(dir.join("watched")).unwrap().map(|e|fs::read_to_string(e.unwrap().path()).unwrap().parse::<i32>().unwrap()).sum();
  let tune:i32=std::env::var("QA_RELAY_TUNE").unwrap().parse().unwrap();
  let native=relay_barrier::barrier(unsafe { qa_value() });
  let witness=format!("{native} SRC_VALUE {tune} {inputs}");
  let rust=SRC_EXPR;
  let result=format!("{native} {rust} {tune} {inputs}");
  let mut log=fs::OpenOptions::new().create(true).append(true).open(std::env::var_os("QA_RELAY_LOG").unwrap()).unwrap();
  writeln!(log,"{witness} {result}").unwrap();
  let out=PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
  fs::write(out.join("verdict.rs"),format!("const VERDICT:&str={result:?};")).unwrap();
}
'''
HELPER_BUILD = '''fn main() {
    let parent=std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    println!("cargo:rerun-if-changed=build.rs");
    for part in ["early","late"] {
        println!("cargo:rustc-link-search=native={}",parent.parent().unwrap().join(part).display());
    }
}
'''
def replace(path,body):
    if not path.is_file() or path.read_bytes()!=body:path.write_bytes(body)

def prepare(src):
    for n in ('src','helper/src','early','late','watched'):(src/n).mkdir(parents=True)
    (src/'Cargo.toml').write_text(COMPILER.format('qa_relay')+'[build-dependencies]\nrelay_barrier={path="helper"}\n[workspace]\nresolver="2"\n')
    (src/'helper/Cargo.toml').write_text(COMPILER.format('relay_barrier')+'links="qa_relay_inputs"\n')
    (src/'helper/build.rs').write_text(HELPER_BUILD)
    (src/'helper/src/lib.rs').write_text(edges.BARRIER)
    (src/'src/main.rs').write_text('include!(concat!(env!("OUT_DIR"),"/verdict.rs")); fn main(){println!("{}",VERDICT);}\n')
    script(src,7)

def script(src,number):
    val=str(number) if number is not None else 'qa_unknown_build_script_name'
    replace(src/'build.rs',BUILD_RS.replace('SRC_VALUE',val).replace('SRC_EXPR',val).encode())

def observation(root,src,work,sdk,env,path,trace,images):
    log=Path(env['QA_RELAY_LOG']);before=log.read_bytes() if log.is_file() else b''
    cmd=['cargo','+ohm','build','--locked','--offline','--message-format=json']
    code,stdout,stderr,events,streams=capture(cmd,src,env,path,trace)
    after=log.read_bytes() if log.is_file() else b'';need(after.startswith(before),'build-script oracle truncated')
    own=after[len(before):].decode().splitlines();msgs=list(map(json.loads,stdout.splitlines()))
    need(code in (0,101) and msgs[-1]=={'reason':'build-finished','success':code==0},'non-Cargo terminal')
    n=native_rows(events,sdk);need(n['cargo']==1 and n['scope']=='kernel-exec' and all(x['stock'] for x in n['linkers']),'missing enrolled native work')
    builds=[row for row in msgs if row['reason']=='compiler-artifact' and Path(row['target']['src_path'])==src/'build.rs']
    returned=[row for row in msgs if row['reason']=='compiler-artifact' and row['target']['name']=='qa_relay' and row.get('executable')]
    diagnostics=[(row['message'].get('code') or {}).get('code') for row in msgs if row['reason']=='compiler-message']
    output=None;raw=None;generated=None
    if code==0:
        need(len(returned)==1,'successful Cargo did not return exactly one native reader')
        exe=Path(returned[0]['executable']);data=exe.read_bytes();raw=sha(exe);edges.mach(data)
        file=images/(raw+'.gz')
        if not file.exists():compress_bytes(file,data)
        output=run([str(exe)],cwd=src).decode().strip()
        produced=[Path(row['out_dir'])/'verdict.rs' for row in msgs if row['reason']=='build-script-executed' and (Path(row['out_dir'])/'verdict.rs').is_file()]
        need(len(produced)==1,'missing or ambiguous generated Rust')
        generated=produced[0].read_text();need(generated==f'const VERDICT:&str="{output}";','generated bytes differ from executable')
    else:need(not returned,'failed build reported executable')
    scripts=[a for a in events if Path(a['path']).name in ('build_script_build','build-script-build')]
    link_path=[b for x in n['linkers'] for a,b in zip(x['argv'],x['argv'][1:]) if a=='-o']
    row={'status':code,'program':output,'sha256':raw,'generated':generated,'script_executions':scripts,'oracle':own,
         'emitted_script_outputs':[v['filenames'] for v in builds],'diagnostics':diagnostics,'ld_output':link_path,
         'native':n,'streams':streams,'mentions_native':('qa_owned_external' in (stdout+stderr).decode(errors='replace'))}
    evidence(work,path,row);save(path/'verified.json',row)
    return row

def run_case(root,out,role,trace,bodies):
    work=root/'relay-fixture-work';src=root/'relay-fixture-source';work.mkdir();src.mkdir()
    for name in ('target','shared','cargo-home'):(work/name).mkdir()
    images=out/'images';images.mkdir(parents=True)
    sdk=select(root,'C');env=env_for(work,sdk);env['QA_RELAY_LOG']=str(work/'script.log')
    prepare(src);run(['cargo','+ohm','generate-lockfile','--offline'],cwd=src,env=env)
    save(out/'sources.json',{str(p.relative_to(src)):p.read_text() for p in src.rglob('*') if p.is_file()})
    rows={};wrong=[]
    for phase,state,rust,env_val,files in STEPS:
        check_host(root,7);script(src,rust);env['QA_RELAY_TUNE']=str(env_val);edges.configure(src,state,bodies)
        for idx in range(2):
            name=src/'watched'/str(idx)
            if idx<len(files):replace(name,str(files[idx]).encode())
            else:name.unlink(missing_ok=True)
        def phase_run(which):return observation(root,src,work,sdk,env,out/phase/which,trace,images)
        a=phase_run('warm');b=edges.with_empty(work,lambda:phase_run('empty'))
        code=0 if rust is not None and edges.NATIVE[state] else 101
        value=f'{edges.NATIVE[state]} {rust} {env_val} {sum(files)}' if code==0 else None
        def valid(q):
            return (q['status'],q['program'])==(code,value) and (code==0 or ('E0425' in q['diagnostics'] if rust is None else q['mentions_native']))
        row={'code':code,'expected':value,'warm':[a['status'],a['program'],a['sha256']],'empty':[b['status'],b['program'],b['sha256']],
             'warm_script_executions':len(a['oracle']),'native':{k:a['native'][k] for k in ('full','link_only')},
             'warm_stock_links':len(a['native']['linkers']),'match':valid(a) and valid(b) and a['sha256']==b['sha256'],
             'inputs':{'build_rs':sha(src/'build.rs'),'tune':env_val,'tracked_files':list(files)}}
        save(out/phase/'compared.json',row);rows[phase]=row
        if not row['match']:wrong.append(phase)
        print('experimental native build-script fixture',role,phase,row['warm'],row['empty'],flush=True)
    save(out/'terminal.json',{'arm':role,'wrong':wrong,'rows':rows})
    shutil.rmtree(work);shutil.rmtree(src)
    return not wrong
