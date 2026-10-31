"""Reopen the signed-to-strict histories, both independent references, all compiler processes and encoded chacha markers."""
import gzip,hashlib,json,re,subprocess,sys
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import observed
H=lambda b:hashlib.sha256(b).hexdigest()
def data(p):return json.loads(p.read_bytes())
def read(p):return gzip.decompress(p.read_bytes())
def same(a,b):assert a==b,(a,b)
def marker(raw):
    """Decode the file table and authenticate the checked compiler marker selected by Cargo."""
    p=0
    def take(n):
        nonlocal p
        out=raw[p:p+n];assert len(out)==n;p+=n;return out
    def number():return int.from_bytes(take(4),'little')
    def vec():return take(number())
    same(take(5),b'\1\0\0\0\xff');assert take(1) in (b'\2',b'\4')
    files=[]
    for _ in range(number()):
        mode=take(1);path=vec();checksum=take(1);assert checksum in (b'\0',b'\1')
        if checksum==b'\1':take(8);vec()
        files.append((mode,path,checksum))
    for _ in range(number()):
        vec();v=take(1);assert v in (b'\0',b'\1')
        if v==b'\1':vec()
    if raw[p:p+4]!=b'LNK1':assert raw[p:p+4] in (b'',b'OBS1');return False
    take(4);i=number();same(files[i],(b'\1',b'/dev/null/ohm-recheck-dependent-links',b'\0'))
    body=raw[:p];digest=take(32)
    try:
        import blake3
        same(blake3.blake3(body).digest(),digest)
    except ImportError:
        same(subprocess.check_output(['b3sum','--no-names'],input=body,text=False).decode().strip(),digest.hex())
    assert raw[p:p+4] in (b'',b'OBS1');return True
