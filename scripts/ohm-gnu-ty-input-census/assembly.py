"""Keep the compiler input and genuine emitted IR for each repeating AArch64 registry crate."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import census

CRATES={'rustix':'1.1.5','tempfile':'3.27.0','portable_atomic':'1.13.1'}
TEMPLATES=re.compile(rb'\basm(?: [a-z_]+)*\s+"((?:\\[0-9A-Fa-f]{2}|[^"\\]|\\.)*)"\s*,\s*"((?:\\[0-9A-Fa-f]{2}|[^"\\]|\\.)*)"')


def captured():
    argv=sys.argv[1:]
    if '--crate-name' in argv and any(x.startswith('--emit=') for x in argv):
        crate=argv[argv.index('--crate-name')+1]
        if crate in CRATES and '--target' in argv and argv[argv.index('--target')+1]==census.TARGET:
            output=Path(os.environ['ASSEMBLY_RECORDS'])/(crate+'.json')
            census.save(output,{'cwd':os.getcwd(),'argv':argv,'env':dict(os.environ)})
    os.execv(argv[0],argv)


def reemit(root,out,crate,records,expected):
    rec=json.loads((records/(crate+'.json')).read_text())
    original=rec['argv']
    env=rec['env']
    assert Path(original[0]).samefile(Path(os.environ['CENSUS_SDK'])/'bin/rustc')
    assert original[1:]==expected[1:] and not any('incremental=' in x for x in original)
    sources=[v for v in original if v.endswith('/src/lib.rs')]
    assert len(sources)==1 and f"/{crate.replace('_','-')}-{CRATES[crate]}/src/lib.rs" in sources[0]
    assert not any(k in env for k in ('GH_TOKEN','GITHUB_TOKEN','RUSTFLAGS','CI'))
    # The standalone emission runs after the original Cargo process releases its jobserver.
    env={k:v for k,v in env.items() if k not in ('CARGO_MAKEFLAGS','MAKEFLAGS','RUSTC_WRAPPER','ASSEMBLY_RECORDS')}
    dest=root/('ir-'+crate);dest.mkdir();folder=out/crate;folder.mkdir()
    assert len([v for v in original if v.startswith('--emit=')])==1 and original.count('--out-dir')==1
    args=[('--emit=llvm-ir,mir' if v.startswith('--emit=') else v) for v in original[1:]]
    args[args.index('--out-dir')+1]=str(dest)
    r=subprocess.run(['rustc','+ohm',*args],cwd=rec['cwd'],env=env,capture_output=True,timeout=2100)
    census.blob(folder/'stdout.gz',r.stdout);census.blob(folder/'stderr.gz',r.stderr)
    census.save(folder/'replay.json',{'captured':rec,'argv':args,'exit':r.returncode,'source_sha':census.sha(Path(sources[0]))})
    assert r.returncode==0,(crate,r.stderr[-2500:])
    sites=[];inventory={};mir_count=unit_count=0
    for path in sorted(dest.iterdir()):
        assert path.suffix in ('.mir','.ll'),path
        data=path.read_bytes()
        inventory[path.name]=[len(data),census.digest(data)]
        census.blob(folder/(path.name+'.gz'),data)
        if path.suffix=='.mir':
            mir_count+=1;continue
        unit_count+=1;symbol=None
        for idx,line in enumerate(data.splitlines(),1):
            if line.startswith(b'define '):
                name=re.search(rb'@("[^"]+"|[-a-zA-Z0-9_.$]+)\(',line)
                symbol=name[1].decode(errors='replace') if name else None
            if b' asm ' in line or line.startswith(b'module asm '):
                m=TEMPLATES.search(line)
                sites.append({'unit':path.name,'line':idx,'owner':symbol,'template':m[1].decode() if m else None,
                              'constraints':m[2].decode() if m else None,'escaped':line.decode(errors='backslashreplace')})
            if line==b'}':symbol=None
    assert unit_count and mir_count and inventory
    census.save(folder/'sites.json',{'inputs':inventory,'sites':sites})
    counts=collections.Counter(s['template'] for s in sites)
    print(crate,unit_count,'LLVM modules',len(sites),'inline or module asm sites',counts.most_common(12),flush=True)
    return {'units':unit_count,'lines':len(sites),'unclassified':sum(s['template'] is None for s in sites),
            'site_record':census.sha(folder/'sites.json')}


def counter(root,out,env,src,ordinary,prog):
    stats=root/'callgrind';stats.mkdir()
    lib=Path(os.environ['CENSUS_SDK']).resolve()
    command=[str(lib/'bin/cargo'),*census.CLI[2:]]
    prefix=['/usr/bin/valgrind.bin','--tool=callgrind','--trace-children=yes','--separate-threads=no',
            '--cache-sim=no','--branch-sim=no','--collect-jumps=no','--callgrind-out-file='+str(stats/'cg.%p'),'--log-file='+str(stats/'log.%p')]
    before=census.sha(prog)
    measured=subprocess.run([*prefix,*command],cwd=src,env=env,capture_output=True,timeout=3900)
    census.blob(out/'count-stdout.gz',measured.stdout);census.blob(out/'count-stderr.gz',measured.stderr)
    assert measured.returncode==0,measured.stderr[-2500:]
    msgs=list(map(json.loads,measured.stdout.splitlines()))
    assert msgs[-1]=={'reason':'build-finished','success':True}
    listed=[m for m in msgs if m['reason']=='compiler-artifact']
    executable,=[m['executable'] for m in listed if m['profile']['test'] and m['executable'] and m['target']['name']=='ty_project']
    assert len(listed)==304 and Path(executable).samefile(prog) and census.sha(prog)==before
    for name in sorted(census.NEW_TESTS):
        r=subprocess.run(['qemu-aarch64','-L','/usr/aarch64-linux-gnu',str(prog),'--exact',name,'--test-threads=1'],cwd=src/'crates/ty_project',env=env,capture_output=True,timeout=180)
        assert r.returncode==0 and f'test {name} ... ok'.encode() in r.stdout and b'1 passed; 0 failed' in r.stdout
        census.blob(out/('counter-'+name.replace(':','_')+'.gz'),r.stdout)
    profiles=[]
    for f in sorted(stats.glob('cg.*')):
        pid=int(f.suffix[1:]);commands=re.findall(rb'^cmd:\s*(.+)$',f.read_bytes(),re.M)
        assert len(commands)==1
        ir=census.qualify.instructions(f,pid)
        log=stats/f'log.{pid}';reported=re.findall(rb'Collected\s+:\s+([\d,]+)',log.read_bytes())
        assert len(reported)==1 and int(reported[0].replace(b',',b''))==ir
        label=commands[0].decode()
        fields=label.split()
        crate=fields[fields.index('--crate-name')+1] if '--crate-name' in fields else None
        cls=crate if crate else Path(fields[0]).name
        census.blob(out/'profiles'/(f.name+'.gz'),f.read_bytes())
        census.blob(out/'profiles'/(log.name+'.gz'),log.read_bytes())
        profiles.append({'pid':pid,'class':cls,'ir':ir,'command':label})
    expected=sorted(r['crate'] for r in ordinary)
    actual=sorted(r['class'] for r in profiles if ' --crate-name ' in r['command'] and ' --emit' in r['command'])
    assert actual==expected,(actual,expected)
    assert len([p for p in profiles if p['command']==' '.join(command)])==1 and any(x['class'] in ('ld','ld.bfd','ld.lld') for x in profiles)
    census.save(out/'count.json',{'one_unpaired_discovery_observation':True,'argv':prefix+command,'profiles':profiles,'product':before})
    print('One unpaired observed instruction census',[(p['class'],p['ir']) for p in profiles],flush=True)


def main():
    root=Path(os.environ['CENSUS_ROOT']).resolve(strict=True);src=root/'ruff'
    receipts=root/'receipts';prior=json.loads((receipts/'repeat/kernel.json').read_text())
    terminal=json.loads((receipts/'terminal.json').read_text())
    assert not terminal['phases']['repeat']['hard']
    env=json.loads((receipts/'enrolled.json').read_text())['env']
    out=receipts/'assembly';out.mkdir()
    records=out/'recorder';records.mkdir();wrapper=root/'record-asm-input'
    wrapper.write_text('#!/usr/bin/python3\nimport os,sys\nos.execv(sys.executable,[sys.executable,"-IB",'+repr(str(Path(__file__).resolve()))+',*sys.argv[1:]])\n');wrapper.chmod(0o755)
    result=subprocess.run(census.CLI,cwd=src,env={**env,'RUSTC_WRAPPER':str(wrapper),'ASSEMBLY_RECORDS':str(records)},capture_output=True,timeout=1800)
    census.blob(out/'observed-stdout.gz',result.stdout);census.blob(out/'observed-stderr.gz',result.stderr)
    assert result.returncode==0,result.stderr[-2000:]
    messages=list(map(json.loads,result.stdout.splitlines()))
    assert messages[-1]=={'reason':'build-finished','success':True}
    outputs=[m for m in messages if m['reason']=='compiler-artifact']
    prog,=[Path(m['executable']) for m in outputs if m['executable'] and m['profile']['test'] and m['target']['name']=='ty_project']
    assert len(outputs)==304 and set(p.stem for p in records.glob('*.json'))==set(CRATES)
    assert census.sha(prog)==terminal['phases']['repeat']['product']['sha256']
    original={r['crate']:r['argv'] for r in prior['rustcs']}
    overview={name:reemit(root,out,name,records,original[name]) for name in sorted(CRATES)}
    census.save(out/'ir-terminal.json',overview)
    counter(root,out,env,src,prior['rustcs'],prog)


if __name__=='__main__':
    if 'ASSEMBLY_RECORDS' in os.environ:
        captured()
    else:
        main()

