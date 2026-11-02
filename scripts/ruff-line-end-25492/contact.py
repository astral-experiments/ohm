"""Compare complete compiler/link commands and the artifacts offered at each edge."""
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from audit import checked_exec, exec_environment, save, sha

RUN=41460616635
HEAD='5e138b559204afacccdd5dba31bc0c760b8bcfe0'
ART=13150085836
DIGEST='c088eba27ed747cbb719332209dfe801682168cf1b2268831a48afa9a1d4c588'
REF=Path('/home/runner/work/_temp/ruff-db-link-reason/ordinary.zip')
OWNER_SET=set(json.loads((HERE/'ordinary.json').read_text())['phases']['edit']['rustc_roster'])
NS=re.compile(r'(?<=/)v2-([0-9a-f]{16})(?=/|$|[\s\x27])')
TMP=re.compile(r'(?<=/)(?:rustc[A-Za-z0-9]{6}(?=/)|cc[A-Za-z0-9]{6}(?=\.res(?:$|[\s\x27])))')
PROBE=re.compile(r'(?<![a-zA-Z0-9_])autocfg_[0-9a-f]{16}_(\d+)(?=$|[./\s])')
INVOC=re.compile(r'(?<=\.)[a-z0-9]{7}(?=\.rcgu\.(?:o|dwo)(?:$|[\s\x27]))')
CARGO_FDS=re.compile(r'(?P<key>--jobserver-(?:auth|fds)=)(\d+),(\d+)')


def enroll():
    import os
    root=Path(os.environ['RUNNER_TEMP'])/'ruff-db-link-reason'
    assert REF.parent==root
    base='repos/astral-experiments/ohm/actions/'
    def metadata(path):return json.loads(subprocess.check_output(['gh','api',base+path]))
    run=metadata(f'runs/{RUN}');assert run['status']=='completed' and run['conclusion']=='success' and run['head_sha']==HEAD and run['run_attempt']==1
    art,=[a for a in metadata(f'runs/{RUN}/artifacts')['artifacts'] if a['name']=='ruff-line-end-25492-baseline']
    assert art['id']==ART and art['size_in_bytes']==6857620 and art['digest']=='sha256:'+DIGEST and not art['expired']
    with REF.open('xb') as out:subprocess.run(['gh','api',base+f'artifacts/{ART}/zip'],stdout=out,check=True)
    assert sha(REF)==DIGEST
    save(root/'records'/ 'ordinary-reference.json',dict(id=ART,run=RUN,sha256=DIGEST,qa=HEAD))


def canonical(values):
    # Preserve each option, argument, input name, and repeated relationship.
    # Only the host-specific SDK namespace and compiler-owned random temporary
    # directory / GCC resolution-file components can be renamed.
    tmp={}
    def rename(m):
        name=m.group()
        if name not in tmp:tmp[name]=('rustcTMP' if name.startswith('rustc') else 'ccTMP')+str(len(tmp))
        return tmp[name]
    seeds={}
    def invocation(m):
        key=m.group()
        if key not in seeds:seeds[key]='<invocation'+str(len(seeds))+'>'
        return seeds[key]
    return [INVOC.sub(invocation,PROBE.sub(r'autocfg_<uuid>_\1',TMP.sub(rename,NS.sub('v2-<sdk>',v)))) for v in values]


def digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read_member(read,phase,key):return json.loads(read(phase+'/'+key))


def commands(read,phase,*,env=True):
    procs=read_member(read,phase,'processes.json');cs={v['pid']:v for v in procs['compilers']};ls={v['pid']:v for v in procs['wild']}
    found=set();rates={'rustc':[],'wild':[]};cmds={}
    with tarfile.open(fileobj=io.BytesIO(read(phase+'/exec.tar.gz')),mode='r:gz') as tar:
        for member in tar:
            pid=int(member.name.split('.')[1])
            if pid not in cs and pid not in ls:continue
            for line in tar.extractfile(member).read().decode(errors='replace').splitlines():
                event=checked_exec(line)
                if event is None:continue
                exe,a=event
                if pid in cs and exe.endswith('/bin/rustc') and '--crate-name' in a:
                    record=cs[pid];assert record['args']==a
                    typ='rustc';crate=record['crate'];assert not record['link_only']
                    target=next((a[i+1] for i in range(len(a)-1) if a[i]=='--crate-type'),'')
                    owner=canonical([crate,target,*sorted(s for s in a if s.startswith(('feature=','extra-filename=')))])
                    if PROBE.fullmatch(crate):owner+=canonical([a[a.index('--out-dir')+1]])
                elif pid in ls and exe.endswith('/wild-ld/ld.bfd'):
                    path=a[a.index('-o')+1];assert path==ls[pid]['out']
                    typ='wild';owner=canonical([path])
                else:continue
                assert pid not in found;found.add(pid)
                cooked=canonical(a);ident=digest(cooked)
                envs={}
                if env:
                    physical=exec_environment(line)
                    # Cargo jobserver descriptors are assigned by the kernel. Check
                    # both spellings refer to the same pair before normalizing it.
                    for k,v in sorted(physical.items()):
                        if k in ('CARGO_MAKEFLAGS','MAKEFLAGS','MFLAGS'):
                            fds={m.groups()[1:] for m in CARGO_FDS.finditer(v)}
                            assert len(fds)<=1
                            v=CARGO_FDS.sub(r'\g<key><read>,<write>',v)
                        envs[k]=canonical([v])[0]
                rates[typ].append({'owner':owner,'argv':ident,'env':digest(envs) if env else None})
                cmds[(typ,tuple(owner),ident)]=(a,envs)
    assert found==set(cs)|set(ls)
    return {k:sorted(v,key=lambda r:(r['owner'],r['argv'],r['env'] or '')) for k,v in rates.items()},cmds