def parity(a,b):return all(a.get(k)==b.get(k) for k in ('status','reader','reader_sha256','generated'))
def verify(root):
    proto=data(root/'protocol.json');side=Path(proto['env']['RUSTUP_HOME'])/'toolchains/ohm/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/libutil.so';wild=side.with_name('ld.bfd')
    assert set(proto['cargo'])=={'signed','strict'}
    same([t[2] for t in [proto['cargo']['signed'],proto['cargo']['strict']]],['4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e','035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'])
    same(proto['sdk'],['f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9','dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3','0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'])
    assert not set(proto['env'])&{'RUSTFLAGS','LIBRARY_PATH','LD_PRELOAD','LD_LIBRARY_PATH','CC','CI','GH_TOKEN'}
    obj={p.stem:read(p) for p in (root/'objects').glob('*.gz')};assert all(H(v)==k for k,v in obj.items())
    paths={};phases={};costs={};cause={};enc={};work_roots={}
    allrows=data(root/'complete.json');same(set(allrows),{'83','bad','empty-signed','empty-strict','edit','edit-empty'})
    for group,ledger in allrows.items():
        base=root/group;s=base/'complete.json';same(H(s.read_bytes()),ledger);phases[group]={};costs[group]={};cause[group]={};enc[group]={};work_roots[group]={}
        for name,q in data(s).items():
            d=base/name;same(data(d/'migration.json'),q);r=q['result'];same(data(d/'observation.json'),r);phases[group][name]=r;binary=q['cargo'];same(binary['sha256'],proto['cargo'][binary['role']][2]);paths[binary['role']]=(binary['path'],binary['mtime'])
            code=r['status'];stream=read(d/'cargo.stdout.gz');msgs=list(map(json.loads,stream.splitlines()));same(msgs[-1],{'reason':'build-finished','success':code==0});same(sum(m['reason']=='compiler-artifact' for m in msgs),r['typed'])
            raw=read(d/'exec-and-provider-open.gz');same(H((d/'exec-and-provider-open.gz').read_bytes()),r['trace']);s=observed.search(raw,str(side),str(wild));same(s,r['search'])
            units=[]
            for line in raw.decode().splitlines():
                m=re.search(r'^\S+ (\d+) execve\("([^"]+/rustc)", .*?"--crate-name", "([^"]+)"',line)
                if not m or m[2]!=str(Path(proto['env']['RUSTUP_HOME'])/'toolchains/ohm/bin/rustc') or not line.endswith('= 0') or m[3]=='___':continue
                cached='"-Zlink-only"' in line or '"-Z", "link-only"' in line
                if cached:assert re.search(r'"[^"]+\.rlink"',line)
                units.append((int(m[1]),m[3],'link-only' if cached else 'full'))
            same(sorted([p,n] for p,n,k in units),sorted(r['physical']['rustc']))
            same(s['physical_ld'],[l for p,l in r['physical']['ld']])
            markerlist=[marker(obj[e['sha256']]) for e in q['encoded']];enc[group][name]=sum(markerlist);work_roots[group][name]=q['roots']
            costs[group][name]=dict(full=[n for p,n,k in units if k=='full'],link_only=[n for p,n,k in units if k=='link-only'],wild=s['physical_ld'].count(str(wild)),ld=len(s['physical_ld']),typed=r['typed'],dirty=r['dirty'],encoded_chacha=len(markerlist),authenticated_markers=sum(markerlist))
            cause[group][name]=dict(linker_open=any(z['exe']==str(wild) and z['kind']=='higher' and z['result']>=0 and z['call'] in ('openat','openat2') for z in s['probes']),
                                   generator_open=any('ruff_unicode_names2' in str(z['exe']) and Path(str(z['exe'])).name in ('build_script_build','build-script-build') and z['kind']=='higher' and z['result']>=0 and z['call'] in ('openat','openat2') for z in s['probes']),
                                   linker_system_fallback=any(z['exe']==str(wild) and z['kind']=='fallback' and z['result']>=0 and z['call'] in ('openat','openat2') for z in s['probes']))
            if code==0:
                actual=read(d/'reader-exec.stdout.gz').decode().splitlines();same(actual,r['reader']);assert len(actual)==4 and actual[1]=='Some(0)' and obj[r['reader_sha256']][:4]==b'\x7fELF'
                same(sorted(r['generated']),['generated.rs','generated_alias.rs','generated_phf.rs'])
                alias=obj[r['generated']['generated_alias.rs']];encoded,=re.findall(rb'\(b"NULL", .*?\\u\{(\w{4})\}',alias)
                same(actual[0],f'Some({int(encoded,16)})');assert all(v in obj for v in r['generated'].values())
                if group in ('edit','edit-empty') and name not in ('original','restored'):same(actual[2:],[r'None','Some(10)'])
                else:same(actual[2:],['Some(10)',r'None'])
            else:
                same(code,101);errors=[m['message'] for m in msgs if m['reason']=='compiler-message' and m['message']['level']=='error'];assert errors
                if (group,name)==('edit','invalid'):assert any((e['code'] or {}).get('code')=='E0425' and 'unavailable_ohm_migration_guard' in e['message'] for e in errors)
                else:assert b'linking' in stream and b'libutil.so' in stream and cause[group][name]['linker_open'] and not cause[group][name]['generator_open'],(group,name)
            for item in r['chacha']:
                dep=read(d/(item['sha256']+'.d.gz'));same(H(dep),item['sha256']);assert b'/dev/null/ohm-recheck-dependent-links-v2' not in dep
    same(paths['signed'],paths['strict'])
    for role in ('signed','strict'):
        group='empty-'+role;rows=phases[group];same(set(rows),{'absent','83','47','bad'})
        for name in ['absent','83','47']:
            r=rows[name];same(r['status'],0);same(r['reader'][0],f'Some({0 if name=="absent" else name})')
            if name=='absent':assert cause[group][name]['linker_system_fallback']
            else:assert cause[group][name]['linker_open'] and cause[group][name]['generator_open']
        same(rows['bad']['status'],101)
    for state in ('83','bad'):
        rows=phases[state]
        same(set(rows),{'signed-empty-absent','signed-repeat-absent','signed-poisoned','strict-migration','strict-repeat','strict-repair-absent','strict-repair-repeat'}|({'strict-same-inode-47','strict-same-inode-bad'} if state=='83' else set()))
        same(len({json.dumps(x,sort_keys=True) for x in work_roots[state].values()}),1)
        for k in ['signed-empty-absent','signed-repeat-absent','signed-poisoned']:
            assert parity(rows[k],phases['empty-signed']['absent']);same(enc[state][k],0);assert costs[state][k]['encoded_chacha']>=1
        assert not parity(rows['signed-poisoned'],phases['empty-signed'][state]);same(costs[state]['signed-poisoned']['full'],[]);same(costs[state]['signed-poisoned']['ld'],0)
        for k,target in [('strict-migration',state),('strict-repeat',state),('strict-repair-absent','absent'),('strict-repair-repeat','absent')]+([('strict-same-inode-47','47'),('strict-same-inode-bad','bad')] if state=='83' else []):
            r=rows[k];assert parity(r,phases['empty-strict'][target]),(state,k,target,r.get('reader'))
            assert parity(r,phases['empty-signed'][target]),(state,k,'signed clean disagreement')
            assert costs[state][k]['wild']>=1
            if target not in ('bad','absent'):assert cause[state][k]['linker_open'] and cause[state][k]['generator_open']
            if target!='bad':assert enc[state][k]>=1,(state,k,'no authenticated native-input marker')
        q=data(root/state/'complete.json');s=q['signed-poisoned']['provider']
        same(q['strict-migration']['provider'],s);same(q['strict-repeat']['provider'],s)
        if state=='83':
            for k in ('strict-same-inode-47','strict-same-inode-bad'):
                t=q[k]['provider'];same([s[x] for x in ('dev','ino','size','mtime')],[t[x] for x in ('dev','ino','size','mtime')]);assert t['sha256']!=s['sha256']
    e=phases['edit'];ref=phases['edit-empty']['independent']
    same(set(e),{'original','historical','historical-repeat','invalid','repair-edited','restored'})
    assert all(parity(e[k],ref) for k in ('historical','historical-repeat','repair-edited'))
    assert parity(e['original'],e['restored']) and e['original']['reader_sha256']!=ref['reader_sha256'] and e['original']['generated']['generated_alias.rs']!=ref['generated']['generated_alias.rs']
    assert costs['edit']['historical']['wild']>=1 and 'unicode_names2_generator' in costs['edit']['historical']['full']
    return {'commands':sum(map(len,phases.values())),'compiled_objects':len(obj),'same_path_and_mtime':paths,'cost':costs,'probes':cause,
            'two_poisoned_histories':{st:{n:[r['status'],r.get('reader'),r.get('reader_sha256'),r.get('generated')] for n,r in ss.items()} for st,ss in phases.items()}}
if __name__=='__main__':print(json.dumps(verify(Path(sys.argv[1])),sort_keys=True,indent=2))
