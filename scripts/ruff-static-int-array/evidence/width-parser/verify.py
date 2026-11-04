#!/usr/bin/env python3
"""Reopen the source-bound C7 and C8 software counters and native verdicts offline."""
from collections import Counter
import argparse, gzip, hashlib, json, re, struct, subprocess, tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
def sha(data):
    return hashlib.sha256(data).hexdigest()

def open_store(root):
    summary = json.loads((root / 'decision.json').read_bytes())
    assert sha((root / 'originals.tar.zst').read_bytes()) == '29b02344462ed064ccf6c9bf6964451657ad6556607a39692a4ba3e167518815'
    names = set()
    bodies = {}
    with subprocess.Popen(['zstd','-qdc',str(root/'originals.tar.zst')],stdout=subprocess.PIPE) as z:
        with tarfile.open(fileobj=z.stdout,mode='r|') as tar:
            for member in tar:
                assert member.name not in names
                names.add(member.name)
                if member.isdir():
                    assert member.name == 'objects'
                    continue
                assert member.isfile() and member.size <= 30_000_000
                data = tar.extractfile(member).read()
                if member.name == 'index.json':
                    assert sha(data) == summary['index']
                    index = json.loads(data)
                else:
                    digest = sha(data)
                    assert member.name == 'objects/' + digest
                    bodies[digest] = data
        z.stdout.read()
        assert z.wait() == 0
    assert {x['sha256'] for x in index.values()} == set(bodies)
    assert all(len(bodies[x['sha256']]) == x['size'] for x in index.values())
    return summary,index,{k:bodies[v['sha256']] for k,v in index.items()}

def sections(body):
    """Classify original ELF64 LE section payloads, retaining all full ELF bytes."""
    assert body[:6] == b'\x7fELF\x02\x01'
    shoff, = struct.unpack_from('<Q', body, 40)
    width,count,strings = struct.unpack_from('<HHH', body, 58)
    assert width == 64 and shoff + width*count <= len(body)
    sec = [struct.unpack_from('<IIQQQQIIQQ',body,shoff+width*i) for i in range(count)]
    stroff,strsz = sec[strings][4:6]
    tab = body[stroff:stroff+strsz]
    result = {}
    for name,typ,flags,addr,start,size,link,info,align,entsz in sec:
        label = tab[name:tab.index(0,name)].decode()
        assert label not in result
        if typ == 8:
            payload = b''
        else:
            assert start + size <= len(body)
            payload = body[start:start+size]
        result[label] = [typ,flags,addr,size,link,info,align,entsz,sha(payload)]
    return result

