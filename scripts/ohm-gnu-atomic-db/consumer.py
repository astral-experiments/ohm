"""Use the exact external rlib and its dependency search paths to compile an independent caller."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'ohm-gnu-ty-input-census'))
import census

def args_from_training(kernel,src):
    rows=[r for r in kernel['rustcs'] if r['crate']=='ruff_db' and not r['link_only'] and '--test' not in r['argv']]
    root,=rows
    args=root['argv']
    external={x.split('=',1)[0]:x.split('=',1)[1] for x in census.flags(args,'--extern') if '=' in x}
    chosen={}
    for name in ('ruff_python_ast','salsa'):
        metadata=Path(external[name])
        archive=metadata.with_suffix('.rlib')
        assert metadata.suffix=='.rmeta' and metadata.is_file() and archive.is_file(),(name,metadata,archive)
        chosen[name]=[str(metadata),str(archive)]
    out_dir,=census.flags(args,'--out-dir')
    suffix,=[x.split('=',1)[1] for x in census.flags(args,'-C') if x.startswith('extra-filename=')]
    library=Path(out_dir)/('libruff_db'+suffix+'.rlib')
    assert library.is_file() and library.with_suffix('.rmeta').is_file(),library
    search=list(census.flags(args,'-L'))
    # Ohm may keep each unit's outputs in a private directory. The standard Cargo command
    # that produced the library is authoritative about which search paths are required.
    return {'external':chosen,'search':search,'root':str(library)}

def run(external,archive,env,src,dest,old=False):
    dest.mkdir()
    caller=src.parent/'downstream.rs'
    if not caller.is_file():shutil.copyfile(HERE/'consumer.rs',caller)
    assert census.sha(caller)==census.sha(HERE/'consumer.rs')
    exe=src.parent/'qa-atomic-consumer'
    cli=['rustc','+ohm','--edition','2024','--crate-name','qa_atomic_subscriber','--target',census.TARGET,
         '-C','linker=/usr/bin/aarch64-linux-gnu-gcc','-C','debuginfo=0','-C','opt-level=1',
         '--extern','ruff_db='+str(archive)]
    local=Path(external['root'])
    assert local.samefile(archive) or census.sha(local)==census.sha(archive)
    cli.extend(['--extern','ruff_db='+str(local.with_suffix('.rmeta'))])
    for name,components in external['external'].items():
        for path in components:
            assert Path(path).is_file(),path
            cli.extend(['--extern',name+'='+path])
    for path in external['search']:cli.extend(['-L',path])
    cmd=[*cli,caller,'-o',exe]
    p=subprocess.run(cmd,cwd=src,env=env,capture_output=True,timeout=270)
    census.blob(dest/'rustc.stdout.gz',p.stdout)
    census.blob(dest/'rustc.stderr.gz',p.stderr)
    census.save(dest/'compile.json',{'argv':list(map(str,cmd)),'exit':p.returncode,'archive_sha':census.sha(archive),
                                     'root_metadata':census.sha(local.with_suffix('.rmeta')),
                                     'deps':{n:[census.sha(Path(p)) for p in paths] for n,paths in external['external'].items()}})
    assert p.returncode==0,p.stderr.decode(errors='replace')[-2400:]
    exercise={}
    for count in (1,65):
        for label in (['valid'] if old else ['valid','past-end']):
            args=[str(count),*([label] if label=='past-end' else [])]
            q=subprocess.run(['qemu-aarch64','-L','/usr/aarch64-linux-gnu',exe,*args],
                             cwd=src,env=env,capture_output=True,timeout=180)
            expected=f'read {count} distinct packed statements\n'
            if label=='past-end':expected+=f'index out of bounds: the len is {count} but the index is {count}\n'
            census.blob(dest/(str(count)+'-'+label+'.stdout.gz'),q.stdout)
            census.blob(dest/(str(count)+'-'+label+'.stderr.gz'),q.stderr)
            assert q.returncode==0 and q.stdout==expected.encode(),(args,q.returncode,q.stdout,q.stderr[-900:])
            exercise[str(count)+'-'+label]=expected.splitlines()
    reported={'elf':census.sha(exe),'bytes':exe.stat().st_size,'verdicts':exercise}
    census.save(dest/'result.json',reported)
    return reported
