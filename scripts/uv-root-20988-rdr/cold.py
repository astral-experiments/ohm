"""Admit complete cold compiler argv from independent unwrapped kernel execs on both actual revisions."""
from pathlib import Path
import gzip, hashlib, json, os, subprocess, sys
import common as c
m=c.m
import compiler_observer as kernel

def bounded_kernel(source):
    text=source.read_bytes();before=b'assert len(rows)<20000 and pid>0'
    m.guard(m.filesha(source)=='59cc6de44340553eccb73dca6c6c22e253bbbda6aaebe0d3dc9c847d5ed65fca' and text.count(before)==1,'unexpected immutable kernel source')
    return text.replace(before,b'assert len(rows)<500000 and pid>0')

def cargo_spawns(events,root_file):
    # A clone or fork inherits its caller's executable until a successful exec.
    # Keep true Cargo-spawned rustcs separate from metadata probes launched by build scripts.
    program={};direct=set()
    for row in events['events']:
        pid,status=row[:2]
        if not isinstance(status,int) or len(row)<3:continue
        tag=status>>16;old=row[2]
        if tag in (1,2,3):
            program[old]=program.get(pid)
        elif tag==4:
            if program.get(old,program.get(pid))==root_file:direct.add(pid)
            program[pid]=row[3]['file']
    return direct

def compare(marked,execs,root_pid,selected_file,root,expected_targets,direct):
    selected=[]
    for im in execs['images']:
        a=im.get('argv',[])
        if im['file']!=selected_file and Path(im['exe']).name!='rustc' and (not a or Path(a[0]).name!='rustc'):continue
        m.guard(a and a[0]==im['exe']==str(m.RUSTC) and im['file']==selected_file and im['pid']in execs['exits'],'foreign compiler or missing exit')
        if im['pid']in direct and '--crate-name'in a and '--out-dir'in a:
            m.guard(execs['exits'][im['pid']]==0,'unsuccessful Cargo-owned compiler')
            selected.append({'pid':im['pid'],'argv':a,'name':a[a.index('--crate-name')+1]})
    need=list(sorted((x['argv']for x in marked)))
    got=list(sorted((x['argv']for x in selected)))
    scopes={}
    for n in expected_targets:
        full,=[x for x in selected if x['name']==n and 'lib'==x['argv'][x['argv'].index('--crate-type')+1] and f'crates/{n.replace("_","-")}/src/lib.rs'in x['argv']]
        obs,=[x for x in marked if x['name']==n and x['marked']]
        scopes[n]={'unwrapped_pid':full['pid'],'marked_pid':obs['pid'],'all_tokens_identical':full['argv']==obs['argv'],
                   'unwrapped_argv':full['argv'],'marked_argv':obs['argv']}
    return {'kernel_root_pid':root_pid,'marked_count':len(marked),'unwrapped_count':len(selected),'identical_entire_compiler_multiset':need==got,'selected':scopes}

def prove(out,state,mark,shape,panel,role):
    path=out/('unwrapped-kernel-cold-'+state);path.mkdir()
    c.capacity(path,'begin',c.P['capacity_after_gib'])
    src=kernel.CAP;code=bounded_kernel(src);actual=path/'exec-events-source.py';actual.write_bytes(code)
    m.guard(c.P['cold_admission']['max_exec_rows']==500000 and c.P['cold_admission']['max_kernel_bytes']==192*(1<<20),'audited cold caps')
    f=path/'launch.json';compiler_file=kernel.k.file_id(m.RUSTC)
    m.save(f,{'command':m.ARGS,'environment':m.ENV,'cwd':str(m.SRC),'role':role,'score':False,'source':m.history()[0],
              'cargo_file':kernel.k.file_id(Path(m.ARGS[0])),'compiler_file':compiler_file,'original_kernel_sha256':m.filesha(src),'bounded_kernel_sha256':m.filesha(actual)})
    subprocess.run([sys.executable,'-ISB',actual,f],env={'PATH':'/usr/bin:/bin','LC_ALL':'C'},timeout=1800,check=True)
    raw=path/'kernel-events.json';m.guard(raw.is_file() and 0<raw.stat().st_size<=c.P['cold_admission']['max_kernel_bytes'],'bounded complete journal')
    events=m.read(raw);tree=kernel.k.decode(events);r=tree['root'];root=tree['images'][0]
    m.guard(root['pid']==r and root['argv']==m.ARGS and root['exe']==m.ARGS[0] and root['file']==kernel.k.file_id(Path(m.ARGS[0])) and tree['exits'][r]==0,'unaltered native cold root')
    with gzip.open(out/mark/'all-compiler-processes.json.gz','rb')as z:marked=json.load(z)
    cmp=compare(marked,tree,r,compiler_file,root,c.P['targets'],cargo_spawns(events,root['file']));m.save(path/'all-argv-comparison.json',cmp)
    products=panel.inventory(path,shape);marked_inv=m.read(out/mark/'raw-inventory.json');m.guard(products.keys()==marked_inv.keys()==shape[1].keys(),'complete native 70 products')
    cm={'entire_cold_argv_multiset_and_both_selected':cmp['identical_entire_compiler_multiset']and all(v['all_tokens_identical']for v in cmp['selected'].values()),
        'marked_count':cmp['marked_count'],'unwrapped_count':cmp['unwrapped_count'],'native_result':0,'kernel_events':len(events['events']),
        'raw_product_differences':[k for k in products if products[k]!=marked_inv[k]]}
    m.save(path/'disposition.json',cm)
    m.guard(cm['entire_cold_argv_multiset_and_both_selected'],'complete original cold argv differ; raw data retained')
    return cm