def verify(root):
    s,idx,b = open_store(root)
    def j(name): return json.loads(b[name])
    def ir(name):
        assert re.findall(rb'^events: (.+)$',b[name],re.M) == [b'Ir']
        total, = re.findall(rb'^summary: (\d+)$',b[name],re.M)
        return int(total)
    decision = {'parser_cases':{},'owner_instructions':{},'native':{},'cross_compiler_elf':{}}
    for role in ('c7','c8'):
        r=role+'/'
        cases=j(r+'parser/verified.json')
        assert s['priors'][role]['source'] in cases['rustc']
        assert len(cases['verdicts'])==28
        for name,case in cases['verdicts'].items():
            assert idx[r+'parser/'+name+'.err']['original_sha256'] == case['stderr']
            assert idx[r+'parser/'+name+'.out']['original_sha256'] == case['stdout']
            assert (case['exit']==1) == bool(case.get('spans'))
        errors=[k for k,v in cases['verdicts'].items()if v['exit']]
        assert len(errors)==17 and len([k for k in errors if k.startswith('disabled-')])==5
        decision['parser_cases'][role] = [len(cases['verdicts']),len(errors)]
        for phase,n in [('old',42),('old-first-repeat',0),('old-settled',0),('edit',2),('edited-settled',0)]:
            info=j(r+'check/'+phase+'/result')
            raw=[json.loads(l) for l in b[r+'check/'+phase+'/cargo'].splitlines()]
            products=[a for a in raw if a.get('reason')=='compiler-artifact']
            dirty=sorted(a['target']['name'] for a in products if not a['fresh'])
            assert info['cargo_finished'] and len(dirty)==n and info['dirty']==dirty and raw[-1]['success']
            if phase=='edit': assert dirty==['ruff_formatter','unicode_width']
        costs={}
        for crate in ('unicode_width','ruff_formatter'):
            p=j(r+'price/'+crate+'.json');a=j(r+'kernel/'+crate)
            assert ir(r+'price/'+crate)==p['ir']==s['priors'][role]['prices'][crate]
            assert p['profile']==idx[r+'price/'+crate]['original_sha256'] and sha(b[r+'rmeta/'+crate])==p['output_sha256']
            argv=a['argv'];assert argv[argv.index('--crate-name')+1]==crate and 'metadata' in ','.join(argv)
            costs[crate]=p['ir']
        costs['unicode_names2_rng']=ir(r+'rng/price')
        assert costs['unicode_names2_rng']==s['priors'][role]['rng']
        decision['owner_instructions'][role]=costs
        enabled=j(r+'cfg-enabled/receipt')
        for stage in ('old','edit','clean'):
            v=enabled[stage];pre=r+'cfg-enabled/'+stage+'/'
            assert v['passed']==1 and v['tests']==['tables::tests::test_normalization: test']
            assert sha(b[pre+'native'])==v['elf'] and sha(gzip.decompress(b[pre+'expanded']))==v['expanded']
            assert b'1 passed; 0 failed' in b[pre+'verdict']
        assert enabled['edit']==enabled['clean'] and enabled['old']['elf']!=enabled['edit']['elf']
        bad = j(r+'malformed/receipt')
        for stage in ('first','last'):
            pre=r+'malformed/'+stage+'/'
            assert bad[stage]['exit'] and sha(b[pre+'diagnostics']) == bad[stage]['diagnostics_sha256']
            assert ir(pre+'price')==bad[stage]['ir']
        assert all(sha(b[r+'malformed/'+stage+'/native'])==bad[stage]['elf']==bad['initial']['elf'] for stage in ('initial','repair','empty'))
        native = j(r+'build/receipt')
        for stage in ('old','edit','settled','empty'):
            v=native['receipts'][stage];pre=r+'build/'+stage+'/'
            assert sha(b[pre+'native'])==v['elf'] and sha(b[pre+'output'])==v['verdict']
            assert len(b[pre+'output'])==3*1112064
        first,last=b[r+'build/old/output'],b[r+'build/edit/output']
        changed=[i for i in range(0,len(first),3)if first[i:i+3]!=last[i:i+3]]
        assert len(changed)==197 and sum(first[i]!=last[i]for i in changed)==197
        assert all(first[i+1:i+3]!=last[i+1:i+3] for i in changed)
        assert b[r+'build/edit/native']==b[r+'build/settled/native']==b[r+'build/empty/native']!=b[r+'build/old/native']
        assert b[r+'build/edit/output']==b[r+'build/settled/output']==b[r+'build/empty/output']
        names=j(r+'rng/build')['build']
        for stage in ('build-old','build-edit','build-warm','build-empty'):
            v=j(r+'rng/'+stage+'/summary')
            assert sha(b[r+'rng/'+stage+'/native'])==v['elf']
            assert v['all_names_and_aliases']==names['new_native']==names['old_native']
        assert names['same_product'] is False
        assert b[r+'rng/build-edit/native']==b[r+'rng/build-warm/native']==b[r+'rng/build-empty/native']!=b[r+'rng/build-old/native']
        decision['native'][role]={'scalar_width_changes':len(changed),'rng_names':names['new_native'],'invalid_first_ir':bad['first']['ir'],'invalid_last_ir':bad['last']['ir']}
    for k in b:
        if k.startswith('c7/parser/')and k.endswith(('.out','.err'))or k.startswith('c7/malformed/')and k.endswith('/diagnostics')or k.startswith('c7/build/')and k.endswith('/output'):
            assert b[k]==b['c8'+k[2:]]
    for stage in ('old','edit','clean'):
        assert j('c7/cfg-enabled/receipt')[stage]['expanded']==j('c8/cfg-enabled/receipt')[stage]['expanded']
    for k in ('parser/positive','parser/outside','build/old/native','build/edit/native','cfg-enabled/old/native','cfg-enabled/edit/native','rng/build-old/native','rng/build-edit/native'):
        old,new=b['c7/'+k],b['c8/'+k];a=sections(old);c=sections(new)
        changed=sorted(n for n in a.keys()|c.keys()if a.get(n)!=c.get(n))
        decision['cross_compiler_elf'][k]={'old_complete':sha(old),'new_complete':sha(new),'differing_section_headers_or_bodies':changed,'differing_payloads':sorted(n for n in a.keys()&c.keys() if a[n][-1]!=c[n][-1]),'text_bytes_equal':a['.text'][-1]==c['.text'][-1]}
    return decision

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=HERE,type=Path);args=p.parse_args()
    print(json.dumps(verify(args.root),sort_keys=True,indent=2))
