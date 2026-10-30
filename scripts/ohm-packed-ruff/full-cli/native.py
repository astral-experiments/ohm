"""Verify complete native executables and their behavioral outputs on each branch."""
import gzip
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'harness'))
import cli_oracle
import elf_parts
from omission import publish,require,sha


def run(cmd, env, cwd, out, expect=0, data=b''):
    result=subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,input=data,capture_output=True)
    for suffix,body in (('stdout',result.stdout),('stderr',result.stderr)):
        out.with_suffix('.'+suffix+'.gz').write_bytes(gzip.compress(body,compresslevel=3,mtime=0))
    publish(out.with_suffix('.json.gz'),{'argv':list(map(str,cmd)),'expected':expect,'exit':result.returncode,
            'stdin_sha256':hashlib.sha256(data).hexdigest(),'stdout_sha256':hashlib.sha256(result.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(result.stderr).hexdigest()})
    require(result.returncode==expect,(str(out),expect,result.returncode,result.stderr[-1100:]));return result


def elf(path):
    with path.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
        sections,segments,_,_,digest,size=elf_parts.image(mm)
        executable={n:{k:item[k] for k in ('flags','size','sha256')} for n,item in sections.items() if item['flags']&4}
        loads=[{'flags':s[1],'offset':s[2],'addr':s[3],'filesz':s[5],'memsz':s[6],'sha256':hashlib.sha256(memoryview(mm)[s[2]:s[2]+s[5]]).hexdigest()} for s in segments if s[0]==1 and s[1]&1]
        require('.text' in executable and loads and size>8192,'missing executable sections or load right')
        return {'whole':digest,'size':size,'executable':executable,'loads':loads,'sections':sections}


def preserve(path, desc, bodies, archive):
    bodies.mkdir(exist_ok=True);archive.mkdir(exist_ok=True)
    digest=desc['whole'];file=bodies/digest;compact=archive/(digest+'.zst')
    if not file.exists():
        with path.open('rb') as src,file.open('xb') as dest:shutil.copyfileobj(src,dest,2**20)
        file.chmod(0o444);require(sha(file)==digest and path.stat().st_size==file.stat().st_size,'incorrect retained native reference')
        with compact.open('xb') as out:subprocess.run(['zstd','-1','-T1','--quiet','--stdout',file],stdout=out,check=True)
        child=subprocess.Popen(['zstd','-dcq',compact],stdout=subprocess.PIPE)
        with child.stdout as decoded:check=hashlib.file_digest(decoded,'sha256').hexdigest()
        require(child.wait()==0 and check==digest,'compressed native reference mismatch')
    require(file.stat().st_size==desc['size'] and compact.is_file(),'missing whole native body')


def same_file(path, observed, expected, bodies, where):
    base=bodies/expected['whole'];require(base.is_file() and not base.is_symlink(),'no independent clean native body')
    matched=observed['whole']==expected['whole'] and observed['size']==expected['size'] and subprocess.run(['cmp','--silent','--',base,path]).returncode==0
    if not matched:
        with (where/(path.name+'-unexpected-'+observed['whole']+'.zst')).open('xb') as out:subprocess.run(['zstd','-1','-T1','--quiet','--stdout',path],stdout=out,check=True)
        raise RuntimeError(('complete native file differs from own empty reference',path,observed['whole'],expected['whole']))
    require(observed==expected,'different ELF record for equal complete bytes')


def fstring(cli, env, repo, out):
    common=['check','--isolated','--no-cache','--select','F541','--output-format','json','--stdin-filename','branch_fstring.py','-']
    valid=b'def labels(items):\n    return [f"{n}:{item!r:>4}" for n, item in enumerate(items)]\n'
    plain=b'def label():\n    return f"literal"\n'
    bad=b'def label(item):\n    return f"{item"\n'
    results={}
    def call(label,args,stdin,code):
        p=run([cli,*args],env,repo,out/label,code,stdin);results[label]=[p.returncode,hashlib.sha256(p.stdout).hexdigest(),hashlib.sha256(p.stderr).hexdigest()];return p.stdout
    require(json.loads(call('fstring-valid',common,valid,0))==[],'formatted item flagged')
    diagnostic=json.loads(call('fstring-warning',common,plain,1));require(len(diagnostic)==1 and diagnostic[0]['code']=='F541' and diagnostic[0]['fix'],'expected F541 fix')
    fixed=call('fstring-fix',['check','--isolated','--no-cache','--select','F541','--fix','--exit-non-zero-on-fix','--stdin-filename','branch_fstring.py','-'],plain,1)
    require(fixed==plain.replace(b'f"literal"',b'"literal"') and json.loads(call('fstring-recheck',common,fixed,0))==[],'f-string fix did not round trip')
    invalid=json.loads(call('fstring-invalid',common,bad,1));require(any('invalid-syntax'==str(l.get('code')).lower() or 'syntax' in str(l.get('message')).lower() for l in invalid),'malformed f-string accepted')
    formatted=call('fstring-format',['format','--isolated','--no-cache','--stdin-filename','branch_fstring.py','-'],valid,0)
    require(formatted==valid,'unexpected valid f-string formatting');return results


def observed(rows, branch, revision, env, root, repo, work, out):
    artifacts=[r for r in rows if r.get('reason')=='compiler-artifact'];bins=[Path(m['executable']) for m in artifacts if m['target']['name']=='ruff' and m['target']['kind']==['bin'] and m['executable']]
    require(len(bins)==1 and bins[0].samefile(work/'target/debug/ruff'),'incorrect Cargo executable')
    cli=bins[0];verdict=cli_oracle.cli_checks(out,cli,env,repo,revision);fv=fstring(cli,env,repo,out)
    extern=[]
    for name in ('ruff_python_ast','ruff_python_parser'):
        libs=[Path(f) for m in artifacts if m['target']['name']==name and 'lib' in m['target']['kind'] for f in m['filenames'] if f.endswith('.rlib')];require(len(libs)==1,('missing native reader input',name));extern+=['--extern',f'{name}={libs[0]}']
    dirs=sorted({f.parent for loc in ('target','build') for pat in ('*.rlib','*.so') for f in (work/loc).rglob(pat)})
    for path in dirs:extern+=['-L','dependency='+str(path)]
    for path in sorted({m['out_dir'] for m in rows if m.get('out_dir')}):extern+=['-L','native='+path]
    scratch=root/'full-cli-reader';scratch.mkdir(exist_ok=True);reader=scratch/'reader';consumer=root/'harness/consumer.rs'
    require(sha(consumer)=='69b71457fca1ee4b9594c733aea2f597bac93d2dfce2c3432e76fbe50ec5e2a7','different historical reader')
    run(['rustc','+ohm','--edition=2024','--crate-name','ohm_branch_reader',consumer,*extern,'-o',reader],env,repo,out/'reader-compile')
    want=64 if branch=='A' else 56;actual=run([reader],env,repo,out/'reader-run').stdout.decode().strip();require(actual==f'Expr={want} valid=1 rejected','wrong branch-specific AST reader')
    for layout in (64,56):
        code=scratch/'layout.rs';code.write_text(f'use ruff_python_ast::Expr;\nconst _: [(); {layout}] = [(); std::mem::size_of::<Expr>()];\npub fn check() {{ let _ = ruff_python_parser::parse_module("x = 1"); }}\n')
        p=run(['rustc','+ohm','--edition=2024','--crate-type=lib','--emit=metadata','--error-format=json',code,*extern,'-o',scratch/'layout.rmeta'],env,repo,out/f'layout-{layout}',int(layout!=want))
        if layout!=want:require(any(m.get('code') and m['code']['code']=='E0308' for m in map(json.loads,p.stderr.splitlines())),'contradictory type check did not reject')
    data={'branch':branch,'source':revision,'cli':elf(cli),'reader':elf(reader),'typed':actual,'cli_cases':verdict,'fstring_cases':fv}
    publish(out/'native.json.gz',data);return data,{'cli':cli,'reader':reader}
