"""Link and execute the authentic PyPI/Pyx parser witness against Cargo's same-revision native products."""
from pathlib import Path
import subprocess
import core as c
import history
m=c.m
def run(at,rev):
    at.mkdir();state=history.state(rev);target=m.ROOT/'behavior'
    argv=[str(m.SDK/'bin/cargo'),'build','-p','uv-client','--locked','--offline','-j8','--message-format=json']
    env=m.ENV|{'CARGO_TARGET_DIR':str(target)}
    with (at/'cargo.jsonl').open('xb')as so,(at/'cargo.stderr').open('xb')as se:
        subprocess.run(argv,cwd=m.SRC,env=env,stdout=so,stderr=se,timeout=1500,check=True)
    import json
    rows=[json.loads(x)for x in (at/'cargo.jsonl').read_bytes().splitlines()];c.guard(rows[-1]=={'reason':'build-finished','success':True},'fixture build')
    args=[str(m.RUSTC),'--edition=2024',str(c.HERE/'witness.rs'),'-o',str(at/'probe')];selected={};libs=set()
    for row in rows:
        if row['reason']!='compiler-artifact':continue
        name=row['target']['name']
        for n in row['filenames']:
            p=Path(n);c.guard(p.resolve()==p and p.is_relative_to(target)and p.is_file(),'foreign native Cargo fixture product');libs.add(p.parent)
            if name in ('uv_pypi_types','serde_json')and p.suffix in ('.rmeta','.rlib'):
                choice=selected.setdefault(name,{})
                c.guard(p.suffix not in choice,('duplicate Cargo extern',name,p.suffix));choice[p.suffix]=p
    c.guard(set(selected)=={'uv_pypi_types','serde_json'}and all(set(v)=={'.rlib','.rmeta'}for v in selected.values()),'real four Cargo externs')
    for name,formats in sorted(selected.items()):
        for p in formats.values():args.extend(['--extern',name+'='+str(p)])
    for p in sorted(libs):args.extend(['-L','dependency='+str(p)])
    with (at/'rustc.stderr').open('xb')as se:subprocess.run(args,cwd=m.SRC,env=env,stderr=se,timeout=120,check=True)
    proc=subprocess.run([at/'probe'],cwd=m.SRC,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True)
    (at/'probe.stdout').write_bytes(proc.stdout);(at/'probe.stderr').write_bytes(proc.stderr)
    c.guard(proc.stdout==b'PyPI and Pyx parsed three files and agreed on interning and invalid inputs\n'and proc.stderr==b''and history.state(rev)==state,'native parser or source changed')
    m.save(at/'witness.json',{'exact':True,'state':state,'fixture_sha256':m.filesha(c.HERE/'witness.rs'),'cargo_argv':argv,'rustc_argv':args,
        'output_sha256':m.digest(proc.stdout),'inputs':{n:{f:{'path':str(p.relative_to(target)),'sha256':m.filesha(p)}for f,p in q.items()}for n,q in selected.items()}})
    # Product digests and the original command are retained. The executable has already run.
    (at/'probe').unlink()
