"""Preserve both authentic native byte sequences before refusing a strict same-seed mismatch."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import material as m
def raw(rel):
    p=m.TARGET/rel
    m.guard(p.resolve(strict=True)==p and p.is_relative_to(m.TARGET) and 0<p.stat().st_size<40<<20,'out-of-root raw product')
    return p.read_bytes()
def check(b,stamp):
    m.guard([len(b),m.digest(b)]==stamp,'product digest changed during capture')
def hold(path,manifest):
    ordinary=path/'workspace-rmeta.zip'
    if ordinary.is_file():return
    with ZipFile(path/'same-seed-first.zip','x',ZIP_DEFLATED,compresslevel=2)as z:
        for rel,stamp in sorted(manifest.items()):
            b=raw(rel);check(b,stamp);z.writestr(rel,b)
def require(first,visit,expected,observed):
    m.guard(expected.keys()==observed.keys(),'native product set changed')
    diff=[n for n in sorted(expected)if expected[n]!=observed[n]]
    if not diff:return True
    archived=first/'workspace-rmeta.zip'
    if not archived.is_file():archived=first/'same-seed-first.zip'
    info={}
    with ZipFile(archived)as previous,ZipFile(visit/'refused-raw-pair.zip','x',ZIP_DEFLATED,compresslevel=2)as z:
        for rel in diff:
            l=previous.read(rel);r=raw(rel);check(l,expected[rel]);check(r,observed[rel])
            z.writestr('reference/'+rel,l);z.writestr('comparison/'+rel,r);info[rel]={'reference':expected[rel],'comparison':observed[rel]}
    m.save(visit/'refused-raw-pair.json',{'compared':len(expected),'reference':first.name,'comparison':visit.name,'members':info,'archive_sha256':m.filesha(visit/'refused-raw-pair.zip')})
    raise ValueError('strict raw mismatch; both verified raw byte sequences have been retained')
