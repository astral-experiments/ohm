"""Screen unmodified Ruff CLI builds on a historical PLE0643 false-positive fix."""
import collections
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import census as runner

OLD='02c02172ceae316dac14a7657d9c85fa8bb1c3ca'
NEW='193984681ef7185c90b548c27b0ac6326908f2ec'
TREES={OLD:'5f59a731d262bb142782a1333d99e894fb1b1cee',NEW:'df36660b9ba5936fbffd96197b0c828e9e5f68c6'}
LOCK='a049c8963abf121b242ebab5481739a33c2cf1d2bbc04b085d60e2e6d52a0b13'
RULE='crates/ruff_linter/src/rules/pylint/rules/potential_index_error.rs'
FILES=['crates/ruff_linter/resources/test/fixtures/pylint/potential_index_error.py',RULE]
CLI=['cargo','+ohm','build','-p','ruff','--bin','ruff','--target',runner.TARGET,'--locked','--offline','-j4','--message-format=json']
PROBES={
    'starred':(b'a = (1, 2, 3)\nprint((*a, 9)[2])\n',[('PLE0643',2)],[]),
    'bounds':(b'print([1, 2][9])\n',[('PLE0643',1)],[('PLE0643',1)]),
    'valid':(b'print([1, 2][0])\n',[],[])}


def cli_product(exe,old,dest,src,env):
    with exe.open('rb') as f:head=f.read(20)
    assert head[:7]==bytes.fromhex('7f454c46020101') and head[18:20]==b'\xb7\x00'
    verdicts={}
    for name,(source,before,after) in PROBES.items():
        args=['qemu-aarch64','-L','/usr/aarch64-linux-gnu',str(exe),'check','--isolated','--no-cache','--select','PLE0643','--output-format','json','--stdin-filename','qa.py','-']
        run=subprocess.run(args,cwd=src,env=env,input=source,capture_output=True,timeout=300)
        runner.blob(dest/(name+'-stdout.gz'),run.stdout);runner.blob(dest/(name+'-stderr.gz'),run.stderr)
        runner.save(dest/(name+'-cmd.json'),{'argv':args,'source':source.decode(),'exit':run.returncode})
        diagnostics=[(d['code'],d['location']['row']) for d in json.loads(run.stdout)]
        expected=before if old else after
        assert diagnostics==expected and run.returncode==int(bool(expected)),(name,run.stderr,diagnostics)
        verdicts[name]=diagnostics
    with exe.open('rb') as f:
        header=f.read(64)
        offset,=struct.unpack_from('<Q',header,40)
        size,count,names=struct.unpack_from('<HHH',header,58)
        assert size==64 and 0<names<count
        f.seek(offset)
        sections=[struct.unpack('<IIQQQQIIQQ',f.read(size)) for _ in range(count)]
        f.seek(sections[names][4]);strings=f.read(sections[names][5])
        code,=[r for r in sections if strings[r[0]:].split(b'\0',1)[0]==b'.text']
        assert code[5]>0;f.seek(code[4]);text=hashlib.sha256(f.read(code[5])).hexdigest()
    return {'sha256':runner.sha(exe),'bytes':exe.stat().st_size,'text_sha':text,'verdicts':verdicts}


def main():
    work,out,src,env=runner.acquire(OLD,NEW,TREES,LOCK,FILES,CLI)
    current={};phases={};root_names=set()
    for phase in ('cold','edit','repeat','invalid','repair','empty-new'):
        if phase=='edit':
            runner.command(['git','restore','--source',NEW,'--staged','--worktree','--','.'],src,env)
        if phase=='invalid':
            with (src/RULE).open('a') as f:f.write('\nconst _: usize = OHM_RUFF_PLE0643_INVALID_EDIT;\n')
        if phase=='repair':
            runner.command(['git','restore','--worktree','--',RULE],src,env)
        if phase=='empty-new':
            for directory in ('target','shared'):
                (work/directory).rename(work/('saved-original-'+directory))
                assert not (work/directory).exists()
            current={}
        rev=OLD if phase=='cold' else NEW
        assert runner.command(['git','write-tree'],src,env)==TREES[rev] and runner.sha(src/'Cargo.lock')==LOCK
        assert runner.command(['git','diff','--name-only'],src,env).splitlines()==([RULE] if phase=='invalid' else [])
        dest,messages,kernel=runner.trace_build(phase,work,out,src,env,CLI,101 if phase=='invalid' else 0)
        units=[m for m in messages if m['reason']=='compiler-artifact']
        if phase=='invalid':
            assert any((m.get('message',{}).get('code') or {}).get('code')=='E0425' and 'OHM_RUFF_PLE0643_INVALID_EDIT' in m['message']['rendered'] for m in messages)
            phases[phase]={'diagnostic':'E0425'}
            continue
        owners=collections.defaultdict(set)
        for m in units:owners[m['target']['name'].replace('-','_')].add(m['target']['src_path'])
        active=[]
        for compiler in kernel['rustcs']:
            key,row=runner.describe(compiler,src,(work/'target',work/'shared'),out,owners)
            active.append(row)
            if not row['link_only']:current[key]=row
        locals=[r for r in current.values() if r['local'] and r['target']==[runner.TARGET] and r['incremental']]
        assert any(r['crate']=='ruff_linter' for r in locals) and all(r['marker']!='unresolved' for r in locals)
        hard=[r['crate'] for r in locals if r['marker']=='hard' and r['llvm_lto_off'] and r['ohm_check']]
        root,=[m for m in units if m['target']['name']=='ruff' and m['target']['kind']==['bin'] and m['executable']]
        exe=Path(root['executable']).resolve(strict=True)
        for proc in kernel['rustcs']:
            args=proc['argv']
            if proc['crate']=='ruff' and 'bin' in runner.flags(args,'--crate-type'):
                extra=[x.removeprefix('extra-filename=') for x in runner.flags(args,'-C') if x.startswith('extra-filename=')]
                assert len(extra)<=1;root_names.add('ruff'+''.join(extra))
        real=[]
        for event in kernel['link_tools']:
            if Path(event['path']).name not in ('ld','ld.bfd','ld.lld','rust-lld','wild'):continue
            for path in runner.flags(event['argv'],'-o'):
                f=Path(path)
                if f.is_file() and (f.samefile(exe) or (f.name in root_names and f.stat().st_size==exe.stat().st_size and runner.sha(f)==runner.sha(exe))):real.append(event['pid'])
        if phase in ('cold','edit','empty-new'):assert len(real)==1,(phase,exe,real)
        product=cli_product(exe,phase=='cold',dest,src,env)
        runner.save(dest/'census.json',{'current_local_incremental':locals,'emitted':active,'eligible_hard':hard,'product':product,'physical_root_links':real,'typed':len(units)})
        phases[phase]={'local_units':len(locals),'hard':hard,'full':[r['crate'] for r in active if not r['link_only']],
                       'link_only':[r['crate'] for r in active if r['link_only']],'root_links':len(real),'product':product}
        print(phase,'full',len(phases[phase]['full']),'link-only',len(phases[phase]['link_only']),'eligible',hard,'native links',len(real),'Ruff verdicts',product['verdicts'],flush=True)
    assert phases['edit']['product']['sha256']!=phases['cold']['product']['sha256']
    empty=phases['empty-new']['product']
    for phase in ('edit','repeat','repair'):
        got=phases[phase]['product']
        assert got['verdicts']==empty['verdicts']
        phases[phase]['matches_empty']={key:got[key]==empty[key] for key in ('sha256','text_sha')}
    runner.save(out/'terminal.json',{'untimed':True,'phases':phases})


if __name__=='__main__':main()

