"""Reopen the Cargo diagnostics, archive bytes, driver commands and native client outputs."""
import hashlib,json,re,subprocess,sys
from pathlib import Path
root=Path(sys.argv[2]).resolve()
run=int(sys.argv[1])
read=lambda file:json.loads(file.read_bytes())
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def checked_archive(file,record):
    data=file.read_bytes();assert sha(data)==record['raw']
    listing=subprocess.check_output(['ar','t',file]).splitlines()
    assert b'lib.rmeta' in listing
    native={}
    for name in listing:
        if not name.endswith(b'.rcgu.o'):continue
        match=re.fullmatch(rb'(green_native_stub-[0-9a-z]+\.[a-z0-9]+)(?:\.([0-9a-z]{7}))?(\.rcgu\.o)',name)
        assert match and data.count(name)>0
        canonical=match[1]+b'.0000000'+match[3] if match[2] else name;assert canonical not in native
        payload=subprocess.check_output(['ar','p',file,name.decode()])
        native[canonical]=sha(payload)
        data=data.replace(name,canonical)
    assert native and sha(data)==record['canonical']
    return native
records={}
for host in ['x86_64-unknown-linux-gnu','aarch64-apple-darwin']:
    folder=root/f'integrated-release-verdicts-{host}-{run}'
    bundle=read(folder/'green-stub.json')
    assert len(bundle)==8 and not list(folder.glob('stub-*/failure.txt'))
    outcomes={};count=0
    for role in ['signed','fixed']:
        for flavor in ['rlib','dylib','default','explicit']:
            label=f'stub-{role}-{flavor}';case=folder/label
            result=bundle[label]
            assert result==read(case/'verified.json')
            bad=role=='signed' and flavor=='explicit'
            if flavor in ['rlib','dylib']:
                for step in ['cold','warm','warm-again']:
                    error=(case/(step+'.stderr')).read_bytes()
                    assert error.decode()==result[step]['stderr']
                    expected=role=='signed'and step!='cold'
                    assert result[step]['rc']==int(expected)
                    assert (b'failed to create encoded metadata from file'in error)==expected
                    count+=1
                if role=='fixed':
                    assert (case/'execute.stdout').read_bytes()==b'17\n'and result['execute']=='17\n'
                    assert not (case/'consume.stderr').read_bytes() and not (case/'execute.stderr').read_bytes()
                    count+=2
                outcomes[label]={k:v['rc']for k,v in result.items()if isinstance(v,dict)}
                continue
            steps=result['steps']
            expected={'cold','unchanged','missing-product','cold-before-input-edit','fresh-before-input-edit','real-build-script-input-edit','cold-binary','real-native-edit','edited-binary','invalid','independent-empty','clean-binary'}
            if not bad:expected|={'repair','repaired-binary'}
            assert set(steps)==expected and result['missing_paths']
            for step,receipt in steps.items():
                stdout=(case/(step+'.stdout')).read_bytes();stderr=(case/(step+'.stderr')).read_bytes()
                if step.endswith('-binary'):
                    assert (stdout.decode(),stderr.decode())==(receipt['stdout'],receipt['stderr'])
                    if receipt['rc']==101:assert bad and b'failed to create encoded metadata from file' in stderr
                    else:assert receipt['rc']==0 and stdout==(b'17\n'if step=='cold-binary'else b'29\n')
                else:
                    messages=[json.loads(l)for l in stdout.splitlines()if l.startswith(b'{')]
                    artifacts=[m for m in messages if m['reason']=='compiler-artifact'and m['target']['name']=='green_native_stub'and m['target']['kind']==['lib']]
                    errors=[m['message']for m in messages if m['reason']=='compiler-message'and m['message']['level']=='error']
                    argv=[line for line in stderr.decode().splitlines()if 'Running 'in line and '--crate-name green_native_stub 'in line]
                    assert argv==receipt['drivers'] and artifacts==receipt['artifacts'] and errors==receipt['errors']
                    was_fresh=step in ['unchanged','fresh-before-input-edit']
                    assert len(argv)==int(not was_fresh)
                    if argv:assert 'incremental='in argv[0]and ('embed-metadata=no'in argv[0])==(flavor=='explicit')
                    rejects=(step=='invalid' or bad and step in ['real-build-script-input-edit','missing-product'])
                    assert receipt['rc']==(101 if rejects else 0)and messages[-1]['reason']=='build-finished'and messages[-1]['success']==(not rejects)
                    if step=='invalid':assert any(e.get('code') and e['code']['code']=='E0308'for e in errors)
                    elif rejects:assert any('failed to create encoded metadata from file'in e['message'] for e in errors)
                    else:assert len(artifacts)==1 and artifacts[0]['fresh']==was_fresh and not errors
                    if step=='real-build-script-input-edit':assert any(m['reason']=='build-script-executed'and ['GREEN_STUB_INPUT','changed']in m['env']for m in messages)
                count+=1
            edit_record=result['new_archive'];empty_record=result['empty_archive']
            native=checked_archive(case/'edited.rlib',edit_record)
            assert checked_archive(case/'empty.rlib',empty_record)==native and edit_record['canonical']==empty_record['canonical']
            if not bad:
                raw=(case/'repaired.rlib').read_bytes()
                listed=subprocess.check_output(['ar','t',case/'repaired.rlib']).splitlines()
                for n in listed:
                    m=re.fullmatch(rb'(green_native_stub-[0-9a-z]+\.[a-z0-9]+)(?:\.([0-9a-z]{7}))?(\.rcgu\.o)',n)
                    if m and m[2]:raw=raw.replace(n,m[1]+b'.0000000'+m[3])
                assert sha(raw)==edit_record['canonical'] and checked_archive(case/'repaired.rlib', {'raw': sha((case/'repaired.rlib').read_bytes()),'canonical': sha(raw)})==native
            outcomes[label]={k:v['rc']for k,v in steps.items()}
    records[host]={'count':count,'cases':outcomes}
    assert count==70,count
    print(host,count,'stub boundary commands')
(root/'reopened-stubs.json').write_text(json.dumps(records,indent=2)+'\n')
