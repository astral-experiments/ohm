"""Check the unmodified signed Cargo's native commands, mount identities and sentinel custody."""
import gzip
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
HEAD='d0721ec2039f5c466d60af2f61dd751587821bfb'
ZIP='bccba27e2aa21a540000cb4b894107b0b57d6757415c4d5ca976eea4d58835ba'
SIGNED='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
def sha(b):return hashlib.sha256(b).hexdigest()
def main(path):
    assert len(path.read_bytes())==22720 and sha(path.read_bytes())==ZIP
    with zipfile.ZipFile(path) as z:
        assert len(z.namelist())==len(set(z.namelist()))==45 and z.testzip() is None
        j=lambda n:json.loads(z.read(n+'.json'))
        take=lambda stem,n:gzip.decompress(z.read('packet/'+stem+'/'+n+'.gz'))
        fact=j('packet/result');outer=j('packet/outer');isolate=j('packet/isolation');cases=fact['results']
        assert outer['qa']==HEAD and outer['exit']==0 and not outer['mounts_before'] and not outer['mounts_after']
        assert outer['ns_before']==outer['ns_after']==isolate['parent_ns']!=isolate['inner_ns'] and not fact['mounts_remaining'] and not fact['issues']
        assert isolate['signed_runtime']['sha256']==outer['cargo_sha']==j('receipts/21/installed')['bin/cargo']==SIGNED
        assert j('receipts/21/custody')['archive_sha256']==outer['artifact_sha']=='6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4'
        assert fact['guard_after']==isolate['guard']
        rec=cases['same-device'];assert rec==j('packet/same-device-immediate') and rec['admitted'] and rec['external_after'] is None
        old,view,held=rec['before'],rec['view_before'],rec['held_after']
        assert old['dev']==view['dev']==held['dev']==rec['parent']['dev'] and old['ino']==held['ino']==view['ino']
        assert old['mount_id']==rec['parent']['mount_id']!=view['mount_id']==rec['before_mount_id']
        assert old['size']==137 and old['nlink']==1 and held['nlink']==0 and old['sha256']==view['sha256']==held['bytes_sha256']
        fixture=Path(isolate['fixture']);shared=Path(isolate['shared']);actual=fixture/'rustup/toolchains/ohm/bin/cargo'
        assert shared.is_relative_to(fixture) and not Path(rec['external_path']).is_relative_to(shared)
        pattern=lambda v:re.escape(str(v))
        all_commands=['signed-cargo-version','regular-ext4-dry','regular-ext4-real','foreign-dry','same-device-dry','same-device-real',
                      'private-enroll','private-same-device-dry','single-overlay-dry']
        streams={}
        for n in all_commands:
            c=j('packet/'+n+'/command')
            assert c['uid']==isolate['user_for_every_cargo']==outer['uid']>0 and c['gid']>0
            stdout,stderr,trace=[take(n,k) for k in ('stdout','stderr','native.trace')]
            assert c['stdout']==sha(stdout) and c['stderr']==sha(stderr)
            native=re.search(rb'^(\d+)\s+[0-9.]+ execve\("'+re.escape(str(actual).encode())+rb'", (\[.*?\]),.*\) = 0$',trace,re.M)
            assert native and json.loads(native[2].decode())[1:]==c['argv'][2:]
            assert c['exit']==(101 if n=='same-device-real' else 0)
            streams[n]=(stderr.decode(),trace.decode().splitlines(),native[1].decode())
        assert b'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c' in take('signed-cargo-version','stdout')
        pre,trace,pid=streams['same-device-dry'];assert 'Summary 1 file, 137B total' in pre and 'Skipping' not in pre
        assert not any('QA_SENTINEL' in l and ('unlink(' in l or 'unlinkat(' in l) for l in trace)
        err,trace,pid=streams['same-device-real'];assert 'Removed 1 file, 137B total' in err and 'Device or resource busy (os error 16)' in err
        trash=Path(rec['view_after']).parent.parent
        oldroot=shared/'debug/build/registries/0123456789abcdef'
        assert trash.parent.parent==shared/'debug/.ohm-gc-trash-v1' and Path(rec['external_path']).name==Path(rec['view_after']).name=='QA_SENTINEL'
        events=[f'rename("{oldroot}", "{trash}") = 0',f'unlink("{rec["view_after"]}") = 0',f'rmdir("{Path(rec["view_after"]).parent}") = -1 EBUSY']
        order=[]
        for event in events:
            index,=[i for i,line in enumerate(trace) if line.startswith(pid+' ') and event in line]
            order.append(index)
        assert order==sorted(order)
        f=cases['foreign'];assert f['external']['dev']==f['seen']['dev']!=f['parent']['dev'] and f['kept'] and not f['real_executed']
        assert 'on a different filesystem; left untouched' in streams['foreign-dry'][0] and 'Summary 0 files' in streams['foreign-dry'][0]
        f=cases['private'];assert f['source']['dev']==f['view']['dev'] and f['source']['ino']==f['view']['ino'] and f['source']['mount_id']!=f['view']['mount_id']
        assert 'would cross mount at ' in streams['private-same-device-dry'][0] and f['kept'] and not f['real_executed']
        f=cases['overlay'];assert f['parent']['mount_id']==f['file']['mount_id'] and f['parent']['dev']!=f['file']['dev']
        assert f['parent']['filesystem']==f['file']['filesystem']=='overlay' and 'Summary 0 files' in streams['single-overlay-dry'][0]
        f=cases['regular'];assert f['before']['filesystem']=='ext4' and f['after'] is None and 'Removed 1 file, 137B total' in streams['regular-ext4-real'][0]
        print(json.dumps({'signed_cargo':SIGNED,'root_scope':'owned Linux shared root','outer_mounts_after':outer['mounts_after'],
              'actual_unlink_syscall':events[1],'signed_cargo_pid':int(pid),'exit':rec['actual_exit'],'held_links':[old['nlink'],held['nlink']],
              'source_and_bind_mounts':[old['mount_id'],view['mount_id']],'single_overlay_mount':f"{cases['overlay']['parent']['mount_id']}",
              'private_foreign_controls':'dry-runs rejected both mounted paths'},sort_keys=True))
if __name__=='__main__':main(Path(sys.argv[1]) if len(sys.argv)>1 else HERE/'native.zip')