def compare(reference,actual,phase,folder):
    first,fa=commands(reference,phase);second,sa=commands(actual,phase)
    mismatches={}
    for typ in first:
        if first[typ]==second[typ]:continue
        diffs=[]
        for row in first[typ]:
            if row in second[typ]:continue
            same_owner=[s for s in second[typ] if s['owner']==row['owner']]
            key=(typ,tuple(row['owner']),row['argv'])
            reason={'ordinary':row,'diagnostic':same_owner}
            if len(same_owner)==1 and key in fa:
                other=same_owner[0];left=fa[key];right=sa[(typ,tuple(other['owner']),other['argv'])]
                aa,bb=canonical(left[0]),canonical(right[0]);reason['arity']=[len(aa),len(bb)]
                reason['first_argv_differences']=[[i,u,v] for i,(u,v) in enumerate(zip(aa,bb)) if u!=v][:5]
                reason['env_differences']={k:[left[1].get(k),right[1].get(k)] for k in left[1].keys()|right[1].keys() if left[1].get(k)!=right[1].get(k)}
            diffs.append(reason)
        mismatches[typ]={'ordinary':len(first[typ]),'diagnostic':len(second[typ]),'first_mismatches':diffs[:8]}
    save(folder/'native-roster.json',{'ordinary':first,'diagnostic':second,'mismatches':mismatches})
    return not mismatches


def ar_members(path):
    members=[]
    with path.open('rb') as f:
        assert f.read(8)==b'!<arch>\n',path
        names=b''
        while header:=f.read(60):
            assert len(header)==60 and header[-2:]==b'`\n',path
            name=header[:16].rstrip().decode();size=int(header[48:58])
            if name=='//':
                names=f.read(size); assert len(names)==size
            else:
                if name.startswith('/') and name[1:].isdigit():
                    offset=int(name[1:]);end=names.index(b'/\n',offset);name=names[offset:end].decode()
                else:name=name.rstrip('/') or '/'
                remaining=size;h=hashlib.sha256()
                while remaining:
                    block=f.read(min(remaining,1<<20));assert block,(path,name);h.update(block);remaining-=len(block)
                members.append([name,size,h.hexdigest()])
            if size%2:assert f.read(1)==b'\n'
    return members


def outputs(products,compilers,folder):
    by_path={};artifacts=[]
    for r in products:
        owner=r['target']['name']
        if owner not in OWNER_SET:continue
        stable=[owner,r['target']['kind'],r['features'],r['profile']]
        files=[]
        for f in r['filenames']:
            path=Path(f);row={'path':f,'bytes':path.stat().st_size,'sha256':sha(path)}
            if f.endswith('.rlib'):row['members']=ar_members(path)
            files.append(row);assert f not in by_path;by_path[f]=stable
        artifacts.append({'unit':stable,'files':files})
    consumers=[]
    for r in compilers:
        if r['crate'] not in OWNER_SET:continue
        a=r['args'];used=[]
        for flag,operand in zip(a,a[1:]):
            if flag.startswith('-') and '=' in operand:
                name,path=operand.split('=',1)
                if path in by_path:used.append([flag,name,path])
        consumers.append({'crate':r['crate'],'pid':r['pid'],'externs':used})
    with gzip.open(folder/'delivered.json.gz','wt',compresslevel=3) as f:json.dump({'artifacts':artifacts,'consumer_operands':consumers},f)
    return artifacts


if __name__=='__main__':
    assert sys.argv[1:]==['enroll']
    enroll()
