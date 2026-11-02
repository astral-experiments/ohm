"""Seal the same genuine compiler inode and Cargo's warm compiler-identification input before a real restored edit."""
import hashlib,json
from pathlib import Path

def snapshot(launcher,info):
    assert launcher.is_file() and not launcher.is_symlink() and info.is_file()and not info.is_symlink()
    stat=launcher.stat();data=info.read_bytes();entry=json.loads(data)
    assert set(entry)=={'rustc_fingerprint','outputs','successes'} and type(entry['rustc_fingerprint'])is int and entry['rustc_fingerprint']>0 and len(entry['outputs'])>=1 and isinstance(entry['successes'],dict)
    return {'launcher':str(launcher),'dev':stat.st_dev,'size':stat.st_size,'inode':stat.st_ino,'ctime_ns':stat.st_ctime_ns,'mtime_ns':stat.st_mtime_ns,
            'launcher_sha256':hashlib.file_digest(launcher.open('rb'),'sha256').hexdigest(),'rustc_info_sha256':hashlib.sha256(data).hexdigest(),
            'rustc_fingerprint':entry['rustc_fingerprint'],'cached_queries':len(entry['outputs'])}

def replay(panel,raw,roles,intake,decode):
    """Recheck four seeds and every just-restored Cargo identification cache, then count all actual compiler execs."""
    read=lambda p:json.loads(p.read_bytes())
    checks={};active={}
    for h in (0,1):
        for r in roles:
            bindings=read(panel/f'hold-{h}-{r}/A-launcher-binding.json')
            assert bindings['launcher']=='/tmp/uv-workflow-search/sdk/bin/rustc' and bindings['launcher_sha256']==intake[r]['runtime']['bin/rustc']and bindings['cached_queries']>0
            assert all(bindings[k]>0 for k in ('dev','inode','ctime_ns','mtime_ns','size','rustc_fingerprint'))and len(bindings['rustc_info_sha256'])==64
            active[h,r]=bindings
    for i,row in enumerate(raw):
        for r in roles:
            q=panel/f'pair-{i}-{r}';bound=active[row['hold'],r]
            for name in ('scoped','clock','wall'):assert read(q/(name+'-launcher-binding.json'))==bound
            tr=decode(read(q/'scoped/kernel-events.json'));units=read(q/'scoped/per-rustc.json')['targets']
            fp=[bound['dev'],bound['inode'],bound['size']];rows=[v for v in tr['images']if v['file']==fp or Path(v['exe']).name=='rustc' or v.get('argv') and Path(v['argv'][0]).name=='rustc']
            assert len(rows)==len(units)==8 and len({v['pid']for v in rows})==8
            for n,t in units.items():
                v,=[v for v in rows if v['pid']==t['pid']]
                assert v['argv']==t['argv'] and v['file']==t['file']==fp and t['exe']==bound['launcher'] and t['argv'][t['argv'].index('--crate-name')+1]==n
            checks[f'{i}/{r}']=len(rows)
    return {'one_binding_before_each_restored_measurement':48,'independent_A_checkpoints':len(active),'actual_scoped_rustc_images':sum(checks.values()),'unselected_compiler_images':0,'visits':checks}
