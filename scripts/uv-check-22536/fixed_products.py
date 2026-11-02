"""The 42 ordinary Cargo files actually touched by six rustcs, excluding transient incremental sessions."""
from pathlib import Path
from basis import SIX,filehash
def paths(metadata):
    result=set()
    for crate in SIX:
        f=Path(metadata[crate]);unit=f.parent.parent;assert unit.parent.name==crate.replace('_','-')and f.parent.name=='out'and f.name=='lib'+crate+'-'+unit.name+'.rmeta'
        result|={f,f.with_name(crate+'-'+unit.name+'.d')}
        fp=unit/'fingerprint'
        result|={fp/name for name in('dep-lib-'+crate,'invoked.timestamp','lib-'+crate,'lib-'+crate+'.json','lib-'+crate+'.public-api-hash')}
    assert len(result)==42;return result
def ordinary_stats(root):
    items={}
    for f in root.rglob('*'):
        n=f.relative_to(root)
        if n.parts[:2]==('debug','incremental')or f.is_symlink()or not f.is_file():continue
        stat=f.stat();items[n]=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
    return items
def changed(before,after,expected):
    actual={n for n in before.keys()|after.keys()if before.get(n)!=after.get(n)}
    assert actual==expected,('unexpected changed ordinary Cargo output',sorted(str(n)for n in actual^expected))
def recorded(root,expected):
    return {str(n):[(root/n).stat().st_size,filehash(root/n)]for n in sorted(expected)}
